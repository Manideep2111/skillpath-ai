"""Unit tests for Stage 2 evaluation collectors (src/services/evaluation/collectors.py)."""

from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.models.entities import (
    AssessmentResult,
    Attempt,
    ContentItem,
    ContentSkill,
    LearningPathItem,
    MasterySnapshot,
    Skill,
    SkillPrerequisite,
)
from src.services.anomaly.sandbox_manager import SandboxManager
from src.services.evaluation.collectors import (
    AnomalyAuditResult,
    CatalogSnapshot,
    EvaluationDataCollector,
    LearnerCohortSnapshot,
    LearnerInteractionSnapshot,
)
from src.services.evaluation.temporal_split import TemporalWindow


@pytest.fixture
def eval_sandbox_session(tmp_path: Path):
    """Provides an isolated clone of the clean baseline database."""
    sandbox_db = tmp_path / "eval_collectors_test.db"
    SandboxManager.clone_baseline(destination_path=sandbox_db)
    engine = create_engine(f"sqlite:///{sandbox_db.as_posix()}")
    with Session(engine) as session:
        yield session


def test_collect_active_catalog(eval_sandbox_session: Session):
    """Verify that catalog collection isolates active items created <= cutoff."""
    collector = EvaluationDataCollector(eval_sandbox_session)
    cutoff = datetime(2026, 8, 1, 0, 0, 0)

    snapshot = collector.collect_active_catalog(cutoff)
    assert isinstance(snapshot, CatalogSnapshot)
    assert snapshot.total_active_items > 0
    assert len(snapshot.active_content_ids) == snapshot.total_active_items

    # Verify no item created after cutoff is present
    for cid in snapshot.active_content_ids:
        item = eval_sandbox_session.get(ContentItem, cid)
        assert item is not None
        assert item.created_at <= cutoff
        assert item.is_active is True


def test_collect_learner_cohorts(eval_sandbox_session: Session):
    """Verify cohort stratification: cold-start, sparse, active, and activity strata."""
    collector = EvaluationDataCollector(eval_sandbox_session)
    cutoff = datetime(2026, 8, 1, 0, 0, 0)

    cohort = collector.collect_learner_cohorts(cutoff)
    assert isinstance(cohort, LearnerCohortSnapshot)
    assert cohort.total_learners == 100
    assert len(cohort.all_learner_ids) == 100

    # Cold start learners must have 0 prior attempts
    assert len(cohort.cold_start_learner_ids) >= 10
    for lid in cohort.cold_start_learner_ids:
        assert cohort.learner_attempt_counts[lid] == 0

    # Sparse learners: 1 <= count < 5
    for lid in cohort.sparse_learner_ids:
        assert 1 <= cohort.learner_attempt_counts[lid] < 5

    # Active learners: count >= 5
    for lid in cohort.active_learner_ids:
        assert cohort.learner_attempt_counts[lid] >= 5

    # Activity strata: "low", "med", "high"
    assert "low" in cohort.activity_strata
    assert "med" in cohort.activity_strata
    assert "high" in cohort.activity_strata
    total_in_strata = (
        len(cohort.activity_strata["low"])
        + len(cohort.activity_strata["med"])
        + len(cohort.activity_strata["high"])
    )
    assert total_in_strata == 100


def test_collect_learner_interactions_and_earliest_assessment(eval_sandbox_session: Session):
    """Verify ground truth collection, subset invariants, and earliest post-cutoff assessment."""
    collector = EvaluationDataCollector(eval_sandbox_session)
    cutoff = datetime(2026, 8, 1, 0, 0, 0)
    window = TemporalWindow.create(
        cutoff=cutoff,
        window_days=30,
        dataset_max_timestamp=datetime(2026, 10, 30, 19, 20, 44),
    )

    # Pick an active learner
    lid = "LRN-000003"
    snapshot: LearnerInteractionSnapshot = collector.collect_learner_interactions(lid, window)

    assert isinstance(snapshot, LearnerInteractionSnapshot)
    assert snapshot.learner_id == lid
    assert snapshot.cutoff == cutoff
    assert snapshot.actual_horizon == window.actual_horizon

    # Invariant: relevant_items must be a subset of observed_items
    assert snapshot.relevant_items.issubset(snapshot.observed_items)

    # Ideal pool contains ground-truth relevance grades
    assert isinstance(snapshot.ideal_pool, dict)
    for cid, grade in snapshot.ideal_pool.items():
        assert grade in (0, 1, 2, 3)

    # Earliest assessment check
    if snapshot.earliest_post_cutoff_assessment:
        skill_id, graded_at, score = snapshot.earliest_post_cutoff_assessment
        assert cutoff < graded_at <= window.actual_horizon
        assert isinstance(score, Decimal)


