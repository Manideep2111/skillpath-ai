"""Unit tests for the anomaly sandbox manager."""

from pathlib import Path
import sqlite3
import pytest

from src.services.anomaly.sandbox_manager import (
    BASELINE_DB_PATH,
    SandboxManager,
    SandboxOverwriteError,
    SandboxPathSecurityError,
)


def test_assert_safe_destination_rejects_baseline():
    """Verify that targeting baseline database raises SandboxPathSecurityError."""
    with pytest.raises(SandboxPathSecurityError, match="CRITICAL SAFETY VIOLATION"):
        SandboxManager.assert_safe_destination(BASELINE_DB_PATH)

    # Also test relative/case-insensitive path strings
    with pytest.raises(SandboxPathSecurityError):
        SandboxManager.assert_safe_destination("skillpath.db")

    with pytest.raises(SandboxPathSecurityError):
        SandboxManager.assert_safe_destination("D:/SkillPathAI/skillpath.db")


def test_assert_safe_destination_accepts_valid_path(tmp_path: Path):
    """Verify that safe non-baseline path is accepted and resolved."""
    dest = tmp_path / "sandbox.db"
    resolved = SandboxManager.assert_safe_destination(dest)
    assert resolved == dest.resolve()


def test_clone_baseline_creates_valid_clone(tmp_path: Path):
    """Verify clone_baseline creates a complete clone with all 15 tables."""
    dest = tmp_path / "cloned_sandbox.db"
    assert not dest.exists()

    cloned_path = SandboxManager.clone_baseline(destination_path=dest)
    assert cloned_path == dest.resolve()
    assert dest.exists()

    # Verify table count in cloned database
    conn = sqlite3.connect(dest.as_posix())
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) FROM sqlite_master WHERE type='table';")
        count = cursor.fetchone()[0]
        assert count >= 15
    finally:
        conn.close()


def test_clone_baseline_refuses_overwrite_without_force(tmp_path: Path):
    """Verify clone_baseline raises SandboxOverwriteError if destination exists and force_recreate is False."""
    dest = tmp_path / "existing_sandbox.db"
    dest.write_text("existing dummy content")

    with pytest.raises(SandboxOverwriteError, match="already exists"):
        SandboxManager.clone_baseline(destination_path=dest, force_recreate=False)


def test_clone_baseline_allows_overwrite_with_force(tmp_path: Path):
    """Verify clone_baseline replaces existing file when force_recreate is True."""
    dest = tmp_path / "existing_sandbox.db"
    dest.write_text("existing dummy content")

    cloned_path = SandboxManager.clone_baseline(destination_path=dest, force_recreate=True)
    assert cloned_path.exists()

    # Should now be a valid sqlite database
    conn = sqlite3.connect(dest.as_posix())
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) FROM learners;")
        count = cursor.fetchone()[0]
        assert count == 100
    finally:
        conn.close()


def test_clone_baseline_rejects_baseline_as_target():
    """Verify clone_baseline refuses to clone onto baseline database."""
    with pytest.raises(SandboxPathSecurityError):
        SandboxManager.clone_baseline(destination_path=BASELINE_DB_PATH)


