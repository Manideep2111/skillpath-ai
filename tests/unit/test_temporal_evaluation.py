"""Unit tests for temporal evaluation boundaries, leakage auditing, and relevance grading."""

from datetime import datetime
from decimal import Decimal
from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.models.entities import AssessmentResult, Attempt
from src.services.anomaly.sandbox_manager import SandboxManager
from src.services.evaluation.business_rules import BusinessRuleAuditor
from src.services.evaluation.ground_truth import GroundTruthExtractor
from src.services.evaluation.temporal_split import (
    TemporalWindow,
    get_dataset_temporal_bounds,
    get_standard_evaluation_windows,
)
from src.services.mastery_service import MasteryService


@pytest.fixture
def test_db_session(tmp_path: Path):
    """Provides an isolated clone of the clean baseline database for testing."""
    target_db = tmp_path / "eval_test_sandbox.db"
    SandboxManager.clone_baseline(destination_path=target_db)
    engine = create_engine(f"sqlite:///{target_db.as_posix()}")
    with Session(engine) as session:
        yield session


def test_temporal_window_partial_observation_detection():
    """Verify that a window extending past the dataset max timestamp is flagged as partially observed."""
    dataset_max = datetime(2026, 10, 30, 19, 20, 44)
    # Window for October 1 extends 30 days to October 31
    cutoff_oct = datetime(2026, 10, 1, 0, 0, 0)
    window = TemporalWindow.create(
        cutoff=cutoff_oct,
        window_days=30,
        dataset_max_timestamp=dataset_max,
    )

    assert window.is_partially_observed is True
    assert window.actual_horizon == dataset_max
    assert window.planned_end == datetime(2026, 10, 31, 0, 0, 0)

    # Window for August 1 is fully observed
    cutoff_aug = datetime(2026, 8, 1, 0, 0, 0)
    window_aug = TemporalWindow.create(
        cutoff=cutoff_aug,
        window_days=30,
        dataset_max_timestamp=dataset_max,
    )
    assert window_aug.is_partially_observed is False
    assert window_aug.actual_horizon == datetime(2026, 8, 31, 0, 0, 0)


def test_pre_cutoff_attempt_with_post_cutoff_grading(test_db_session: Session):
    """Verify that an attempt started before T but graded after T does NOT influence mastery at T."""
    cutoff = datetime(2026, 5, 1, 0, 0, 0)
    learner_id = "LRN-000091"  # Cold start learner with 0 initial attempts
    skill_id = "SKL-000001"

    # Mastery at cutoff T must be unknown (None)
    mastery_service = MasteryService(test_db_session)
    pre_m, count, _, _, _ = mastery_service.compute_mastery(learner_id, skill_id, cutoff)
    assert pre_m is None
    assert count == 0

    # Insert attempt started before T (April 30 23:00) but completed and graded after T (May 1 01:00)
    attempt = Attempt(
        attempt_id="ATT-LEAK-TEST-001",
        learner_id=learner_id,
        content_id="CNT-000001",
        attempt_number=1,
        started_at=datetime(2026, 4, 30, 23, 0, 0),    # Before T
        completed_at=datetime(2026, 5, 1, 1, 0, 0),    # After T
        time_spent_seconds=7200,
        status="COMPLETED",
    )
    result = AssessmentResult(
        result_id="RES-LEAK-TEST-001",
        attempt_id="ATT-LEAK-TEST-001",
        raw_score=Decimal("100.0"),
        max_score=Decimal("100.0"),
        normalized_score=Decimal("1.0000"),
        is_passed=True,
        graded_at=datetime(2026, 5, 1, 1, 5, 0),        # After T
    )
    test_db_session.add_all([attempt, result])
    test_db_session.commit()

    # Re-compute mastery at cutoff T: MUST STILL BE NONE!
    post_check_m, post_count, _, _, _ = mastery_service.compute_mastery(learner_id, skill_id, cutoff)
    assert post_check_m is None
    assert post_count == 0


def test_clean_temporal_leakage_audit(test_db_session: Session):
    """Verify clean temporal leakage audit: future records exist in DB but are not in used evidence."""
    auditor = BusinessRuleAuditor(test_db_session)
    cutoff = datetime(2026, 6, 1, 0, 0, 0)

    # In clean DB, attempts and assessments exist after June 1.
    # We query historical evidence used up to June 1.
    mastery_service = MasteryService(test_db_session)
    _, _, _, _, evidence_ids = mastery_service.compute_mastery("LRN-000001", "SKL-000001", cutoff)

    # Audit this calculation: should report 0% leakage
    audit_res = auditor.audit_temporal_leakage([("LRN-000001", "SKL-000001", cutoff, evidence_ids)])
    assert audit_res.has_zero_leakage is True
    assert audit_res.leakage_rate == 0.0
    assert audit_res.leaking_evaluations == 0


