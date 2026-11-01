"""Integration tests for the anomaly detection and evaluation pipeline."""

from pathlib import Path
import sqlite3
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.services.anomaly.detector import AnomalyDetectionService
from src.services.anomaly.evaluation import AnomalyEvaluator
from src.services.anomaly.fixture_generator import (
    ANOMALY_TYPE_A1,
    ANOMALY_TYPE_A2,
    ANOMALY_TYPE_A3,
    ANOMALY_TYPE_A4,
    ANOMALY_TYPE_A5,
    AnomalyFixtureGenerator,
)
from src.services.anomaly.sandbox_manager import (
    BASELINE_DB_PATH,
    SandboxManager,
)


def test_full_anomaly_pipeline_e2e(tmp_path: Path):
    """End-to-end test: clone -> inject -> detect -> record -> evaluate -> verify baseline intact."""
    sandbox_db = tmp_path / "sandbox.db"
    gt_csv = tmp_path / "labels.csv"

    # Step 1: Clone clean baseline
    SandboxManager.clone_baseline(destination_path=sandbox_db)
    assert sandbox_db.exists()

    # Step 2: Inject all 5 canonical anomaly fixtures
    generator = AnomalyFixtureGenerator(sandbox_db_path=sandbox_db, ground_truth_csv_path=gt_csv)
    injected_labels = generator.inject_all()
    assert len(injected_labels) == 5
    assert gt_csv.exists()

    # Step 3: Run detection service on sandbox
    engine = create_engine(f"sqlite:///{sandbox_db.as_posix()}")
    with Session(engine) as session:
        detector = AnomalyDetectionService(session)
        detected_issues = detector.detect_all()
        assert len(detected_issues) == 5

        # Step 4: Record issues idempotently
        new_count = detector.record_issues(detected_issues)
        assert new_count == 5

        # Step 5: Evaluate against ground-truth CSV
        report = AnomalyEvaluator.evaluate_session(session, ground_truth_csv_path=gt_csv)

        # Step 6: Verify metrics: Precision = 1.0, Recall = 1.0, F1 = 1.0
        assert report.total_ground_truth == 5
        assert report.total_detected == 5
        assert report.true_positives == 5
        assert report.false_positives == 0
        assert report.false_negatives == 0
        assert report.precision == 1.0
        assert report.recall == 1.0
        assert report.f1_score == 1.0

        # Verify each of the 5 canonical anomaly types achieved perfect score
        for a_type in [
            ANOMALY_TYPE_A1,
            ANOMALY_TYPE_A2,
            ANOMALY_TYPE_A3,
            ANOMALY_TYPE_A4,
            ANOMALY_TYPE_A5,
        ]:
            metrics = report.by_type[a_type]
            assert metrics.ground_truth_count == 1
            assert metrics.detected_count == 1
            assert metrics.true_positives == 1
            assert metrics.false_positives == 0
            assert metrics.false_negatives == 0
            assert metrics.precision == 1.0
            assert metrics.recall == 1.0
            assert metrics.f1_score == 1.0

    # Step 7: Strict verification that baseline database is 100% clean and intact
    baseline_conn = sqlite3.connect(f"file:{BASELINE_DB_PATH.as_posix()}?mode=ro", uri=True)
    try:
        cur = baseline_conn.cursor()
        cur.execute("SELECT count(*) FROM data_issues;")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM mastery_snapshots;")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM recommendations;")
        assert cur.fetchone()[0] == 0
    finally:
        baseline_conn.close()
