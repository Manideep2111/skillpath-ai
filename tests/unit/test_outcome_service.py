"""Unit tests for OutcomeTrackingService and recommendation outcome lifecycle."""

from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.database import Base, register_sqlite_pragmas
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
from src.services.outcome_service import (
    InvalidInteractionAttemptError,
    InvalidStateTransitionError,
    OutcomeTrackingService,
    RecommendationNotFoundError,
)


@pytest.fixture
def outcome_db(tmp_path: Path):
    """Set up an isolated database with baseline domain records for outcome testing."""
    db_path = tmp_path / "outcome_test.db"
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

    t0 = datetime(2026, 10, 30, 10, 0, 0)
    with TestSession() as session:
        learner1 = Learner(
            learner_id="LRN-OUT-001",
            first_name="Alice",
            last_name="Tester",
            email="alice@test.local",
            experience_level="BEGINNER",
            is_active=True,
            created_at=t0,
            updated_at=t0,
        )
        learner2 = Learner(
            learner_id="LRN-OUT-002",
            first_name="Bob",
            last_name="Other",
            email="bob@test.local",
            experience_level="INTERMEDIATE",
            is_active=True,
            created_at=t0,
            updated_at=t0,
        )
        course = Course(
            course_id="CRS-OUT-001",
            title="Algorithms",
            code="ALG101",
            difficulty="BEGINNER",
            is_active=True,
            created_at=t0,
            updated_at=t0,
        )
        skill = Skill(
            skill_id="SKL-OUT-001",
            name="Binary Search",
            domain="Algorithms",
            difficulty_level=0.35,
            is_active=True,
            created_at=t0,
            updated_at=t0,
        )
        content1 = ContentItem(
            content_id="CNT-OUT-001",
            course_id="CRS-OUT-001",
            title="Binary Search Lab",
            content_type="LAB",
            difficulty=0.30,
            duration_minutes=45,
            is_active=True,
            created_at=t0,
            updated_at=t0,
        )
        content2 = ContentItem(
            content_id="CNT-OUT-002",
            course_id="CRS-OUT-001",
            title="Sorting Video",
            content_type="VIDEO",
            difficulty=0.20,
            duration_minutes=20,
            is_active=True,
            created_at=t0,
            updated_at=t0,
        )
        cs1 = ContentSkill(
            content_id="CNT-OUT-001",
            skill_id="SKL-OUT-001",
            relevance_weight=1.00,
        )
        cs2 = ContentSkill(
            content_id="CNT-OUT-002",
            skill_id="SKL-OUT-001",
            relevance_weight=0.50,
        )

        rec = Recommendation(
            recommendation_id="REC-2026-000001",
            learner_id="LRN-OUT-001",
            content_id="CNT-OUT-001",
            target_skill_id="SKL-OUT-001",
            decision_timestamp=datetime(2026, 10, 30, 12, 0, 0),
            rank_position=1,
            recommendation_score=0.88,
            primary_reason_code="SKILL_GAP",
            score_components_json="{}",
            algorithm_version="v1.1.0",
        )
        outcome = RecommendationOutcome(
            outcome_id="OUT-REC-2026-000001",
            recommendation_id="REC-2026-000001",
            outcome_status="RECOMMENDED",
            recorded_at=datetime(2026, 10, 30, 12, 0, 0),
        )

        session.add_all([learner1, learner2, course, skill, content1, content2, cs1, cs2, rec, outcome])
        session.commit()

    try:
        yield test_engine, TestSession
    finally:
        test_engine.dispose()


def test_start_recommendation_success(outcome_db):
    """Verify RECOMMENDED -> STARTED transition links attempt and records timestamp."""
    _, TestSession = outcome_db

    with TestSession() as session:
        t_start = datetime(2026, 10, 30, 12, 30, 0)
        attempt = Attempt(
            attempt_id="ATT-OUT-001",
            learner_id="LRN-OUT-001",
            content_id="CNT-OUT-001",
            attempt_number=1,
            started_at=t_start,
            status="IN_PROGRESS",
        )
        session.add(attempt)
        session.commit()

        service = OutcomeTrackingService(session)
        outcome = service.record_interaction_start(
            recommendation_id="REC-2026-000001",
            attempt_id="ATT-OUT-001",
        )
        session.commit()

        assert outcome.outcome_status == "STARTED"
        assert outcome.interaction_attempt_id == "ATT-OUT-001"
        assert outcome.recorded_at == t_start