def test_five_anomaly_audits_clean_baseline(eval_sandbox_session: Session):
    """Verify all five anomaly audits pass on clean baseline database with zero violations."""
    collector = EvaluationDataCollector(eval_sandbox_session)
    cutoff = datetime(2026, 8, 1, 0, 0, 0)

    audits = collector.run_five_anomaly_audits(cutoff=cutoff)
    assert len(audits) == 5

    for name, audit in audits.items():
        assert isinstance(audit, AnomalyAuditResult)
        assert audit.passed is True
        assert audit.violations_count == 0
        assert len(audit.details) == 0


def test_anomaly_audits_detected_violations(eval_sandbox_session: Session):
    """Verify that injected anomalies are detected by read-only audits."""
    collector = EvaluationDataCollector(eval_sandbox_session)
    cutoff = datetime(2026, 8, 1, 0, 0, 0)

    # 1. Inject an inverted attempt (completed_at < started_at)
    bad_attempt = Attempt(
        attempt_id="ATT-ANOM-TEST-INV",
        learner_id="LRN-000001",
        content_id="CNT-000001",
        attempt_number=99,
        started_at=datetime(2026, 8, 10, 12, 0, 0),
        completed_at=datetime(2026, 8, 10, 11, 0, 0),  # Inverted!
        time_spent_seconds=3600,
        status="COMPLETED",
    )
    eval_sandbox_session.add(bad_attempt)

    # 2. Inject an orphaned content skill
    bad_content_skill = ContentSkill(
        content_id="CNT-000001",
        skill_id="SKL-NONEXISTENT-9999",  # Non-existent skill!
        relevance_weight=Decimal("1.0"),
    )
    eval_sandbox_session.add(bad_content_skill)

    # 3. Inject a leaking mastery snapshot
    bad_snapshot = MasterySnapshot(
        snapshot_id="SNP-LEAK-TEST-001",
        learner_id="LRN-000001",
        skill_id="SKL-000001",
        calculated_at=datetime(2026, 8, 1, 0, 0, 0),
        cutoff_timestamp=datetime(2026, 8, 1, 0, 0, 0),
        mastery_level=Decimal("0.8500"),
        confidence_score=Decimal("0.9000"),
        evidence_count=1,
        max_evidence_graded_at=datetime(2026, 8, 5, 0, 0, 0),  # Future graded!
        evidence_result_ids_json="[]",
        algorithm_version="v1.1.0",
    )
    eval_sandbox_session.add(bad_snapshot)

    # 4. Inject a learning path loop (same content reassigned incomplete)
    item1 = LearningPathItem(
        path_item_id="LPI-LOOP-TEST-1",
        path_id="PTH-LOOP-TEST",
        content_id="CNT-000001",
        sequence_order=1,
        status="IN_PROGRESS",  # Incomplete!
    )
    item2 = LearningPathItem(
        path_item_id="LPI-LOOP-TEST-2",
        path_id="PTH-LOOP-TEST",
        content_id="CNT-000001",
        sequence_order=2,  # Reassigned!
        status="PENDING",
    )
    eval_sandbox_session.add_all([item1, item2])
    eval_sandbox_session.commit()

    # Run the audits
    audits = collector.run_five_anomaly_audits(cutoff=cutoff)

    # A2: Timestamp ordering failed
    assert audits["timestamp_ordering"].passed is False
    assert audits["timestamp_ordering"].violations_count >= 1

    # A3: Orphaned content skills failed
    assert audits["orphaned_content_skills"].passed is False
    assert audits["orphaned_content_skills"].violations_count >= 1

    # A4: Future mastery leakage failed
    assert audits["future_mastery_leakage"].passed is False
    assert audits["future_mastery_leakage"].violations_count >= 1

    # A5: Learning path loops failed
    assert audits["learning_path_loops"].passed is False
    assert audits["learning_path_loops"].violations_count >= 1
