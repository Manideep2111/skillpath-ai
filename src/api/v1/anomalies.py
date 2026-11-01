"""Data quality and anomaly status API endpoints for SkillPath AI.

Provides read-only baseline database audit inspection and isolated
anomaly detection sandbox benchmark metrics.
"""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from src.core.config import settings
from src.schemas.evaluation import (
    AnomalyAuditItemSchema,
    AnomalyStatusResponse,
    SandboxEvaluationSummarySchema,
    TypeEvaluationMetricsSchema,
)
from src.services.anomaly.evaluation import AnomalyEvaluator
from src.services.anomaly.fixture_generator import DEFAULT_GROUND_TRUTH_PATH
from src.services.anomaly.sandbox_manager import DEFAULT_SANDBOX_PATH
from src.services.evaluation.collectors import EvaluationDataCollector

logger = logging.getLogger(__name__)

router = APIRouter()

BASELINE_DB_PATH = Path("D:/SkillPathAI/skillpath.db").resolve()
REPORTS_DIR = Path("D:/SkillPathAI/data/reports").resolve()


def _get_baseline_audits_from_report_or_db() -> Dict[str, AnomalyAuditItemSchema]:
    """Retrieve baseline audit results from the latest report or run a read-only collector pass.

    Strictly read-only; never mutates the baseline database.
    """
    # 1. Check if a compiled evaluation report exists with full recommendation-time audits
    if REPORTS_DIR.exists() and REPORTS_DIR.is_dir():
        report_files = sorted(
            REPORTS_DIR.glob("recommendation_evaluation_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if report_files:
            try:
                with open(report_files[0], "r", encoding="utf-8") as f:
                    data = json.load(f)
                windows = data.get("windows_evaluated", [])
                if windows:
                    # Pick window with richest audit records (or latest window)
                    latest_window = windows[0]
                    anomaly_data = latest_window.get("anomaly_audits", {})
                    raw_audits = anomaly_data.get("audits", {})
                    if raw_audits:
                        result: Dict[str, AnomalyAuditItemSchema] = {}
                        for key, audit_dict in raw_audits.items():
                            result[key] = AnomalyAuditItemSchema.model_validate(audit_dict)
                        return result
            except Exception as err:
                logger.warning("Could not read audits from latest evaluation report: %s", err)

    # 2. Fallback: run read-only collector on baseline database
    if not BASELINE_DB_PATH.exists():
        raise FileNotFoundError(f"Baseline database not found at '{BASELINE_DB_PATH}'.")

    engine = create_engine(
        f"sqlite:///{BASELINE_DB_PATH.as_posix()}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def set_readonly_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA query_only = ON;")
        cursor.close()

    with Session(engine) as session:
        collector = EvaluationDataCollector(session)
        audit_results = collector.run_five_anomaly_audits(cutoff=datetime.now(timezone.utc))
        result = {}
        for key, res in audit_results.items():
            result[key] = AnomalyAuditItemSchema(
                audit_name=res.audit_name,
                anomaly_type=res.anomaly_type,
                passed=res.passed,
                total_checked=res.total_checked,
                violations_count=res.violations_count,
                details=res.details,
                metadata=res.metadata,
            )
        return result


def _get_sandbox_evaluation_summary() -> Optional[SandboxEvaluationSummarySchema]:
    """Evaluate anomaly detection on the isolated sandbox database against ground truth labels."""
    sandbox_path = Path(DEFAULT_SANDBOX_PATH).resolve()
    gt_path = Path(DEFAULT_GROUND_TRUTH_PATH).resolve()

    if not sandbox_path.exists() or not gt_path.exists():
        logger.warning(
            "Sandbox DB (%s) or Ground Truth file (%s) does not exist; skipping benchmark.",
            sandbox_path,
            gt_path,
        )
        return None

    engine = create_engine(
        f"sqlite:///{sandbox_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def set_readonly_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA query_only = ON;")
        cursor.close()

    try:
        with Session(engine) as session:
            eval_report = AnomalyEvaluator.evaluate_session(session, gt_path)

        by_type_schemas: Dict[str, TypeEvaluationMetricsSchema] = {}
        for k, v in eval_report.by_type.items():
            by_type_schemas[k] = TypeEvaluationMetricsSchema(
                anomaly_type=v.anomaly_type,
                ground_truth_count=v.ground_truth_count,
                detected_count=v.detected_count,
                true_positives=v.true_positives,
                false_positives=v.false_positives,
                false_negatives=v.false_negatives,
                precision=round(v.precision, 4),
                recall=round(v.recall, 4),
                f1_score=round(v.f1_score, 4),
            )

        return SandboxEvaluationSummarySchema(
            total_ground_truth=eval_report.total_ground_truth,
            total_detected=eval_report.total_detected,
            true_positives=eval_report.true_positives,
            false_positives=eval_report.false_positives,
            false_negatives=eval_report.false_negatives,
            precision=round(eval_report.precision, 4),
            recall=round(eval_report.recall, 4),
            f1_score=round(eval_report.f1_score, 4),
            by_type=by_type_schemas,
        )
    except Exception as err:
        logger.error("Failed to run sandbox anomaly evaluation: %s", err)
        return None


@router.get(
    "/anomalies/status",
    response_model=AnomalyStatusResponse,
    summary="Get Anomaly Detection and Data Quality Status",
    description=(
        "Retrieve data quality audit status for the production baseline database "
        "(verifying zero violations across SRS anomaly types A1 through A5) "
        "and benchmark accuracy metrics (Precision, Recall, F1) evaluated against "
        "the isolated anomaly sandbox and ground-truth labels."
    ),
    responses={
        200: {
            "model": AnomalyStatusResponse,
            "description": "Anomaly status successfully compiled.",
        },
        500: {
            "description": "Failed to compile anomaly status.",
        },
    },
)
def get_anomaly_status():
    """Return data quality audit results and sandbox benchmark metrics."""
    try:
        baseline_audits = _get_baseline_audits_from_report_or_db()
    except Exception as err:
        logger.error("Error evaluating baseline anomaly audits: %s", err)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error evaluating baseline anomaly audits: {str(err)}",
        )

    total_violations = sum(audit.violations_count for audit in baseline_audits.values())
    baseline_status = "CLEAN" if total_violations == 0 else "VIOLATIONS_DETECTED"

    sandbox_eval = _get_sandbox_evaluation_summary()

    return AnomalyStatusResponse(
        baseline_status=baseline_status,
        baseline_database=BASELINE_DB_PATH.name,
        total_baseline_violations=total_violations,
        baseline_audits=baseline_audits,
        sandbox_evaluation=sandbox_eval,
        sandbox_database=Path(DEFAULT_SANDBOX_PATH).name if Path(DEFAULT_SANDBOX_PATH).exists() else None,
        ground_truth_file=Path(DEFAULT_GROUND_TRUTH_PATH).name if Path(DEFAULT_GROUND_TRUTH_PATH).exists() else None,
    )