def test_abandon_recommendation_success(outcome_db):
    """Verify STARTED -> ABANDONED transition sets terminal status."""
    _, TestSession = outcome_db

    with TestSession() as session:
        t_start = datetime(2026, 10, 30, 12, 30, 0)
        attempt = Attempt(
            attempt_id="ATT-OUT-001",
            learner_id="LRN-OUT-001",
            content_id="CNT-OUT-001",
            attempt_number=1,
            started_at=t_start,
            status="IN_PROGRESS",
        )
        session.add(attempt)
        session.commit()

        service = OutcomeTrackingService(session)
        service.record_interaction_start("REC-2026-000001", "ATT-OUT-001")
        outcome = service.record_interaction_abandonment("REC-2026-000001")
        session.commit()

        assert outcome.outcome_status == "ABANDONED"

        # Rejection of further transition from terminal state
        with pytest.raises(InvalidStateTransitionError, match="terminal state"):
            service.record_interaction_completion("REC-2026-000001")


def test_complete_and_evaluate_improvement(outcome_db):
    """Verify STARTED -> COMPLETED -> IMPROVED calculation when post-mastery exceeds pre-mastery."""
    _, TestSession = outcome_db

    with TestSession() as session:
        # Prior assessment established pre-mastery = 0.5000 at 11:00 (before rec at 12:00)
        t_prior = datetime(2026, 10, 30, 11, 0, 0)
        att_prior = Attempt(
            attempt_id="ATT-PRIOR-001",
            learner_id="LRN-OUT-001",
            content_id="CNT-OUT-001",
            attempt_number=1,
            started_at=t_prior - timedelta(minutes=30),
            completed_at=t_prior,
            status="COMPLETED",
        )
        res_prior = AssessmentResult(
            result_id="RES-PRIOR-001",
            attempt_id="ATT-PRIOR-001",
            raw_score=50.0,
            max_score=100.0,
            normalized_score=0.5000,
            is_passed=False,
            graded_at=t_prior,
        )

        # Recommended interaction attempt completed at 13:00, scored 90% (0.9000)
        t_start = datetime(2026, 10, 30, 12, 15, 0)
        t_graded = datetime(2026, 10, 30, 13, 0, 0)
        att_post = Attempt(
            attempt_id="ATT-POST-001",
            learner_id="LRN-OUT-001",
            content_id="CNT-OUT-001",
            attempt_number=2,
            started_at=t_start,
            completed_at=t_graded,
            status="COMPLETED",
        )
        res_post = AssessmentResult(
            result_id="RES-POST-001",
            attempt_id="ATT-POST-001",
            raw_score=90.0,
            max_score=100.0,
            normalized_score=0.9000,
            is_passed=True,
            graded_at=t_graded,
        )
        session.add_all([att_prior, res_prior, att_post, res_post])
        session.commit()

        service = OutcomeTrackingService(session)
        service.record_interaction_start("REC-2026-000001", "ATT-POST-001")
        outcome, pre_m, post_m, delta = service.evaluate_outcome("REC-2026-000001")
        session.commit()

        assert outcome.outcome_status == "IMPROVED"
        assert pre_m is not None and pre_m == Decimal("0.5000")
        assert post_m is not None and post_m > pre_m
        assert delta is not None and delta > Decimal("0")
        assert outcome.mastery_delta is not None and outcome.mastery_delta > 0.0


