"""Evaluation report API endpoints for SkillPath AI.

Provides read-only access to compiled temporal evaluation reports
under data/reports/.
"""

import json
import logging
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException, status

from src.schemas.evaluation import ComprehensiveEvaluationReportSchema

logger = logging.getLogger(__name__)

router = APIRouter()

DEFAULT_REPORTS_DIR = Path("D:/SkillPathAI/data/reports").resolve()


def get_latest_evaluation_report_path(reports_dir: Optional[Path] = None) -> Path:
    """Safely locate the most recently generated evaluation report file.

    Strictly inspects the server-configured reports directory and matches
    recommendation_evaluation_*.json files by modification timestamp.
    Rejects any client-supplied file paths.

    Args:
        reports_dir: Path to directory containing JSON evaluation reports.

    Returns:
        Path: Absolute path to latest report file.

    Raises:
        FileNotFoundError: If no matching report files are found.
    """
    target_dir = reports_dir if reports_dir is not None else DEFAULT_REPORTS_DIR
    if not target_dir.exists() or not target_dir.is_dir():
        raise FileNotFoundError(f"Reports directory not found at '{target_dir}'.")

    report_files = list(target_dir.glob("recommendation_evaluation_*.json"))
    if not report_files:
        raise FileNotFoundError(f"No recommendation evaluation JSON reports found in '{target_dir}'.")

    # Sort by mtime descending (most recent first)
    report_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return report_files[0]


@router.get(
    "/evaluation/latest",
    response_model=ComprehensiveEvaluationReportSchema,
    summary="Get Latest Comprehensive Evaluation Report",
    description=(
        "Retrieve the most recently compiled recommendation quality and temporal "
        "evaluation report. Includes Precision@K, Realized Precision@K, Observed Precision@K, "
        "Recall@K, NDCG@K Pool, catalog coverage, Gini, Cold-Start conversion, "
        "observational learning gain, stratified activity disparity (Section 3.5.2), "
        "and read-only anomaly audits across all evaluated temporal windows."
    ),
    responses={
        200: {
            "model": ComprehensiveEvaluationReportSchema,
            "description": "Latest evaluation report successfully loaded.",
        },
        404: {
            "description": "No evaluation reports exist in data/reports/.",
        },
    },
)
def get_latest_evaluation():
    """Return the latest multi-window evaluation report."""
    try:
        report_path = get_latest_evaluation_report_path()
    except FileNotFoundError as err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(err),
        )

    try:
        with open(report_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return ComprehensiveEvaluationReportSchema.model_validate(data)
    except Exception as err:
        logger.error("Failed to load or parse evaluation report at '%s': %s", report_path, err)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to read evaluation report: {str(err)}",
        )