def test_injected_temporal_leakage_audit(test_db_session: Session):
    """Verify that if prohibited future evidence is included in used evidence IDs, leakage is detected."""
    auditor = BusinessRuleAuditor(test_db_session)
    cutoff = datetime(2026, 6, 1, 0, 0, 0)

    # Insert a future assessment graded on June 15
    attempt = Attempt(
        attempt_id="ATT-FUTURE-001",
        learner_id="LRN-000001",
        content_id="CNT-000001",
        attempt_number=99,
        started_at=datetime(2026, 6, 15, 10, 0, 0),
        completed_at=datetime(2026, 6, 15, 11, 0, 0),
        time_spent_seconds=3600,
        status="COMPLETED",
    )
    result = AssessmentResult(
        result_id="RES-FUTURE-001",
        attempt_id="ATT-FUTURE-001",
        raw_score=Decimal("90.0"),
        max_score=Decimal("100.0"),
        normalized_score=Decimal("0.9000"),
        is_passed=True,
        graded_at=datetime(2026, 6, 15, 11, 2, 0),
    )
    test_db_session.add_all([attempt, result])
    test_db_session.commit()

    # Pass the future result ID as allegedly used evidence at cutoff June 1
    corrupted_calc = [("LRN-000001", "SKL-000001", cutoff, ["RES-FUTURE-001"])]
    audit_res = auditor.audit_temporal_leakage(corrupted_calc)

    assert audit_res.has_zero_leakage is False
    assert audit_res.leakage_rate == 1.0
    assert audit_res.leaking_evaluations == 1
    assert audit_res.leakage_details[0]["leaking_result_id"] == "RES-FUTURE-001"


def test_four_tier_relevance_grading(test_db_session: Session):
    """Verify four-tier relevance grading (0: unobserved, 1: engaged, 2: proficient, 3: gap closed)."""
    cutoff = datetime(2026, 6, 1, 0, 0, 0)
    horizon = datetime(2026, 6, 30, 23, 59, 59)
    window = TemporalWindow.create(cutoff=cutoff, window_days=30, dataset_max_timestamp=horizon)

    learner_id = "LRN-000092"  # Cold-start learner
    gt_extractor = GroundTruthExtractor(test_db_session)

    # Grade 0: initially no activity
    gt_initial = gt_extractor.extract_for_learner(learner_id, window)
    assert gt_initial.relevance_grades == {}
    assert gt_initial.has_relevant_outcomes is False

    # Grade 1 (Engaged): reading completed (no assessment)
    att1 = Attempt(
        attempt_id="ATT-GRADE-001",
        learner_id=learner_id,
        content_id="CNT-000002",  # Reading Unit
        attempt_number=1,
        started_at=datetime(2026, 6, 5, 10, 0, 0),
        completed_at=datetime(2026, 6, 5, 10, 30, 0),
        time_spent_seconds=1800,
        status="COMPLETED",
    )
    test_db_session.add(att1)
    test_db_session.commit()

    gt_1 = gt_extractor.extract_for_learner(learner_id, window)
    assert gt_1.relevance_grades.get("CNT-000002") == 1

    # Grade 3 (Target Gap Closed): quiz completed, assessment passed, prior gap (< 0.70) closed
    att2 = Attempt(
        attempt_id="ATT-GRADE-002",
        learner_id=learner_id,
        content_id="CNT-000004",  # Quiz Unit (maps to SKL-000001)
        attempt_number=1,
        started_at=datetime(2026, 6, 10, 10, 0, 0),
        completed_at=datetime(2026, 6, 10, 11, 0, 0),
        time_spent_seconds=3600,
        status="COMPLETED",
    )
    res2 = AssessmentResult(
        result_id="RES-GRADE-002",
        attempt_id="ATT-GRADE-002",
        raw_score=Decimal("85.0"),
        max_score=Decimal("100.0"),
        normalized_score=Decimal("0.8500"),
        is_passed=True,
        graded_at=datetime(2026, 6, 10, 11, 2, 0),
    )
    test_db_session.add_all([att2, res2])
    test_db_session.commit()

    gt_3 = gt_extractor.extract_for_learner(learner_id, window)
    # CNT-000004 qualifies for Grade 3 because prior mastery was unknown/gap and now improved!
    assert gt_3.relevance_grades.get("CNT-000004") == 3
