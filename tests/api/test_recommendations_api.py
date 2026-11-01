"""Integration tests for SkillPath AI FastAPI application and recommendation endpoints.

Uses an isolated, temporary SQLite database to verify all API contracts,
validation rules, error codes, and responses without touching production data.
"""

from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.db.database import Base, get_db, register_sqlite_pragmas
from src.main import app
from src.models.entities import (
    AssessmentResult,
    Attempt,
    ContentItem,
    ContentSkill,
    Course,
    Learner,
    Recommendation,
    RecommendationOutcome,
    Skill,
)
from src.schemas.recommendations import RecommendationResponse


@pytest.fixture
def api_test_setup(tmp_path: Path):
    """Set up an isolated temporary SQLite database and override get_db dependency."""
    db_path = tmp_path / "test_api.db"
    test_engine = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    register_sqlite_pragmas(test_engine)
    Base.metadata.create_all(bind=test_engine)

    TestSession = sessionmaker(
        bind=test_engine,
        autoflush=False,
        expire_on_commit=False,
    )

    now = datetime(2026, 10, 30, 12, 0, 0)

    # Seed minimal valid domain graph for recommendation tests
    with TestSession() as session:
        # Active beginner learner
        session.add(
            Learner(
                learner_id="LRN-TEST-001",
                first_name="Alice",
                last_name="Tester",
                email="alice@test.skillpath.local",
                experience_level="BEGINNER",
                is_active=True,
                created_at=now,
                updated_at=now,
            )
        )
        # Inactive learner
        session.add(
            Learner(
                learner_id="LRN-TEST-002",
                first_name="Bob",
                last_name="Inactive",
                email="bob@test.skillpath.local",
                experience_level="INTERMEDIATE",
                is_active=False,
                created_at=now,
                updated_at=now,
            )
        )
        # Active Skill
        session.add(
            Skill(
                skill_id="SKL-TEST-001",
                name="Python Fundamentals",
                domain="Programming",
                difficulty_level=0.30,
                description="Introductory Python",
                is_active=True,
                created_at=now,
                updated_at=now,
            )
        )
        # Active Course
        session.add(
            Course(
                course_id="CRS-TEST-001",
                title="Intro to Python",
                code="CS101",
                description="Python course",
                difficulty="BEGINNER",
                is_active=True,
                created_at=now,
                updated_at=now,
            )
        )
        # Active ContentItem
        session.add(
            ContentItem(
                content_id="CNT-TEST-001",
                course_id="CRS-TEST-001",
                title="Variables & Data Types",
                content_type="READING",
                difficulty=0.25,
                duration_minutes=30,
                is_active=True,
                created_at=now,
                updated_at=now,
            )
        )
        # ContentSkill Mapping
        session.add(
            ContentSkill(
                content_id="CNT-TEST-001",
                skill_id="SKL-TEST-001",
                relevance_weight=1.00,
            )
        )
        session.commit()

    def override_get_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as client:
        yield client, TestSession

    app.dependency_overrides.clear()
    test_engine.dispose()


def test_root_endpoint(api_test_setup):
    """Verify root endpoint returns API metadata and links."""
    client, _ = api_test_setup
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["app_name"] == "SkillPath AI"
    assert "documentation" in data
    assert "health" in data


def test_health_check_endpoints(api_test_setup):
    """Verify health check returns healthy status on /health and /api/v1/health."""
    client, _ = api_test_setup

    for path in ["/health", "/api/v1/health"]:
        response = client.get(path)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["database"] == "connected"
        assert data["app_name"] == "SkillPath AI"


def test_health_check_database_error():
    """Verify health check returns 503 when the database check fails."""
    class BrokenSession:
        def execute(self, *args, **kwargs):
            raise RuntimeError("Database connection unreachable")

        def close(self):
            pass

    def broken_get_db():
        yield BrokenSession()

    app.dependency_overrides[get_db] = broken_get_db
    try:
        with TestClient(app) as client:
            response = client.get("/health")
            assert response.status_code == 503
            assert "failed" in response.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


def test_recommendations_active_learner_success(api_test_setup):
    """Verify 200 OK and accurate response schema for active learner recommendations."""
    client, _ = api_test_setup

    response = client.get(
        "/api/v1/learners/LRN-TEST-001/recommendations",
        params={
            "cutoff_timestamp": "2026-10-30T12:00:00",
            "top_k": 5,
        },
    )

    assert response.status_code == 200
    data = response.json()

    # Validate against Pydantic schema
    validated = RecommendationResponse.model_validate(data)
    assert validated.learner_id == "LRN-TEST-001"
    assert len(validated.items) == 1

    item = validated.items[0]
    assert item.content_id == "CNT-TEST-001"
    assert item.title == "Variables & Data Types"
    assert item.target_skill_id == "SKL-TEST-001"
    assert item.primary_reason_code == "COLD_START"
    assert "COLD_START" in item.reason_codes

    # Verify score components
    components = item.score_components
    assert components.gap > Decimal("0")
    assert components.difficulty_suitability > Decimal("0")
    assert components.total > Decimal("0")

    # Verify rejection summary
    assert validated.rejection_summary.inactive_content == 0
    assert validated.rejection_summary.prerequisite_blocked == 0


