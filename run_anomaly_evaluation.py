"""Runner script for SkillPath AI anomaly sandbox, detection, and evaluation."""

import argparse
import json
import logging
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.services.anomaly.detector import AnomalyDetectionService
from src.services.anomaly.evaluation import AnomalyEvaluator
from src.services.anomaly.fixture_generator import (
    DEFAULT_GROUND_TRUTH_PATH,
    AnomalyFixtureGenerator,
)
from src.services.anomaly.sandbox_manager import (
    DEFAULT_SANDBOX_PATH,
    SandboxManager,
    SandboxOverwriteError,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("anomaly_evaluation")


def run_pipeline(
    sandbox_path: Path = DEFAULT_SANDBOX_PATH,
    ground_truth_path: Path = DEFAULT_GROUND_TRUTH_PATH,
    force_recreate: bool = False,
) -> dict:
    """Run end-to-end anomaly detection and evaluation pipeline."""
    logger.info("Initializing anomaly sandbox at: %s", sandbox_path)
    try:
        SandboxManager.clone_baseline(destination_path=sandbox_path, force_recreate=force_recreate)
    except SandboxOverwriteError as e:
        logger.warning("%s. Reusing existing sandbox.", e)

    logger.info("Injecting deterministic anomaly fixtures into sandbox...")
    generator = AnomalyFixtureGenerator(
        sandbox_db_path=sandbox_path,
        ground_truth_csv_path=ground_truth_path,
    )
    generator.inject_all()
    logger.info("Saved ground-truth labels to: %s", ground_truth_path)

    logger.info("Running AnomalyDetectionService scan...")
    engine = create_engine(f"sqlite:///{sandbox_path.as_posix()}")
    with Session(engine) as session:
        detector = AnomalyDetectionService(session)
        issues = detector.detect_all()
        logger.info("Detected %d issues across all 5 SRS anomaly types.", len(issues))

        new_count = detector.record_issues(issues)
        logger.info("Recorded %d new issues into data_issues table (idempotent).", new_count)

        logger.info("Evaluating detection results against ground-truth labels...")
        report = AnomalyEvaluator.evaluate_session(session, ground_truth_csv_path=ground_truth_path)

    summary = report.summary_dict()
    print("\n" + "=" * 80)
    print("SKILLPATH AI — ANOMALY DETECTION EVALUATION REPORT")
    print("=" * 80)
    print(f"Sandbox Target     : {sandbox_path}")
    print(f"Ground-Truth CSV   : {ground_truth_path}")
    print(f"Ground-Truth Count : {report.total_ground_truth}")
    print(f"Detected Count     : {report.total_detected}")
    print(f"True Positives     : {report.true_positives}")
    print(f"False Positives    : {report.false_positives}")
    print(f"False Negatives    : {report.false_negatives}")
    print(f"Precision          : {report.precision:.4f}")
    print(f"Recall             : {report.recall:.4f}")
    print(f"F1 Score           : {report.f1_score:.4f}")
    print("-" * 80)
    print(f"{'Anomaly Type':<30} {'GT':<5} {'Det':<5} {'TP':<5} {'FP':<5} {'FN':<5} {'Prec':<7} {'Rec':<7} {'F1':<7}")
    print("-" * 80)
    for a_type, m in report.by_type.items():
        print(
            f"{a_type:<30} {m.ground_truth_count:<5} {m.detected_count:<5} {m.true_positives:<5} "
            f"{m.false_positives:<5} {m.false_negatives:<5} {m.precision:<7.4f} {m.recall:<7.4f} {m.f1_score:<7.4f}"
        )
    print("=" * 80 + "\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description="SkillPath AI Anomaly Evaluation Pipeline")
    parser.add_argument(
        "--sandbox",
        type=Path,
        default=DEFAULT_SANDBOX_PATH,
        help="Path to sandbox database",
    )
    parser.add_argument(
        "--ground-truth",
        type=Path,
        default=DEFAULT_GROUND_TRUTH_PATH,
        help="Path to ground truth labels CSV",
    )
    parser.add_argument(
        "--force-recreate",
        action="store_true",
        help="Force re-creation of the sandbox if it already exists",
    )
    args = parser.parse_args()
    run_pipeline(
        sandbox_path=args.sandbox,
        ground_truth_path=args.ground_truth,
        force_recreate=args.force_recreate,
    )


if __name__ == "__main__":
    main()