def test_evaluate_unknown_pre_mastery_gain(outcome_db):
    """Verify cold-start learner (unknown pre-mastery) evaluates to IMPROVED upon demonstrating mastery."""
    _, TestSession = outcome_db

    with TestSession() as session:
        # Learner has NO prior attempts (unknown pre-mastery).
        t_start = datetime(2026, 10, 30, 12, 15, 0)
        t_graded = datetime(2026, 10, 30, 13, 0, 0)
        att_post = Attempt(
            attempt_id="ATT-COLD-001",
            learner_id="LRN-OUT-001",
            content_id="CNT-OUT-001",
            attempt_number=1,
            started_at=t_start,
            completed_at=t_graded,
            status="COMPLETED",
        )
        res_post = AssessmentResult(
            result_id="RES-COLD-001",
            attempt_id="ATT-COLD-001",
            raw_score=80.0,
            max_score=100.0,
            normalized_score=0.8000,
            is_passed=True,
            graded_at=t_graded,
        )
        session.add_all([att_post, res_post])
        session.commit()

        service = OutcomeTrackingService(session)
        service.record_interaction_start("REC-2026-000001", "ATT-COLD-001")
        outcome, pre_m, post_m, delta = service.evaluate_outcome("REC-2026-000001")
        session.commit()

        assert pre_m is None  # Confirmed UNKNOWN, not silent zero
        assert post_m == Decimal("0.8000")
        assert delta == Decimal("0.8000")
        assert outcome.outcome_status == "IMPROVED"


def test_evaluate_no_improvement(outcome_db):
    """Verify outcome is NO_IMPROVEMENT when post-mastery <= pre-mastery."""
    _, TestSession = outcome_db

    with TestSession() as session:
        # Prior assessment scored 95% at 11:00
        t_prior = datetime(2026, 10, 30, 11, 0, 0)
        att_prior = Attempt(
            attempt_id="ATT-PRIOR-002",
            learner_id="LRN-OUT-001",
            content_id="CNT-OUT-001",
            attempt_number=1,
            started_at=t_prior - timedelta(minutes=30),
            completed_at=t_prior,
            status="COMPLETED",
        )
        res_prior = AssessmentResult(
            result_id="RES-PRIOR-002",
            attempt_id="ATT-PRIOR-002",
            raw_score=95.0,
            max_score=100.0,
            normalized_score=0.9500,
            is_passed=True,
            graded_at=t_prior,
        )

        # Recommended interaction attempt scored 60%
        t_start = datetime(2026, 10, 30, 12, 15, 0)
        t_graded = datetime(2026, 10, 30, 13, 0, 0)
        att_post = Attempt(
            attempt_id="ATT-POST-002",
            learner_id="LRN-OUT-001",
            content_id="CNT-OUT-001",
            attempt_number=2,
            started_at=t_start,
            completed_at=t_graded,
            status="COMPLETED",
        )
        res_post = AssessmentResult(
            result_id="RES-POST-002",
            attempt_id="ATT-POST-002",
            raw_score=60.0,
            max_score=100.0,
            normalized_score=0.6000,
            is_passed=False,
            graded_at=t_graded,
        )
        session.add_all([att_prior, res_prior, att_post, res_post])
        session.commit()

        service = OutcomeTrackingService(session)
        service.record_interaction_start("REC-2026-000001", "ATT-POST-002")
        outcome, pre_m, post_m, delta = service.evaluate_outcome("REC-2026-000001")
        session.commit()

        assert outcome.outcome_status == "NO_IMPROVEMENT"
        assert delta is not None and delta <= Decimal("0")


