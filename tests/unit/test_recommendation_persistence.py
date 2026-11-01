"""Unit tests for recommendation persistence in RecommendationService using an isolated database."""

from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from src.db.database import Base, register_sqlite_pragmas
from src.models.entities import (
    ContentItem,
    ContentSkill,
    Course,
    Learner,
    Recommendation,
    RecommendationOutcome,
    Skill,
)
from src.services.recommendation_service import (
    RecommendationIdAllocator,
    RecommendationService,
)


@pytest.fixture
def persistence_db(tmp_path: Path):
    """Create an isolated SQLite database fixture for persistence tests."""
    db_path = tmp_path / "persistence_test.db"
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
    with TestSession() as session:
        learner = Learner(
            learner_id="LRN-PERSIST-001",
            first_name="Persist",
            last_name="Learner",
            email="persist@test.local",
            experience_level="BEGINNER",
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        course = Course(
            course_id="CRS-PERSIST-001",
            title="Course 1",
            code="C1",
            difficulty="BEGINNER",
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        skill = Skill(
            skill_id="SKL-PERSIST-001",
            name="Python Basics",
            domain="Computer Science",
            difficulty_level=0.25,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        content = ContentItem(
            content_id="CNT-PERSIST-001",
            course_id="CRS-PERSIST-001",
            title="Basics Lesson",
            content_type="READING",
            difficulty=0.20,
            duration_minutes=25,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        content_skill = ContentSkill(
            content_id="CNT-PERSIST-001",
            skill_id="SKL-PERSIST-001",
            relevance_weight=1.00,
        )
        session.add_all([learner, course, skill, content, content_skill])
        session.commit()

    try:
        yield test_engine, TestSession
    finally:
        test_engine.dispose()


def test_persist_false_does_not_mutate_database(persistence_db):
    """Verify persist=False produces recommendations without inserting rows."""
    _, TestSession = persistence_db

    with TestSession() as session:
        service = RecommendationService(session)
        batch = service.get_recommendations(
            learner_id="LRN-PERSIST-001",
            cutoff_timestamp=datetime(2026, 10, 30, 12, 0, 0),
            persist=False,
        )

        assert len(batch.items) == 1
        assert batch.items[0].recommendation_id is None

        rec_count = session.scalar(select(func.count()).select_from(Recommendation))
        outcome_count = session.scalar(select(func.count()).select_from(RecommendationOutcome))
        assert rec_count == 0
        assert outcome_count == 0


def test_persist_true_inserts_recommendation_and_initial_outcome(persistence_db):
    """Verify persist=True creates Recommendation and initial RECOMMENDED outcome."""
    _, TestSession = persistence_db

    cutoff = datetime(2026, 10, 30, 12, 0, 0)
    with TestSession() as session:
        service = RecommendationService(session)
        batch = service.get_recommendations(
            learner_id="LRN-PERSIST-001",
            cutoff_timestamp=cutoff,
            persist=True,
        )
        session.commit()

        assert len(batch.items) == 1
        rec_id = batch.items[0].recommendation_id
        assert rec_id is not None
        assert rec_id.startswith("REC-2026-")

        # Verify persisted Recommendation record
        rec = session.get(Recommendation, rec_id)
        assert rec is not None
        assert rec.learner_id == "LRN-PERSIST-001"
        assert rec.content_id == "CNT-PERSIST-001"
        assert rec.target_skill_id == "SKL-PERSIST-001"
        assert rec.decision_timestamp == cutoff
        assert rec.rank_position == 1
        assert Decimal("0.0") <= Decimal(str(rec.recommendation_score)) <= Decimal("1.0")
        assert rec.primary_reason_code == "COLD_START"
        assert rec.algorithm_version == "v1.1.0"

        # Verify valid and deterministic JSON fields
        components = json.loads(rec.score_components_json)
        assert "gap" in components
        assert "difficulty_suitability" in components
        assert "path_alignment" in components
        assert "practice_urgency" in components
        assert "total" in components

        audit = json.loads(rec.rejection_audit_json)
        assert audit["inactive_content"] == 0
        assert audit["prerequisite_blocked"] == 0

        # Verify initial RecommendationOutcome record
        outcome = session.scalar(
            select(RecommendationOutcome).where(
                RecommendationOutcome.recommendation_id == rec_id
            )
        )
        assert outcome is not None
        assert outcome.outcome_id == f"OUT-{rec_id}"
        assert outcome.outcome_status == "RECOMMENDED"
        assert outcome.interaction_attempt_id is None
        assert outcome.mastery_delta is None
        assert outcome.recorded_at == cutoff


def test_idempotent_persist_does_not_create_duplicates(persistence_db):
    """Verify repeated persist=True calls with identical learner and cutoff return existing batch."""
    _, TestSession = persistence_db

    cutoff = datetime(2026, 10, 30, 12, 0, 0)
    with TestSession() as session:
        service = RecommendationService(session)

        # First call
        batch1 = service.get_recommendations(
            learner_id="LRN-PERSIST-001",
            cutoff_timestamp=cutoff,
            persist=True,
        )
        session.commit()

        # Second call (retry)
        batch2 = service.get_recommendations(
            learner_id="LRN-PERSIST-001",
            cutoff_timestamp=cutoff,
            persist=True,
        )
        session.commit()

        assert batch1.items[0].recommendation_id == batch2.items[0].recommendation_id
        rec_count = session.scalar(select(func.count()).select_from(Recommendation))
        assert rec_count == 1


def test_persistence_rollback_atomicity(persistence_db):
    """Verify transaction rollback leaves 0 recommendations and 0 outcomes if an error occurs."""
    _, TestSession = persistence_db

    cutoff = datetime(2026, 10, 30, 12, 0, 0)
    with TestSession() as session:
        service = RecommendationService(session)

        batch = service.get_recommendations(
            learner_id="LRN-PERSIST-001",
            cutoff_timestamp=cutoff,
            persist=True,
        )

        # Simulate transaction rollback by caller
        session.rollback()

        rec_count = session.scalar(select(func.count()).select_from(Recommendation))
        outcome_count = session.scalar(select(func.count()).select_from(RecommendationOutcome))
        assert rec_count == 0
        assert outcome_count == 0


def test_concurrency_safe_id_allocator(persistence_db):
    """Verify RecommendationIdAllocator sequentially increments without collisions."""
    _, TestSession = persistence_db

    with TestSession() as session:
        ids1 = RecommendationIdAllocator.allocate_ids(session, count=3, year=2026)
        assert ids1 == ["REC-2026-000001", "REC-2026-000002", "REC-2026-000003"]

        # Insert a recommendation with the 3rd id
        now = datetime(2026, 10, 30, 12, 0, 0)
        session.add(
            Recommendation(
                recommendation_id="REC-2026-000003",
                learner_id="LRN-PERSIST-001",
                content_id="CNT-PERSIST-001",
                target_skill_id="SKL-PERSIST-001",
                decision_timestamp=now,
                rank_position=1,
                recommendation_score=0.85,
                primary_reason_code="COLD_START",
                score_components_json="{}",
                algorithm_version="v1.1.0",
            )
        )
        session.commit()

        # Subsequent allocation picks up high-water mark
        ids2 = RecommendationIdAllocator.allocate_ids(session, count=2, year=2026)
        assert ids2 == ["REC-2026-000004", "REC-2026-000005"]