def test_recommendations_default_cutoff_timestamp(api_test_setup):
    """Verify recommendations work when cutoff_timestamp query parameter is omitted."""
    client, _ = api_test_setup

    response = client.get("/api/v1/learners/LRN-TEST-001/recommendations")
    assert response.status_code == 200
    data = response.json()
    assert data["learner_id"] == "LRN-TEST-001"
    assert "cutoff_timestamp" in data
    assert len(data["items"]) == 1


def test_recommendations_inactive_learner_returns_empty(api_test_setup):
    """Verify inactive learner receives 200 OK with empty items list."""
    client, _ = api_test_setup

    response = client.get(
        "/api/v1/learners/LRN-TEST-002/recommendations",
        params={"cutoff_timestamp": "2026-10-30T12:00:00"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["learner_id"] == "LRN-TEST-002"
    assert data["items"] == []


def test_recommendations_nonexistent_learner_returns_404(api_test_setup):
    """Verify non-existent learner ID returns HTTP 404 Not Found."""
    client, _ = api_test_setup

    response = client.get("/api/v1/learners/LRN-DOES-NOT-EXIST/recommendations")
    assert response.status_code == 404
    data = response.json()
    assert "does not exist" in data["detail"]


def test_recommendations_empty_learner_id_returns_400(api_test_setup):
    """Verify whitespace-only learner ID returns HTTP 400 Bad Request."""
    client, _ = api_test_setup

    response = client.get("/api/v1/learners/%20/recommendations")
    assert response.status_code == 400
    data = response.json()
    assert "non-empty string" in data["detail"]


def test_recommendations_timezone_aware_cutoff_returns_400(api_test_setup):
    """Verify timezone-aware cutoff timestamp returns HTTP 400 Bad Request."""
    client, _ = api_test_setup

    response = client.get(
        "/api/v1/learners/LRN-TEST-001/recommendations",
        params={"cutoff_timestamp": "2026-10-30T12:00:00+05:30"},
    )

    assert response.status_code == 400
    data = response.json()
    assert "timezone-naive" in data["detail"]


def test_recommendations_invalid_cutoff_format_returns_422(api_test_setup):
    """Verify unparseable cutoff timestamp returns HTTP 422 Unprocessable Entity."""
    client, _ = api_test_setup

    response = client.get(
        "/api/v1/learners/LRN-TEST-001/recommendations",
        params={"cutoff_timestamp": "not-a-valid-timestamp"},
    )

    assert response.status_code == 422


@pytest.mark.parametrize("invalid_top_k", [0, -1, -100, "abc"])
def test_recommendations_invalid_top_k_returns_422(api_test_setup, invalid_top_k):
    """Verify invalid top_k (< 1 or non-integer) returns HTTP 422 Unprocessable Entity."""
    client, _ = api_test_setup

    response = client.get(
        "/api/v1/learners/LRN-TEST-001/recommendations",
        params={"top_k": invalid_top_k},
    )

    assert response.status_code == 422


def test_recommendations_persist_true_success(api_test_setup):
    """Verify persist=True returns HTTP 200 and commits records with generated recommendation_id."""
    client, TestSession = api_test_setup

    response = client.get(
        "/api/v1/learners/LRN-TEST-001/recommendations",
        params={"cutoff_timestamp": "2026-10-30T12:00:00", "persist": True},
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 1
    rec_id = data["items"][0]["recommendation_id"]
    assert rec_id is not None
    assert rec_id.startswith("REC-2026-")

    # Verify committed in DB
    with TestSession() as session:
        rec = session.get(Recommendation, rec_id)
        assert rec is not None
        outcome = session.scalar(
            select(RecommendationOutcome).where(
                RecommendationOutcome.recommendation_id == rec_id
            )
        )
        assert outcome is not None
        assert outcome.outcome_status == "RECOMMENDED"


def test_outcome_lifecycle_api_flow(api_test_setup):
    """Verify full outcome API lifecycle: persist -> start -> complete -> evaluate."""
    client, TestSession = api_test_setup

    # Step 1: Generate & persist recommendation
    res = client.get(
        "/api/v1/learners/LRN-TEST-001/recommendations",
        params={"cutoff_timestamp": "2026-10-30T12:00:00", "persist": True},
    )
    assert res.status_code == 200
    rec_id = res.json()["items"][0]["recommendation_id"]

    # Step 2: Seed attempt and assessment in DB
    t_start = datetime(2026, 10, 30, 12, 15, 0)
    t_graded = datetime(2026, 10, 30, 13, 0, 0)
    with TestSession() as session:
        attempt = Attempt(
            attempt_id="ATT-API-001",
            learner_id="LRN-TEST-001",
            content_id="CNT-TEST-001",
            attempt_number=1,
            started_at=t_start,
            completed_at=t_graded,
            status="COMPLETED",
        )
        assessment = AssessmentResult(
            result_id="RES-API-001",
            attempt_id="ATT-API-001",
            raw_score=85.0,
            max_score=100.0,
            normalized_score=0.8500,
            is_passed=True,
            graded_at=t_graded,
        )
        session.add_all([attempt, assessment])
        session.commit()

    # Step 3: POST start
    start_res = client.post(
        f"/api/v1/recommendations/{rec_id}/start",
        json={"attempt_id": "ATT-API-001"},
    )
    assert start_res.status_code == 200
    assert start_res.json()["outcome_status"] == "STARTED"
    assert start_res.json()["interaction_attempt_id"] == "ATT-API-001"

    # Step 4: POST complete
    comp_res = client.post(
        f"/api/v1/recommendations/{rec_id}/complete",
        json={"completed_at": t_graded.isoformat()},
    )
    assert comp_res.status_code == 200
    assert comp_res.json()["outcome_status"] == "COMPLETED"

    # Step 5: POST evaluate
    eval_res = client.post(f"/api/v1/recommendations/{rec_id}/evaluate")
    assert eval_res.status_code == 200
    eval_data = eval_res.json()
    assert eval_data["outcome_status"] == "IMPROVED"
    assert Decimal(eval_data["mastery_delta"]) > Decimal("0")


def test_outcome_abandon_and_terminal_rejection_api(api_test_setup):
    """Verify abandoning a recommendation and rejecting further transitions from terminal state."""
    client, TestSession = api_test_setup

    res = client.get(
        "/api/v1/learners/LRN-TEST-001/recommendations",
        params={"cutoff_timestamp": "2026-10-30T12:00:00", "persist": True},
    )
    rec_id = res.json()["items"][0]["recommendation_id"]

    # Seed attempt
    with TestSession() as session:
        attempt = Attempt(
            attempt_id="ATT-API-ABANDON",
            learner_id="LRN-TEST-001",
            content_id="CNT-TEST-001",
            attempt_number=1,
            started_at=datetime(2026, 10, 30, 12, 15, 0),
            status="IN_PROGRESS",
        )
        session.add(attempt)
        session.commit()

    # Start
    client.post(
        f"/api/v1/recommendations/{rec_id}/start",
        json={"attempt_id": "ATT-API-ABANDON"},
    )

    # Abandon
    abandon_res = client.post(
        f"/api/v1/recommendations/{rec_id}/abandon",
        json={},
    )
    assert abandon_res.status_code == 200
    assert abandon_res.json()["outcome_status"] == "ABANDONED"

    # Further transition attempt -> 409 Conflict
    re_start_res = client.post(
        f"/api/v1/recommendations/{rec_id}/start",
        json={"attempt_id": "ATT-API-ABANDON"},
    )
    assert re_start_res.status_code == 409


def test_outcome_api_error_responses(api_test_setup):
    """Verify 404, 400, and 409 HTTP status codes for invalid outcome operations."""
    client, TestSession = api_test_setup

    # 404 for non-existent recommendation
    res_404 = client.post(
        "/api/v1/recommendations/REC-DOES-NOT-EXIST/start",
        json={"attempt_id": "ATT-123"},
    )
    assert res_404.status_code == 404

    # Generate valid recommendation
    res = client.get(
        "/api/v1/learners/LRN-TEST-001/recommendations",
        params={"cutoff_timestamp": "2026-10-30T12:00:00", "persist": True},
    )
    rec_id = res.json()["items"][0]["recommendation_id"]

    # 400 for non-existent attempt
    res_400 = client.post(
        f"/api/v1/recommendations/{rec_id}/start",
        json={"attempt_id": "ATT-NONEXISTENT"},
    )
    assert res_400.status_code == 400

    # 409 for complete without start
    res_409 = client.post(
        f"/api/v1/recommendations/{rec_id}/complete",
        json={},
    )
    assert res_409.status_code == 409


def test_get_learner_overview_endpoint_success(api_test_setup):
    """Verify GET /api/v1/learners/{learner_id}/overview returns valid profile & activity telemetry."""
    client, TestSession = api_test_setup

    response = client.get("/api/v1/learners/LRN-TEST-001/overview")
    assert response.status_code == 200, f"Error: {response.text}"
    data = response.json()

    assert data["learner_id"] == "LRN-TEST-001"
    assert data["first_name"] == "Alice"
    assert data["experience_level"] == "BEGINNER"
    assert isinstance(data["total_attempts"], int)
    assert isinstance(data["completed_attempts"], int)
    assert isinstance(data["skills_needing_attention"], list)
    assert isinstance(data["recent_activities"], list)
    assert isinstance(data["recommended_preview"], list)


def test_get_learner_overview_endpoint_not_found(api_test_setup):
    """Verify GET /api/v1/learners/{learner_id}/overview returns 404 for non-existent learner."""
    client, TestSession = api_test_setup

    response = client.get("/api/v1/learners/LRN-DOES-NOT-EXIST/overview")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()