def test_future_assessment_leakage_prevention(outcome_db):
    """Verify assessments graded after the interaction cutoff are excluded from post-mastery calculation."""
    _, TestSession = outcome_db

    with TestSession() as session:
        t_start = datetime(2026, 10, 30, 12, 15, 0)
        t_graded = datetime(2026, 10, 30, 13, 0, 0)
        att_post = Attempt(
            attempt_id="ATT-CURR-001",
            learner_id="LRN-OUT-001",
            content_id="CNT-OUT-001",
            attempt_number=1,
            started_at=t_start,
            completed_at=t_graded,
            status="COMPLETED",
        )
        res_post = AssessmentResult(
            result_id="RES-CURR-001",
            attempt_id="ATT-CURR-001",
            raw_score=70.0,
            max_score=100.0,
            normalized_score=0.7000,
            is_passed=True,
            graded_at=t_graded,
        )

        # Future assessment at 15:00 (scored 100%)
        t_future = datetime(2026, 10, 30, 15, 0, 0)
        att_future = Attempt(
            attempt_id="ATT-FUTURE-001",
            learner_id="LRN-OUT-001",
            content_id="CNT-OUT-001",
            attempt_number=2,
            started_at=t_future - timedelta(minutes=20),
            completed_at=t_future,
            status="COMPLETED",
        )
        res_future = AssessmentResult(
            result_id="RES-FUTURE-001",
            attempt_id="ATT-FUTURE-001",
            raw_score=100.0,
            max_score=100.0,
            normalized_score=1.0000,
            is_passed=True,
            graded_at=t_future,
        )
        session.add_all([att_post, res_post, att_future, res_future])
        session.commit()

        service = OutcomeTrackingService(session)
        service.record_interaction_start("REC-2026-000001", "ATT-CURR-001")
        outcome, pre_m, post_m, delta = service.evaluate_outcome("REC-2026-000001")
        session.commit()

        # Post-mastery evaluated at 13:00 MUST reflect 0.7000, NOT the future 1.0000 score
        assert post_m == Decimal("0.7000")


def test_rejection_of_invalid_transitions(outcome_db):
    """Verify illegal lifecycle transitions raise InvalidStateTransitionError."""
    _, TestSession = outcome_db

    with TestSession() as session:
        service = OutcomeTrackingService(session)

        # Cannot complete without starting first
        with pytest.raises(InvalidStateTransitionError, match="STARTED"):
            service.record_interaction_completion("REC-2026-000001")

        # Cannot evaluate without starting/completing
        with pytest.raises(InvalidStateTransitionError):
            service.evaluate_outcome("REC-2026-000001")


def test_rejection_of_mismatched_and_inverted_attempts(outcome_db):
    """Verify attempt learner mismatch, content mismatch, and temporal inversion are rejected."""
    _, TestSession = outcome_db

    with TestSession() as session:
        service = OutcomeTrackingService(session)
        t_now = datetime(2026, 10, 30, 12, 30, 0)

        # 1. Learner mismatch
        att_diff_learner = Attempt(
            attempt_id="ATT-DIFF-LRN",
            learner_id="LRN-OUT-002",  # Different learner
            content_id="CNT-OUT-001",
            attempt_number=1,
            started_at=t_now,
            status="IN_PROGRESS",
        )
        # 2. Content mismatch
        att_diff_content = Attempt(
            attempt_id="ATT-DIFF-CNT",
            learner_id="LRN-OUT-001",
            content_id="CNT-OUT-002",  # Different content
            attempt_number=1,
            started_at=t_now,
            status="IN_PROGRESS",
        )
        # 3. Temporal inversion: attempt started BEFORE recommendation was generated (at 10:00 vs rec at 12:00)
        att_inverted = Attempt(
            attempt_id="ATT-INVERTED",
            learner_id="LRN-OUT-001",
            content_id="CNT-OUT-001",
            attempt_number=1,
            started_at=datetime(2026, 10, 30, 10, 0, 0),
            status="IN_PROGRESS",
        )
        session.add_all([att_diff_learner, att_diff_content, att_inverted])
        session.commit()

        # Learner mismatch
        with pytest.raises(InvalidInteractionAttemptError, match="learner"):
            service.record_interaction_start("REC-2026-000001", "ATT-DIFF-LRN")

        # Content mismatch
        with pytest.raises(InvalidInteractionAttemptError, match="content"):
            service.record_interaction_start("REC-2026-000001", "ATT-DIFF-CNT")

        # Temporal inversion
        with pytest.raises(InvalidInteractionAttemptError, match="Temporal inversion"):
            service.record_interaction_start("REC-2026-000001", "ATT-INVERTED")


def test_recommendation_not_found_raises_error(outcome_db):
    """Verify non-existent recommendation ID raises RecommendationNotFoundError."""
    _, TestSession = outcome_db

    with TestSession() as session:
        service = OutcomeTrackingService(session)
        with pytest.raises(RecommendationNotFoundError):
            service.record_interaction_start("REC-NONEXISTENT", "ATT-123")
