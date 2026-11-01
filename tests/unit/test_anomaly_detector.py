"""Unit tests for the anomaly detection service."""

from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.models.entities import (
    AssessmentResult,
    Attempt,
    DataIssue,
    LearningPathItem,
    MasterySnapshot,
    Recommendation,
)
from src.services.anomaly.detector import (
    AnomalyDetectionService,
    generate_issue_id,
)
from src.services.anomaly.fixture_generator import (
    ANOMALY_TYPE_A1,
    ANOMALY_TYPE_A2,
    ANOMALY_TYPE_A3,
    ANOMALY_TYPE_A4,
    ANOMALY_TYPE_A5,
)
from src.services.anomaly.sandbox_manager import (
    BASELINE_DB_PATH,
    SandboxManager,
    SandboxPathSecurityError,
)


@pytest.fixture
def cloned_test_db(tmp_path: Path) -> Path:
    """Provides a temporary clone of the clean baseline database."""
    target = tmp_path / "test_sandbox.db"
    SandboxManager.clone_baseline(destination_path=target)
    return target


def test_clean_baseline_has_zero_anomalies(cloned_test_db: Path):
    """Verify that scanning a clean baseline database produces exactly 0 false positives."""
    engine = create_engine(f"sqlite:///{cloned_test_db.as_posix()}")
    with Session(engine) as session:
        detector = AnomalyDetectionService(session)
        issues = detector.detect_all()
        assert len(issues) == 0


def test_record_issues_rejects_baseline_db():
    """Verify that record_issues refuses to mutate the clean baseline database."""
    engine = create_engine(f"sqlite:///{BASELINE_DB_PATH.as_posix()}")
    with Session(engine) as session:
        detector = AnomalyDetectionService(session)
        dummy_issue = DataIssue(
            issue_id="ISS-TEST-0001",
            anomaly_type="TEST",
            severity="LOW",
            entity_type="Test",
            entity_id="TEST-01",
            description="Test issue",
            detected_at=datetime.now(timezone.utc),
            quarantine_status="FLAGGED",
        )
        with pytest.raises(SandboxPathSecurityError, match="CRITICAL SAFETY VIOLATION"):
            detector.record_issues([dummy_issue])


def test_detect_a1_prerequisite_violation(cloned_test_db: Path):
    """Verify A1 detector flags recommendation violating prerequisite."""
    engine = create_engine(f"sqlite:///{cloned_test_db.as_posix()}")
    with Session(engine) as session:
        # LRN-000091 is cold start (mastery unknown / 0.00 for SKL-000003)
        # CNT-000022 teaches SKL-000004, which requires SKL-000003 at 0.70
        rec = Recommendation(
            recommendation_id="REC-TEST-0001",
            learner_id="LRN-000091",
            content_id="CNT-000022",
            target_skill_id="SKL-000004",
            decision_timestamp=datetime(2026, 1, 15, 10, 0, 0),
            rank_position=1,
            recommendation_score=Decimal("0.9000"),
            primary_reason_code="TEST",
            score_components_json="{}",
            rejection_audit_json="{}",
            algorithm_version="v1.2.0-test",
        )
        session.add(rec)
        session.commit()

        detector = AnomalyDetectionService(session)
        issues = detector.detect_a1_prerequisite_violations()
        assert len(issues) == 1
        assert issues[0].anomaly_type == ANOMALY_TYPE_A1
        assert issues[0].entity_id == "REC-TEST-0001"
        assert issues[0].severity == "HIGH"


def test_detect_a2_timestamp_order_inversion(cloned_test_db: Path):
    """Verify A2 detector flags attempts with completed_at < started_at and premature assessments."""
    engine = create_engine(f"sqlite:///{cloned_test_db.as_posix()}")
    with Session(engine) as session:
        # 1. Inverted attempt
        att = Attempt(
            attempt_id="ATT-TEST-0001",
            learner_id="LRN-000001",
            content_id="CNT-000001",
            attempt_number=99,
            started_at=datetime(2026, 2, 1, 15, 0, 0),
            completed_at=datetime(2026, 2, 1, 14, 0, 0),  # Inverted
            time_spent_seconds=600,
            status="COMPLETED",
        )
        # 2. Premature assessment
        att2 = Attempt(
            attempt_id="ATT-TEST-0002",
            learner_id="LRN-000001",
            content_id="CNT-000004",  # Quiz
            attempt_number=99,
            started_at=datetime(2026, 2, 2, 10, 0, 0),
            completed_at=datetime(2026, 2, 2, 11, 0, 0),
            time_spent_seconds=3600,
            status="COMPLETED",
        )
        res2 = AssessmentResult(
            result_id="RES-TEST-0002",
            attempt_id="ATT-TEST-0002",
            raw_score=Decimal("80.0"),
            max_score=Decimal("100.0"),
            normalized_score=Decimal("0.8000"),
            is_passed=True,
            graded_at=datetime(2026, 2, 2, 10, 30, 0),  # Before completion!
        )
        session.add_all([att, att2, res2])
        session.commit()

        detector = AnomalyDetectionService(session)
        issues = detector.detect_a2_timestamp_order_inversions()
        assert len(issues) == 2
        entities = {i.entity_id for i in issues}
        assert "ATT-TEST-0001" in entities
        assert "RES-TEST-0002" in entities


