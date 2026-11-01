"""Integration tests for Version 2.3 recommendation evaluation engine and report validation."""

from datetime import datetime
from pathlib import Path
import sqlite3
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.schemas.evaluation import (
    ComprehensiveEvaluationReportSchema,
    WindowEvaluationResultSchema,
)
from src.services.anomaly.sandbox_manager import BASELINE_DB_PATH, SandboxManager
from src.services.evaluation.engine import (
    ComprehensiveEvaluationReport,
    RecommendationEvaluationEngine,
    WindowEvaluationResult,
)
from src.services.evaluation.temporal_split import TemporalWindow


@pytest.fixture
def eval_engine_session(tmp_path: Path):
    """Provides an isolated clone of the clean baseline database."""
    sandbox_db = tmp_path / "eval_engine_sandbox.db"
    report_dir = tmp_path / "reports"
    SandboxManager.clone_baseline(destination_path=sandbox_db)
    engine = create_engine(f"sqlite:///{sandbox_db.as_posix()}")
    with Session(engine) as session:
        yield session, report_dir


def test_evaluation_engine_v2_3_end_to_end(eval_engine_session):
    """Test full multi-cutoff evaluation pipeline with Version 2.3 metrics and schema validation."""
    session, report_dir = eval_engine_session

    engine_svc = RecommendationEvaluationEngine(session, k_values=(1, 3, 5, 10))

    # Evaluate window T1 (2026-08-01, 30 days)
    w1 = TemporalWindow.create(
        cutoff=datetime(2026, 8, 1, 0, 0, 0),
        window_days=30,
        dataset_max_timestamp=datetime(2026, 10, 30, 19, 20, 44),
    )

    report = engine_svc.run_comprehensive_evaluation(windows=[w1])
    json_path, md_path = engine_svc.save_reports(report, output_dir=report_dir)

    # 1. Report structure and Pydantic validation
    assert report.evaluation_id.startswith("EVAL-")
    assert len(report.windows_evaluated) == 1

    report_dict = report.to_dict()
    validated_report = ComprehensiveEvaluationReportSchema.model_validate(report_dict)
    assert validated_report.evaluation_id == report.evaluation_id

    w_res: WindowEvaluationResult = report.windows_evaluated[0]
    WindowEvaluationResultSchema.model_validate(w_res.__dict__)

    # 2. Accounting
    assert w_res.total_learners == 100
    assert w_res.evaluated_learners == 63
    assert w_res.excluded_learners == 37
    assert w_res.cold_start_learners >= 10
    assert w_res.active_catalog_size == 100

    # 3. Version 2.3 metrics across K
    for k in (1, 3, 5, 10):
        m = w_res.metrics_by_k[k]
        # Legacy
        assert 0.0 <= m.mean_precision <= 1.0
        assert 0.0 <= m.mean_standard_recall <= 1.0
        assert 0.0 <= m.mean_bounded_recall <= 1.0
        assert 0.0 <= m.mean_ndcg <= 1.0
        assert 0.0 <= m.catalog_coverage <= 1.0
        assert 0.0 <= m.gini_coefficient <= 1.0

        # Version 2.3
        assert 0.0 <= m.mean_realized_precision <= 1.0
        assert 0.0 <= m.mean_unobserved_exposure_rate <= 1.0
        if m.mean_observed_precision is not None:
            assert 0.0 <= m.mean_observed_precision <= 1.0
        if m.mean_ndcg_ideal_pool is not None:
            assert 0.0 <= m.mean_ndcg_ideal_pool <= 1.0

        # Stratified activity disparity at rank K
        assert m.stratified_disparity is not None
        sd = m.stratified_disparity
        assert "stratum_metrics" in sd
        assert "stratum_sizes" in sd
        assert "evaluated_stratum_sizes" in sd
        assert "low" in sd["stratum_metrics"]
        assert "med" in sd["stratum_metrics"]
        assert "high" in sd["stratum_metrics"]

    # 4. Cold-start conversion metrics (Version 2.3)
    cs = w_res.cold_start_conversion
    assert cs is not None
    assert cs["total_cold_start"] >= 10
    assert cs["active_cold_start"] >= 0
    assert cs["converted_cold_start"] >= 0
    if cs["active_cold_start"] == 0:
        assert cs["conditional_conversion_rate"] is None
        assert cs["diagnostic"] == "NO_COLD_START_ATTEMPTS"

    # 5. Observational learning gain (Version 2.3)
    lg = w_res.observational_learning_gain
    assert lg is not None

    # 6. Read-only Five Anomaly Audits
    anom = w_res.anomaly_audits
    assert anom is not None
    assert anom["total_audits"] == 5
    assert anom["all_passed"] is True
    for name, a in anom["audits"].items():
        assert a["passed"] is True
        assert a["violations_count"] == 0

    # 7. File persistence
    assert json_path.exists()
    assert json_path.stat().st_size > 1000
    assert md_path.exists()
    assert md_path.stat().st_size > 1000

    # 8. Clean baseline database cleanliness verification (no rows added)
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
