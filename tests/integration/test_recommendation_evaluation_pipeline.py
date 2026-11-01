"""Integration test for the end-to-end recommendation evaluation pipeline."""

from datetime import datetime
from pathlib import Path
import sqlite3
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.services.anomaly.sandbox_manager import BASELINE_DB_PATH, SandboxManager
from src.services.evaluation.engine import RecommendationEvaluationEngine
from src.services.evaluation.temporal_split import TemporalWindow


def test_full_recommendation_evaluation_pipeline_e2e(tmp_path: Path):
    """End-to-end evaluation pipeline test on an isolated database clone."""
    sandbox_db = tmp_path / "eval_pipeline_sandbox.db"
    report_dir = tmp_path / "reports"

    # Step 1: Clone baseline database safely
    SandboxManager.clone_baseline(destination_path=sandbox_db)
    assert sandbox_db.exists()

    # Step 2: Initialize engine on sandbox connection
    engine = create_engine(f"sqlite:///{sandbox_db.as_posix()}")
    with Session(engine) as session:
        engine_svc = RecommendationEvaluationEngine(session, k_values=(1, 3, 5, 10))

        # Evaluate window T1 (2026-08-01, 30 days)
        w1 = TemporalWindow.create(
            cutoff=datetime(2026, 8, 1, 0, 0, 0),
            window_days=30,
            dataset_max_timestamp=datetime(2026, 10, 30, 19, 20, 44),
        )

        report = engine_svc.run_comprehensive_evaluation(windows=[w1])
        json_path, md_path = engine_svc.save_reports(report, output_dir=report_dir)

        # Step 3: Assert report structure and metric sanity
        assert report.evaluation_id.startswith("EVAL-")
        assert len(report.windows_evaluated) == 1
        w_res = report.windows_evaluated[0]

        assert w_res.total_learners == 100
        assert w_res.cold_start_learners >= 10  # 10 permanent cold-start learners + point-in-time cold learners
        assert w_res.active_catalog_size == 100
        assert w_res.evaluated_learners > 0

        # Step 4: Verify business-rule invariants
        prereq = w_res.prerequisite_audit
        assert prereq is not None
        assert prereq["compliance_rate"] == 1.0
        assert prereq["violations_count"] == 0

        leakage = w_res.temporal_leakage_audit
        assert leakage is not None
        assert leakage["leakage_rate"] == 0.0
        assert leakage["leaking_evaluations"] == 0

        # Step 5: Verify metrics across K
        for k in (1, 3, 5, 10):
            m = w_res.metrics_by_k[k]
            assert 0.0 <= m.mean_precision <= 1.0
            assert 0.0 <= m.mean_standard_recall <= 1.0
            assert 0.0 <= m.mean_bounded_recall <= 1.0
            assert 0.0 <= m.mean_ndcg <= 1.0
            assert 0.0 <= m.catalog_coverage <= 1.0
            assert 0.0 <= m.gini_coefficient <= 1.0

        # Step 6: Verify artifact creation
        assert json_path.exists()
        assert json_path.stat().st_size > 500
        assert md_path.exists()
        assert md_path.stat().st_size > 500

    # Step 7: Strict verification that clean baseline database is 100% clean and untouched
    conn = sqlite3.connect(f"file:{BASELINE_DB_PATH.as_posix()}?mode=ro", uri=True)
    try:
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM data_issues;")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM mastery_snapshots;")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM recommendations;")
        assert cur.fetchone()[0] == 0
    finally:
        conn.close()
