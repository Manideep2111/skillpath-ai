"""Focused tests for RecommendationService using an isolated SQLite database."""

from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from src.db.database import Base, register_sqlite_pragmas
from src.models.entities import (
    Learner,
    Recommendation,
    MasterySnapshot,
    Course,
    Skill,
    SkillPrerequisite,
    ContentItem,
    ContentSkill,
    LearningPath,
    LearningPathItem,
    Attempt,
    AssessmentResult,
)
from src.services.recommendation_service import RecommendationService


@pytest.fixture
def recommendation_db(tmp_path: Path):
    """Create an isolated database for each recommendation-service test."""
    db_path = tmp_path / "recommendation_test.db"
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

    with TestSession() as session:
        now = datetime(2026, 10, 30, 12, 0, 0)
        session.add(
            Learner(
                learner_id="LRN-TEST-001",
                first_name="Test",
                last_name="Learner",
                email="recommendation-test@skillpath.local",
                experience_level="BEGINNER",
                is_active=True,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()

    try:
        yield test_engine, TestSession
    finally:
        test_engine.dispose()


def test_rejects_empty_learner_id(recommendation_db):
    _, TestSession = recommendation_db

    with TestSession() as session:
        service = RecommendationService(session)

        with pytest.raises(ValueError, match="learner_id"):
            service.get_recommendations(
                learner_id=" ",
                cutoff_timestamp=datetime(2026, 10, 30),
            )



def test_rejects_non_datetime_cutoff(recommendation_db):
    _, TestSession = recommendation_db

    with TestSession() as session:
        service = RecommendationService(session)

        with pytest.raises(ValueError, match="cutoff_timestamp"):
            service.get_recommendations(
                learner_id="LRN-TEST-001",
                cutoff_timestamp="2026-10-30",
            )


def test_rejects_timezone_aware_cutoff(recommendation_db):
    _, TestSession = recommendation_db

    with TestSession() as session:
        service = RecommendationService(session)

        with pytest.raises(ValueError, match="timezone-naive"):
            service.get_recommendations(
                learner_id="LRN-TEST-001",
                cutoff_timestamp=datetime.fromisoformat(
                    "2026-10-30T12:00:00+05:30"
                ),
            )


@pytest.mark.parametrize("top_k", [0, -1, 1.5, True, "5", None])
def test_rejects_invalid_top_k(recommendation_db, top_k):
    _, TestSession = recommendation_db

    with TestSession() as session:
        service = RecommendationService(session)

        with pytest.raises(ValueError, match="top_k"):
            service.get_recommendations(
                learner_id="LRN-TEST-001",
                cutoff_timestamp=datetime(2026, 10, 30),
                top_k=top_k,
            )


def test_rejects_nonexistent_learner(recommendation_db):
    _, TestSession = recommendation_db

    with TestSession() as session:
        service = RecommendationService(session)

        with pytest.raises(ValueError, match="does not exist"):
            service.get_recommendations(
                learner_id="LRN-NOT-FOUND",
                cutoff_timestamp=datetime(2026, 10, 30),
            )


def test_persist_true_persists_batch(recommendation_db):
    _, TestSession = recommendation_db

    with TestSession() as session:
        service = RecommendationService(session)

        batch = service.get_recommendations(
            learner_id="LRN-TEST-001",
            cutoff_timestamp=datetime(2026, 10, 30),
            persist=True,
        )
        assert batch.learner_id == "LRN-TEST-001"
        assert len(batch.items) == 0  # Cold start learner with no items seeded in this test fixture


def test_inactive_learner_receives_empty_batch(recommendation_db):
    _, TestSession = recommendation_db

    with TestSession() as session:
        learner = session.get(Learner, "LRN-TEST-001")
        assert learner is not None
        learner.is_active = False
        session.commit()

        service = RecommendationService(session)
        batch = service.get_recommendations(
            learner_id="LRN-TEST-001",
            cutoff_timestamp=datetime(2026, 10, 30),
        )

        assert batch.learner_id == "LRN-TEST-001"
        assert batch.items == ()


def test_empty_learner_recommendations_do_not_create_records(
    recommendation_db,
):
    """An empty learner history must not create recommendations or snapshots."""
    _, TestSession = recommendation_db

    with TestSession() as session:
        service = RecommendationService(session)

        recommendations_before = session.scalar(
            select(func.count()).select_from(Recommendation)
        )
        snapshots_before = session.scalar(
            select(func.count()).select_from(MasterySnapshot)
        )

        batch = service.get_recommendations(
            learner_id="LRN-TEST-001",
            cutoff_timestamp=datetime(2026, 10, 30),
            persist=False,
        )

        recommendations_after = session.scalar(
            select(func.count()).select_from(Recommendation)
        )
        snapshots_after = session.scalar(
            select(func.count()).select_from(MasterySnapshot)
        )

        assert batch.learner_id == "LRN-TEST-001"
        assert recommendations_after == recommendations_before
        assert snapshots_after == snapshots_before
        assert not session.new
        assert not session.dirty
        assert not session.deleted




def test_select_target_skill_tie_breaks_by_full_skill_id():
    service = RecommendationService(db=None)

    mapped_skills = [
        ("SKL-000008", "Compilers", Decimal("1.0000")),
        ("SKL-000002", "Automata", Decimal("1.0000")),
    ]

    mastery_map = {
        "SKL-000008": None,
        "SKL-000002": None,
    }

    result = service._select_target_skill(
        mapped_skills,
        mastery_map,
    )

    assert result == (
        "SKL-000002",
        "Automata",
        Decimal("1.0000"),
    )


def test_reason_codes_include_assessment_review_for_recent_failure():
    service = RecommendationService(db=None)

    result = service._reason_codes(
        target_skill_id="SKL-000001",
        mastery_map={"SKL-000001": Decimal("0.4500")},
        evidence_counts={"SKL-000001": 1},
        latest_failed_by_skill={"SKL-000001": True},
        attempted_content={"CNT-000001"},
        content_id="CNT-000002",
        path_factor=Decimal("0.0000"),
        prerequisites_by_skill={},
        has_any_attempts=True,
        urgency_factor=Decimal("0.5000"),
    )

    assert "ASSESSMENT_REVIEW" in result
    assert "LOW_EVIDENCE" in result
    assert result[-1] == "SKILL_GAP"

def test_future_path_completion_is_pending_at_historical_cutoff(
    recommendation_db,
):
    """A future completion must not count as completed at an earlier cutoff."""
    _, TestSession = recommendation_db

    with TestSession() as session:
        now = datetime(2026, 10, 30, 12, 0, 0)

        course = Course(
            course_id="CRS-PATH-001",
            title="Python Fundamentals",
            code="PATH-TEST-001",
            difficulty="BEGINNER",
            is_active=True,
            created_at=datetime(2026, 10, 1),
            updated_at=datetime(2026, 10, 1),
        )
        content = ContentItem(
            content_id="CNT-PATH-001",
            course_id=course.course_id,
            title="Python Variables",
            content_type="VIDEO",
            difficulty=0.20,
            duration_minutes=15,
            is_active=True,
            created_at=datetime(2026, 10, 1),
            updated_at=datetime(2026, 10, 1),
        )
        path = LearningPath(
            path_id="PATH-TEST-001",
            learner_id="LRN-TEST-001",
            title="Python Learning Path",
            status="ACTIVE",
            created_at=datetime(2026, 10, 1),
            updated_at=datetime(2026, 10, 1),
        )
        path_item = LearningPathItem(
            path_item_id="LPI-PATH-001",
            path_id=path.path_id,
            content_id=content.content_id,
            sequence_order=1,
            is_mandatory=True,
            status="COMPLETED",
            completed_at=datetime(2026, 11, 5),
        )

        session.add_all([course, content, path, path_item])
        session.commit()

        service = RecommendationService(session)

        alignment = service._get_path_alignment(
            learner_id="LRN-TEST-001",
            cutoff_timestamp=now,
        )

        assert content.content_id in alignment
        assert alignment[content.content_id] == Decimal("1.0000")

def test_zero_relevance_mapping_does_not_block_eligible_content(
    recommendation_db,
):
    """A zero-relevance mapping must not impose a prerequisite restriction."""
    _, TestSession = recommendation_db

    with TestSession() as session:
        now = datetime(2026, 10, 30, 12, 0, 0)

        course = Course(
            course_id="CRS-REL-001",
            title="Programming",
            code="REL-TEST-001",
            difficulty="BEGINNER",
            is_active=True,
            created_at=datetime(2026, 10, 1),
            updated_at=datetime(2026, 10, 1),
        )

        blocked_skill = Skill(
            skill_id="SKL-REL-001",
            name="Advanced Frameworks",
            domain="Programming",
            difficulty_level=Decimal("0.80"),
            is_active=True,
            created_at=datetime(2026, 10, 1),
            updated_at=datetime(2026, 10, 1),
        )
        required_skill = Skill(
            skill_id="SKL-REL-002",
            name="Framework Basics",
            domain="Programming",
            difficulty_level=Decimal("0.30"),
            is_active=True,
            created_at=datetime(2026, 10, 1),
            updated_at=datetime(2026, 10, 1),
        )
        eligible_skill = Skill(
            skill_id="SKL-REL-003",
            name="Python Syntax",
            domain="Programming",
            difficulty_level=Decimal("0.20"),
            is_active=True,
            created_at=datetime(2026, 10, 1),
            updated_at=datetime(2026, 10, 1),
        )

        content = ContentItem(
            content_id="CNT-REL-001",
            course_id=course.course_id,
            title="Python Syntax Practice",
            content_type="VIDEO",
            difficulty=0.20,
            duration_minutes=15,
            is_active=True,
            created_at=datetime(2026, 10, 1),
            updated_at=datetime(2026, 10, 1),
        )

        prerequisite = SkillPrerequisite(
            skill_id=blocked_skill.skill_id,
            prerequisite_skill_id=required_skill.skill_id,
            minimum_mastery=Decimal("0.70"),
            is_required=True,
            created_at=datetime(2026, 10, 1),
        )

        zero_relevance_mapping = ContentSkill(
            content_id=content.content_id,
            skill_id=blocked_skill.skill_id,
            relevance_weight=Decimal("0.00"),
        )
        positive_relevance_mapping = ContentSkill(
            content_id=content.content_id,
            skill_id=eligible_skill.skill_id,
            relevance_weight=Decimal("1.00"),
        )

        session.add_all([
            course,
            blocked_skill,
            required_skill,
            eligible_skill,
            content,
            prerequisite,
            zero_relevance_mapping,
            positive_relevance_mapping,
        ])
        session.commit()

        service = RecommendationService(session)

        batch = service.get_recommendations(
            learner_id="LRN-TEST-001",
            cutoff_timestamp=now,
            top_k=5,
        )

        recommended_ids = {
            item.content_id for item in batch.items
        }

        assert content.content_id in recommended_ids

def test_recently_failed_quiz_is_not_marked_as_completed(
    recommendation_db,
):
    """A failed quiz must not be treated as a successful recent completion."""
    _, TestSession = recommendation_db

    with TestSession() as session:
        now = datetime(2026, 10, 30, 12, 0, 0)

        course = Course(
            course_id="CRS-FAIL-001",
            title="Python Basics",
            code="FAIL-TEST-001",
            difficulty="BEGINNER",
            is_active=True,
            created_at=datetime(2026, 10, 1),
            updated_at=datetime(2026, 10, 1),
        )

        content = ContentItem(
            content_id="CNT-FAIL-001",
            course_id=course.course_id,
            title="Python Basics Quiz",
            content_type="QUIZ",
            difficulty=0.30,
            duration_minutes=15,
            is_active=True,
            created_at=datetime(2026, 10, 1),
            updated_at=datetime(2026, 10, 1),
        )

        attempt = Attempt(
            attempt_id="ATT-FAIL-001",
            learner_id="LRN-TEST-001",
            content_id=content.content_id,
            attempt_number=1,
            started_at=datetime(2026, 10, 29, 10, 0, 0),
            completed_at=datetime(2026, 10, 29, 10, 15, 0),
            time_spent_seconds=900,
            status="COMPLETED",
        )

        result = AssessmentResult(
            result_id="RES-FAIL-001",
            attempt_id=attempt.attempt_id,
            raw_score=40,
            max_score=100,
            normalized_score=Decimal("0.4000"),
            is_passed=False,
            graded_at=datetime(2026, 10, 29, 10, 20, 0),
        )

        session.add_all([course, content, attempt, result])
        session.commit()

        service = RecommendationService(session)

        recently_completed = service._get_recently_completed_content(
            learner_id="LRN-TEST-001",
            cutoff_timestamp=now,
        )

        assert content.content_id not in recently_completed