def test_compute_metrics_seven_required_scenarios():
    """Verify compute_metrics on the 7 required benchmark scenarios."""
    from src.services.anomaly.evaluation import compute_metrics, AnomalyEvaluator
    from src.models.entities import DataIssue

    # Scenario 1: TP=1, FP=0, FN=0
    p1, r1, f1_1 = compute_metrics(tp=1, fp=0, fn=0)
    assert p1 == 1.0
    assert r1 == 1.0
    assert f1_1 == 1.0

    # Scenario 2: TP=1, FP=1, FN=0 (Precision = 50%, Recall = 100%, F1 ~ 66.67%)
    p2, r2, f1_2 = compute_metrics(tp=1, fp=1, fn=0)
    assert p2 == 0.5
    assert r2 == 1.0
    assert pytest.approx(f1_2, 1e-4) == 2.0 * (0.5 * 1.0) / (0.5 + 1.0)
    assert round(f1_2, 4) == 0.6667

    # Scenario 3: TP=0, FP=0, FN=1 (Complete miss)
    p3, r3, f1_3 = compute_metrics(tp=0, fp=0, fn=1)
    assert p3 == 0.0
    assert r3 == 0.0
    assert f1_3 == 0.0

    # Scenario 4: No detections and no ground-truth anomalies (TP=0, FP=0, FN=0)
    p4, r4, f1_4 = compute_metrics(tp=0, fp=0, fn=0)
    assert p4 == 1.0
    assert r4 == 1.0
    assert f1_4 == 1.0

    # Scenario 5: No predicted positives when ground-truth anomalies exist (TP=0, FP=0, FN=3)
    p5, r5, f1_5 = compute_metrics(tp=0, fp=0, fn=3)
    assert p5 == 0.0
    assert r5 == 0.0
    assert f1_5 == 0.0

    # Scenario 6: Mixed results containing true positives, false positives, and false negatives (TP=4, FP=2, FN=1)
    p6, r6, f1_6 = compute_metrics(tp=4, fp=2, fn=1)
    assert p6 == 4 / 6  # ~0.6667
    assert r6 == 4 / 5  # 0.8000
    expected_f1_6 = 2.0 * ((4 / 6) * 0.8) / ((4 / 6) + 0.8)
    assert pytest.approx(f1_6, 1e-4) == expected_f1_6

    # Scenario 7: Aggregated metrics across the five anomaly categories (Micro-averaging verification)
    ground_truth = [
        {"anomaly_type": "PREREQUISITE_VIOLATION", "entity_id": "REC-001"},
        {"anomaly_type": "TIMESTAMP_ORDER_INVERSION", "entity_id": "ATT-001"},
        {"anomaly_type": "NONEXISTENT_SKILL_REFERENCE", "entity_id": "CNT-001:SKL-999"},
        {"anomaly_type": "FUTURE_ATTEMPT_LEAKAGE", "entity_id": "SNP-001"},
        {"anomaly_type": "LEARNING_PATH_LOOP", "entity_id": "LPI-001"},
    ]
    # Simulate: 4 true positives, 1 false positive, 1 false negative
    detected_issues = [
        DataIssue(anomaly_type="PREREQUISITE_VIOLATION", entity_id="REC-001"),       # TP
        DataIssue(anomaly_type="TIMESTAMP_ORDER_INVERSION", entity_id="ATT-001"),    # TP
        DataIssue(anomaly_type="NONEXISTENT_SKILL_REFERENCE", entity_id="CNT-001:SKL-999"),  # TP
        DataIssue(anomaly_type="FUTURE_ATTEMPT_LEAKAGE", entity_id="SNP-001"),       # TP
        # LEARNING_PATH_LOOP: missed (FN=1)
        DataIssue(anomaly_type="LEARNING_PATH_LOOP", entity_id="LPI-DUMMY-FP"),      # FP=1
    ]

    report = AnomalyEvaluator.evaluate(ground_truth, detected_issues)
    assert report.total_ground_truth == 5
    assert report.total_detected == 5
    assert report.true_positives == 4
    assert report.false_positives == 1
    assert report.false_negatives == 1
    # Micro-average precision: 4 / (4 + 1) = 0.8
    assert report.precision == 0.8
    # Micro-average recall: 4 / (4 + 1) = 0.8
    assert report.recall == 0.8
    # Micro-average F1: 0.8
    assert pytest.approx(report.f1_score, 1e-4) == 0.8

    # Category-level breakdown verification
    assert report.by_type["PREREQUISITE_VIOLATION"].true_positives == 1
    assert report.by_type["PREREQUISITE_VIOLATION"].precision == 1.0
    assert report.by_type["LEARNING_PATH_LOOP"].true_positives == 0
    assert report.by_type["LEARNING_PATH_LOOP"].false_positives == 1
    assert report.by_type["LEARNING_PATH_LOOP"].false_negatives == 1
    assert report.by_type["LEARNING_PATH_LOOP"].precision == 0.0
    assert report.by_type["LEARNING_PATH_LOOP"].recall == 0.0


