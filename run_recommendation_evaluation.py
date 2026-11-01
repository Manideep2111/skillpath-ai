"""CLI runner script for SkillPath AI recommendation quality and temporal evaluation."""

import argparse
from datetime import datetime
import logging
from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from src.services.evaluation.engine import RecommendationEvaluationEngine
from src.services.evaluation.temporal_split import (
    TemporalWindow,
    get_dataset_temporal_bounds,
    get_standard_evaluation_windows,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("eval_runner")


def main():
    parser = argparse.ArgumentParser(description="SkillPath AI Recommendation Quality Evaluation")
    parser.add_argument(
        "--db-path",
        type=Path,
        default=Path("D:/SkillPathAI/skillpath.db"),
        help="Path to database file (evaluated strictly read-only)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("D:/SkillPathAI/data/reports"),
        help="Directory to save JSON and Markdown reports",
    )
    parser.add_argument(
        "--cutoffs",
        nargs="+",
        help="Optional ISO date strings for custom cutoffs (YYYY-MM-DDTHH:MM:SS)",
    )
    args = parser.parse_args()

    db_path = args.db_path.resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at '{db_path}'.")

    # Enforce read-only driver enforcement if connecting to clean baseline
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")

    @event.listens_for(engine, "connect")
    def set_readonly_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA query_only = ON;")
        cursor.close()

    with Session(engine) as session:
        logger.info("Connected to database: %s (PRAGMA query_only = ON)", db_path)

        if args.cutoffs:
            _, max_ts = get_dataset_temporal_bounds(session)
            windows = [
                TemporalWindow.create(
                    cutoff=datetime.fromisoformat(c_str),
                    window_days=30,
                    dataset_max_timestamp=max_ts,
                )
                for c_str in args.cutoffs
            ]
        else:
            windows = get_standard_evaluation_windows(session)

        engine_svc = RecommendationEvaluationEngine(session, k_values=(1, 3, 5, 10))
        report = engine_svc.run_comprehensive_evaluation(windows=windows)
        json_path, md_path = engine_svc.save_reports(report, output_dir=args.output_dir)

    print("\n" + "=" * 90)
    print(f"SKILLPATH AI — RECOMMENDATION QUALITY EVALUATION COMPLETE ({report.evaluation_id})")
    print("=" * 90)
    print(f"Reports Generated:")
    print(f"  - JSON Report     : {json_path}")
    print(f"  - Markdown Report : {md_path}")
    print("-" * 90)

    for idx, w in enumerate(report.windows_evaluated, start=1):
        partial_tag = " [PARTIALLY OBSERVED]" if w.is_partially_observed else ""
        print(f"\nWindow {idx}: Cutoff {w.cutoff}{partial_tag}")
        print(f"  Outcome Interval : {w.cutoff} to {w.actual_horizon}")
        print(f"  Learners (Total/Eval/Excl/Cold) : {w.total_learners} / {w.evaluated_learners} / {w.excluded_learners} / {w.cold_start_learners}")
        print(f"  Active Catalog   : {w.active_catalog_size} items")
        print(f"  {'Rank':<6} {'Precision':<12} {'Realized':<12} {'Std Recall':<12} {'NDCG(Pool)':<12} {'Coverage':<10} {'Gini':<10}")
        for k in (1, 3, 5, 10):
            m = w.metrics_by_k.get(k)
            if m:
                ndcg_pool_str = f"{m.mean_ndcg_ideal_pool:.4f}" if m.mean_ndcg_ideal_pool is not None else "N/A"
                print(f"  @{k:<5} {m.mean_precision:<12.4f} {m.mean_realized_precision:<12.4f} {m.mean_standard_recall:<12.4f} {ndcg_pool_str:<12} {m.catalog_coverage:<10.4f} {m.gini_coefficient:<10.4f}")

        # Version 2.3 metrics summary
        cs = w.cold_start_conversion or {}
        lg = w.observational_learning_gain or {}
        sd = w.stratified_disparity or {}
        cs_ov = cs.get("overall_conversion_rate")
        cs_cond = cs.get("conditional_conversion_rate")
        lg_val = lg.get("learning_gain")
        print(f"  Cold-Start Conversion   : Overall={cs_ov if cs_ov is not None else 'N/A'}, Cond={cs_cond if cs_cond is not None else 'N/A'} (Diag: {cs.get('diagnostic')})")
        print(f"  Observational Gain      : {float(lg_val):.4f}" if lg_val is not None else "  Observational Gain      : N/A")
        print(f"  Stratified Disparity @5 : Abs={sd.get('absolute_disparity')}, Ratio={sd.get('ratio_disparity')} (Diag: {sd.get('diagnostic')})")

        prereq = w.prerequisite_audit or {}
        leak = w.temporal_leakage_audit or {}
        print(f"  Prerequisite Compliance : {prereq.get('compliance_rate', 1.0):.4f} (Violations: {prereq.get('violations_count', 0)})")
        print(f"  Temporal Leakage Rate   : {leak.get('leakage_rate', 0.0):.4f} (Leaks: {leak.get('leaking_evaluations', 0)})")

        anom = w.anomaly_audits or {}
        if anom:
            all_pass = anom.get("all_passed", False)
            status_str = "[PASS] ALL AUDITS PASSED" if all_pass else "[FAIL] VIOLATIONS FOUND"
            print(f"  Five Anomaly Audits     : {status_str} ({anom.get('total_audits', 0)} audits)")

    print("\n" + "=" * 90 + "\n")


if __name__ == "__main__":
    main()
