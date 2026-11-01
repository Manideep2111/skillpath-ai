"""Health check and readiness endpoints for SkillPath AI."""

from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from src.core.config import settings
from src.db.database import get_db
from src.models.entities import Learner, Skill, Course, ContentItem, Attempt, AssessmentResult, LearningPath
from src.schemas.recommendations import HealthResponse, SystemSummaryResponse

router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="System Health & Database Connectivity Check",
    description="Performs a lightweight read-only query to ensure database connectivity.",
    responses={
        200: {
            "model": HealthResponse,
            "description": "System and database are healthy.",
        },
        503: {
            "description": "Database connectivity check failed.",
        },
    },
)
def health_check(db: Session = Depends(get_db)) -> HealthResponse:
    """Check application health and perform read-only DB connectivity test."""
    try:
        db.execute(text("SELECT 1")).scalar()
        return HealthResponse(
            status="healthy",
            database="connected",
            app_name=settings.app_name,
            version="1.0.0",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database connectivity check failed: {exc}",
        )


@router.get(
    "/system/summary",
    response_model=SystemSummaryResponse,
    summary="Get System Health and Live Dataset Summary",
    description="Retrieve high-level application health and verified dataset entity counts.",
    responses={
        200: {
            "model": SystemSummaryResponse,
            "description": "System summary successfully retrieved.",
        },
        503: {
            "description": "Failed to query system status.",
        },
    },
)
def get_system_summary(db: Session = Depends(get_db)) -> SystemSummaryResponse:
    """Retrieve high-level system status and live dataset statistics."""
    try:
        learners = db.scalar(select(func.count(Learner.learner_id))) or 0
        skills = db.scalar(select(func.count(Skill.skill_id))) or 0
        courses = db.scalar(select(func.count(Course.course_id))) or 0
        content_items = db.scalar(select(func.count(ContentItem.content_id))) or 0
        attempts = db.scalar(select(func.count(Attempt.attempt_id))) or 0
        assessment_results = db.scalar(select(func.count(AssessmentResult.result_id))) or 0
        learning_paths = db.scalar(select(func.count(LearningPath.path_id))) or 0

        bind_url = str(db.get_bind().url)
        db_file = Path(bind_url.split("///")[-1]).name if "///" in bind_url else "skillpath.db"

        return SystemSummaryResponse(
            status="healthy",
            database="connected",
            database_file=db_file,
            app_name=settings.app_name,
            version="1.0.0",
            learners_count=learners,
            skills_count=skills,
            courses_count=courses,
            content_items_count=content_items,
            attempts_count=attempts,
            assessment_results_count=assessment_results,
            learning_paths_count=learning_paths,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"System summary retrieval failed: {exc}",
        )