def test_detect_a3_nonexistent_skill_reference(cloned_test_db: Path):
    """Verify A3 detector flags content_skills referencing nonexistent skills."""
    conn = sqlite3.connect(cloned_test_db.as_posix())
    try:
        conn.execute("PRAGMA foreign_keys = OFF;")
        conn.execute(
            "INSERT INTO content_skills (content_id, skill_id, relevance_weight) VALUES ('CNT-000001', 'SKL-999999', 1.0);"
        )
        conn.commit()
        conn.execute("PRAGMA foreign_keys = ON;")
    finally:
        conn.close()

    engine = create_engine(f"sqlite:///{cloned_test_db.as_posix()}")
    with Session(engine) as session:
        detector = AnomalyDetectionService(session)
        issues = detector.detect_a3_nonexistent_skill_references()
        assert len(issues) == 1
        assert issues[0].anomaly_type == ANOMALY_TYPE_A3
        assert issues[0].entity_id == "CNT-000001:SKL-999999"
        assert issues[0].severity == "CRITICAL"


def test_detect_a4_future_attempt_leakage(cloned_test_db: Path):
    """Verify A4 detector flags future evidence timestamps and handles malformed JSON."""
    engine = create_engine(f"sqlite:///{cloned_test_db.as_posix()}")
    with Session(engine) as session:
        # Snapshot with max_evidence_graded_at > cutoff
        s1 = MasterySnapshot(
            snapshot_id="SNP-TEST-0001",
            learner_id="LRN-000001",
            skill_id="SKL-000001",
            mastery_level=Decimal("0.7500"),
            evidence_count=1,
            confidence_score=Decimal("0.8500"),
            cutoff_timestamp=datetime(2026, 1, 1, 0, 0, 0),
            max_evidence_graded_at=datetime(2026, 1, 10, 0, 0, 0),  # Leakage!
            evidence_result_ids_json="malformed-not-a-json",  # Resilient to malformed json
            algorithm_version="v1.2.0-test",
            calculated_at=datetime(2026, 1, 10, 1, 0, 0),
        )
        session.add(s1)
        session.commit()

        detector = AnomalyDetectionService(session)
        issues = detector.detect_a4_future_attempt_leakage()
        assert len(issues) == 1
        assert issues[0].anomaly_type == ANOMALY_TYPE_A4
        assert issues[0].entity_id == "SNP-TEST-0001"
        assert issues[0].severity == "CRITICAL"


def test_detect_a5_learning_path_loop(cloned_test_db: Path):
    """Verify A5 detector flags learning path looping without progress."""
    engine = create_engine(f"sqlite:///{cloned_test_db.as_posix()}")
    with Session(engine) as session:
        # PATH-2026-000001 already has CNT-000030 at seq 1 with status IN_PROGRESS.
        # Add duplicate at sequence 99.
        item = LearningPathItem(
            path_item_id="LPI-LOOP-0001",
            path_id="PATH-2026-000001",
            content_id="CNT-000030",
            sequence_order=99,
            is_mandatory=True,
            status="PENDING",
            completed_at=None,
        )
        session.add(item)
        session.commit()

        detector = AnomalyDetectionService(session)
        issues = detector.detect_a5_learning_path_loops()
        assert len(issues) == 1
        assert issues[0].anomaly_type == ANOMALY_TYPE_A5
        assert issues[0].entity_id == "LPI-LOOP-0001"
        assert issues[0].severity == "MEDIUM"


def test_record_issues_idempotency(cloned_test_db: Path):
    """Verify record_issues does not insert duplicates when called multiple times."""
    engine = create_engine(f"sqlite:///{cloned_test_db.as_posix()}")
    with Session(engine) as session:
        detector = AnomalyDetectionService(session)

        test_issues = [
            DataIssue(
                issue_id=generate_issue_id(ANOMALY_TYPE_A2, "Attempt", "ATT-TEST-001"),
                anomaly_type=ANOMALY_TYPE_A2,
                severity="HIGH",
                entity_type="Attempt",
                entity_id="ATT-TEST-001",
                description="Test description",
                detected_at=datetime.now(timezone.utc),
                quarantine_status="FLAGGED",
            ),
            DataIssue(
                issue_id=generate_issue_id(ANOMALY_TYPE_A3, "ContentSkill", "CNT-01:SKL-99"),
                anomaly_type=ANOMALY_TYPE_A3,
                severity="CRITICAL",
                entity_type="ContentSkill",
                entity_id="CNT-01:SKL-99",
                description="Test description 2",
                detected_at=datetime.now(timezone.utc),
                quarantine_status="FLAGGED",
            ),
        ]

        # First run: should insert 2
        count_first = detector.record_issues(test_issues)
        assert count_first == 2

        # Second run: should insert 0 (idempotent)
        count_second = detector.record_issues(test_issues)
        assert count_second == 0

        # Verify total rows in data_issues table
        total_rows = session.scalars(select(DataIssue)).all()
        assert len(total_rows) == 2
