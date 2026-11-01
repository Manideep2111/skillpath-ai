"""Tests for Evaluation and Anomaly Detection API endpoints.

Verifies GET /api/v1/evaluation/latest and GET /api/v1/anomalies/status contracts.
"""

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.api.v1.evaluation import get_latest_evaluation_report_path
from src.schemas.evaluation import ComprehensiveEvaluationReportSchema, AnomalyStatusResponse


@pytest.fixture
def client():
    """FastAPI TestClient fixture."""
    return TestClient(app)


def test_get_latest_evaluation_report_endpoint(client: TestClient):
    """Verify GET /api/v1/evaluation/latest returns valid evaluation schema with windows."""
    response = client.get("/api/v1/evaluation/latest")
    assert response.status_code == 200, f"Unexpected error: {response.text}"

    data = response.json()
    validated = ComprehensiveEvaluationReportSchema.model_validate(data)
    assert validated.evaluation_id.startswith("EVAL-")
    assert len(validated.windows_evaluated) >= 1
    assert validated.k_values == [1, 3, 5, 10]

    # Verify October window is marked partially observed
    oct_window = next((w for w in validated.windows_evaluated if "2026-10" in w.cutoff), None)
    if oct_window:
        assert oct_window.is_partially_observed is True

    # Verify August window is not partially observed
    aug_window = next((w for w in validated.windows_evaluated if "2026-08" in w.cutoff), None)
    if aug_window:
        assert aug_window.is_partially_observed is False

    # Check that rank-K metrics exist for 1, 3, 5, 10
    first_window = validated.windows_evaluated[0]
    assert 5 in first_window.metrics_by_k
    k5_summary = first_window.metrics_by_k[5]
    assert 0.0 <= k5_summary.mean_precision <= 1.0
    assert 0.0 <= k5_summary.catalog_coverage <= 1.0
    assert 0.0 <= k5_summary.gini_coefficient <= 1.0


def test_get_latest_evaluation_report_not_found(client: TestClient, monkeypatch, tmp_path: Path):
    """Verify 404 response when reports directory contains no evaluation JSON files."""
    empty_reports = tmp_path / "empty_reports"
    empty_reports.mkdir()

    import src.api.v1.evaluation as eval_module
    monkeypatch.setattr(eval_module, "DEFAULT_REPORTS_DIR", empty_reports)

    response = client.get("/api/v1/evaluation/latest")
    assert response.status_code == 404
    assert "No recommendation evaluation JSON reports found" in response.json()["detail"]


def test_get_anomaly_status_endpoint(client: TestClient):
    """Verify GET /api/v1/anomalies/status returns baseline audits and sandbox metrics."""
    response = client.get("/api/v1/anomalies/status")
    assert response.status_code == 200, f"Unexpected error: {response.text}"

    data = response.json()
    validated = AnomalyStatusResponse.model_validate(data)

    # 1. Baseline status assertions
    assert validated.baseline_status == "CLEAN"
    assert validated.total_baseline_violations == 0
    assert "prerequisite_compliance" in validated.baseline_audits
    assert "timestamp_ordering" in validated.baseline_audits
    assert "orphaned_content_skills" in validated.baseline_audits
    assert "future_mastery_leakage" in validated.baseline_audits
    assert "learning_path_loops" in validated.baseline_audits

    for audit_key, audit in validated.baseline_audits.items():
        assert audit.passed is True
        assert audit.violations_count == 0
        assert audit.total_checked >= 0

    # 2. Sandbox benchmark evaluation assertions
    assert validated.sandbox_evaluation is not None
    sandbox = validated.sandbox_evaluation
    assert sandbox.total_ground_truth == 5
    assert sandbox.total_detected == 5
    assert sandbox.true_positives == 5
    assert sandbox.false_positives == 0
    assert sandbox.false_negatives == 0
    assert sandbox.precision == 1.0
    assert sandbox.recall == 1.0
    assert sandbox.f1_score == 1.0

    # Check by_type contains all 5 canonical SRS types
    expected_types = {
        "PREREQUISITE_VIOLATION",
        "TIMESTAMP_ORDER_INVERSION",
        "NONEXISTENT_SKILL_REFERENCE",
        "FUTURE_ATTEMPT_LEAKAGE",
        "LEARNING_PATH_LOOP",
    }
    assert expected_types.issubset(set(sandbox.by_type.keys()))
    for t in expected_types:
        metrics = sandbox.by_type[t]
        assert metrics.ground_truth_count == 1
        assert metrics.detected_count == 1
        assert metrics.true_positives == 1
        assert metrics.precision == 1.0
        assert metrics.recall == 1.0
        assert metrics.f1_score == 1.0


def test_anomaly_benchmark_mathematical_invariants(client: TestClient):
    """Verify mathematical consistency of Precision, Recall, and F1 calculations.

    Invariants:
    1. Ground Truth = TP + FN
    2. Detected = TP + FP
    3. Precision = TP / (TP + FP)
    4. Recall = TP / (TP + FN)
    5. F1 = 2 * (P * R) / (P + R)
    """
    response = client.get("/api/v1/anomalies/status")
    assert response.status_code == 200
    data = response.json()
    validated = AnomalyStatusResponse.model_validate(data)
    sandbox = validated.sandbox_evaluation
    assert sandbox is not None

    # Overall invariants
    assert sandbox.total_ground_truth == sandbox.true_positives + sandbox.false_negatives
    assert sandbox.total_detected == sandbox.true_positives + sandbox.false_positives
    expected_prec = round(sandbox.true_positives / (sandbox.true_positives + sandbox.false_positives), 4)
    expected_rec = round(sandbox.true_positives / (sandbox.true_positives + sandbox.false_negatives), 4)
    expected_f1 = round(2.0 * (expected_prec * expected_rec) / (expected_prec + expected_rec), 4)

    assert sandbox.precision == expected_prec
    assert sandbox.recall == expected_rec
    assert sandbox.f1_score == expected_f1

    # Per-type invariants
    for t_name, metrics in sandbox.by_type.items():
        assert metrics.ground_truth_count == metrics.true_positives + metrics.false_negatives, (
            f"Type {t_name}: ground_truth_count != TP + FN"
        )
        assert metrics.detected_count == metrics.true_positives + metrics.false_positives, (
            f"Type {t_name}: detected_count != TP + FP"
        )
        t_prec = round(metrics.true_positives / (metrics.true_positives + metrics.false_positives), 4)
        t_rec = round(metrics.true_positives / (metrics.true_positives + metrics.false_negatives), 4)
        t_f1 = round(2.0 * (t_prec * t_rec) / (t_prec + t_rec), 4)

        assert metrics.precision == t_prec, f"Type {t_name}: precision mismatch"
        assert metrics.recall == t_rec, f"Type {t_name}: recall mismatch"
        assert metrics.f1_score == t_f1, f"Type {t_name}: f1 mismatch"

