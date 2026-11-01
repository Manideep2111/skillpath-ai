"""Personalized recommendation and outcome tracking endpoints for SkillPath AI."""

from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.database import get_db
from src.models.entities import Attempt, ContentItem, ContentSkill, Learner, Skill
from src.schemas.recommendations import (
    AbandonRecommendationRequest,
    CompleteRecommendationRequest,
    ErrorDetail,
    LearnerOverviewResponse,
    LearnerRecentActivitySchema,
    LearnerRecommendedPreviewSchema,
    LearnerSkillOverviewSchema,
    RecommendationOutcomeResponse,
    RecommendationResponse,
    StartRecommendationRequest,
)
from src.services.mastery_service import MasteryService
from src.services.outcome_service import (
    InvalidInteractionAttemptError,
    InvalidStateTransitionError,
    OutcomeTrackingService,
    RecommendationNotFoundError,
)
from src.services.recommendation_service import RecommendationService

router = APIRouter()


@router.get(
    "/learners/{learner_id}/recommendations",
    response_model=RecommendationResponse,
    summary="Get Personalized Content Recommendations",
    description=(
        "Compute deterministic, explainable learning recommendations for a learner "
        "as of a point-in-time cutoff. Uses prerequisite validation, skill gaps, "
        "curriculum path alignment, and spaced practice urgency. When persist=True, "
        "atomically stores recommendations and initializes their outcome tracking."
    ),
    responses={
        200: {
            "model": RecommendationResponse,
            "description": "Recommendations successfully calculated and ranked.",
        },
        400: {
            "model": ErrorDetail,
            "description": "Invalid parameter (e.g. timezone-aware cutoff or whitespace learner ID).",
        },
        404: {
            "model": ErrorDetail,
            "description": "Learner ID does not exist in the database.",
        },
        422: {
            "description": "Validation error (e.g. top_k < 1 or invalid datetime string format).",
        },
    },
)
def get_learner_recommendations(
    learner_id: str = Path(
        ...,
        description="Unique learner identifier (e.g. 'LRN-000001').",
        examples=["LRN-000001"],
    ),
    cutoff_timestamp: Optional[datetime] = Query(
        default=None,
        description=(
            "Point-in-time cutoff timestamp in ISO 8601 format without timezone offset "
            "(e.g., '2026-10-30T12:00:00'). When omitted, defaults to current UTC time."
        ),
        examples=["2026-10-30T12:00:00"],
    ),
    top_k: int = Query(
        default=5,
        ge=1,
        le=50,
        description="Maximum number of recommendations to return (>= 1). Default is 5.",
    ),
    persist: bool = Query(
        default=False,
        description="Whether to atomically persist generated recommendations and initial outcomes.",
    ),
    db: Session = Depends(get_db),
) -> RecommendationResponse:
    """Generate deterministic recommendations for a learner."""
    # Validate learner_id is non-empty string
    if not learner_id or not learner_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="learner_id must be a non-empty string.",
        )

    # Validate cutoff timestamp is timezone-naive
    if cutoff_timestamp is not None:
        if cutoff_timestamp.tzinfo is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="cutoff_timestamp must be timezone-naive.",
            )
        eval_cutoff = cutoff_timestamp
    else:
        eval_cutoff = datetime.utcnow()

    service = RecommendationService(db)
    try:
        batch = service.get_recommendations(
            learner_id=learner_id,
            cutoff_timestamp=eval_cutoff,
            top_k=top_k,
            persist=persist,
        )
        if persist:
            db.commit()
    except ValueError as exc:
        db.rollback()
        err_msg = str(exc)
        if "does not exist" in err_msg:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=err_msg,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=err_msg,
        )
    except Exception:
        db.rollback()
        raise

    return RecommendationResponse.model_validate(batch)


@router.get(
    "/learners/{learner_id}/overview",
    response_model=LearnerOverviewResponse,
    summary="Get Learner Profile & Progression Overview",
    description="Retrieve learner learning progression, skills needing attention, recent activity, and recommended next activities.",
    responses={
        200: {"model": LearnerOverviewResponse, "description": "Learner overview successfully compiled."},
        404: {"model": ErrorDetail, "description": "Learner not found."},
    },
)
def get_learner_overview(
    learner_id: str = Path(..., description="Unique learner identifier (e.g. 'LRN-000001')"),
    db: Session = Depends(get_db),
) -> LearnerOverviewResponse:
    """Retrieve verified point-in-time learner metrics, skills, and activity progression."""
    learner = db.get(Learner, learner_id)
    if not learner:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Learner '{learner_id}' not found.",
        )

    # 1. Query attempts with optional assessment result score
    from src.models.entities import AssessmentResult

    attempt_rows = db.execute(
        select(Attempt, AssessmentResult.normalized_score)
        .outerjoin(AssessmentResult, AssessmentResult.attempt_id == Attempt.attempt_id)
        .filter(Attempt.learner_id == learner_id)
        .order_by(Attempt.started_at.desc())
    ).all()

    total_attempts = len(attempt_rows)
    completed_attempts = sum(1 for a, _ in attempt_rows if a.status == "COMPLETED")
    in_progress_attempts = sum(1 for a, _ in attempt_rows if a.status == "IN_PROGRESS")
    completed_scores = [float(score) for a, score in attempt_rows if a.status == "COMPLETED" and score is not None]
    average_score = round(sum(completed_scores) / len(completed_scores), 4) if completed_scores else None

    # 2. Recent activities (up to 5)
    recent_activities: list[LearnerRecentActivitySchema] = []
    content_ids = {a.content_id for a, _ in attempt_rows[:5]}
    content_map = {}
    if content_ids:
        items = db.scalars(select(ContentItem).filter(ContentItem.content_id.in_(content_ids))).all()
        content_map = {c.content_id: c.title for c in items}

    for a, score in attempt_rows[:5]:
        recent_activities.append(
            LearnerRecentActivitySchema(
                attempt_id=a.attempt_id,
                content_id=a.content_id,
                content_title=content_map.get(a.content_id, a.content_id),
                score=float(score) if score is not None else None,
                is_completed=(a.status == "COMPLETED"),
                started_at=a.started_at,
                completed_at=a.completed_at,
            )
        )


    # 3. Skills summary and skills needing attention
    practiced_skill_ids = db.scalars(
        select(ContentSkill.skill_id)
        .join(Attempt, Attempt.content_id == ContentSkill.content_id)
        .filter(Attempt.learner_id == learner_id)
        .distinct()
    ).all()
    skills_practiced_count = len(practiced_skill_ids)

    now = datetime.utcnow()
    mastery_service = MasteryService(db)
    skills_needing_attention: list[LearnerSkillOverviewSchema] = []

    if practiced_skill_ids:
        skills = db.scalars(select(Skill).filter(Skill.skill_id.in_(practiced_skill_ids))).all()
        skill_dict = {s.skill_id: s for s in skills}

        scored_skills = []
        for sid, skill_obj in skill_dict.items():
            mastery_level, count, confidence, _, _ = mastery_service.compute_mastery(learner_id, sid, now)
            m_val = float(mastery_level) if mastery_level is not None else 0.0
            c_val = float(confidence) if confidence is not None else 0.0
            scored_skills.append((m_val, c_val, skill_obj))

        # Sort ascending by mastery (lowest mastery first)
        scored_skills.sort(key=lambda x: (x[0], -x[1]))
        for m_val, c_val, s_obj in scored_skills[:5]:
            skills_needing_attention.append(
                LearnerSkillOverviewSchema(
                    skill_id=s_obj.skill_id,
                    skill_name=s_obj.name,
                    domain=s_obj.domain,
                    mastery_score=round(m_val, 4),
                    confidence=round(c_val, 4),
                )
            )

    # 4. Recommended next activity preview (top 2)
    recommended_preview: list[LearnerRecommendedPreviewSchema] = []
    try:
        rec_service = RecommendationService(db)
        batch = rec_service.get_recommendations(
            learner_id=learner_id,
            cutoff_timestamp=now,
            top_k=2,
            persist=False,
        )
        for item in batch.items[:2]:
            recommended_preview.append(
                LearnerRecommendedPreviewSchema(
                    content_id=item.content_id,
                    title=item.title,
                    target_skill_id=item.target_skill_id,
                    score=float(item.score),
                    difficulty_match=float(item.score_components.difficulty_suitability),
                    primary_reason_code=item.primary_reason_code,
                )
            )
    except Exception:
        recommended_preview = []

    return LearnerOverviewResponse(
        learner_id=learner.learner_id,
        first_name=learner.first_name,
        last_name=learner.last_name,
        experience_level=learner.experience_level,
        total_attempts=total_attempts,
        completed_attempts=completed_attempts,
        in_progress_attempts=in_progress_attempts,
        average_score=average_score,
        skills_practiced_count=skills_practiced_count,
        skills_needing_attention=skills_needing_attention,
        recent_activities=recent_activities,
        recommended_preview=recommended_preview,
    )


@router.post(
    "/recommendations/{recommendation_id}/start",
    response_model=RecommendationOutcomeResponse,
    summary="Record Recommendation Interaction Start",
    description="Transitions recommendation outcome status from RECOMMENDED to STARTED and associates an interaction attempt.",
    responses={
        200: {"model": RecommendationOutcomeResponse, "description": "Outcome transitioned to STARTED."},
        400: {"model": ErrorDetail, "description": "Invalid attempt or temporal violation."},
        404: {"model": ErrorDetail, "description": "Recommendation or attempt not found."},
        409: {"model": ErrorDetail, "description": "Illegal state transition."},
    },
)
def start_recommendation(
    recommendation_id: str = Path(..., description="Target recommendation ID (e.g. 'REC-2026-000001')"),
    request: StartRecommendationRequest = ...,
    db: Session = Depends(get_db),
) -> RecommendationOutcomeResponse:
    """Record that a learner has begun interacting with a recommendation."""
    outcome_service = OutcomeTrackingService(db)
    try:
        outcome = outcome_service.record_interaction_start(
            recommendation_id=recommendation_id,
            attempt_id=request.attempt_id,
            started_at=request.started_at,
        )
        db.commit()
        return RecommendationOutcomeResponse.model_validate(outcome)
    except RecommendationNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except InvalidStateTransitionError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except InvalidInteractionAttemptError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception:
        db.rollback()
        raise


@router.post(
    "/recommendations/{recommendation_id}/complete",
    response_model=RecommendationOutcomeResponse,
    summary="Record Recommendation Interaction Completion",
    description="Transitions recommendation outcome status from STARTED to COMPLETED.",
    responses={
        200: {"model": RecommendationOutcomeResponse, "description": "Outcome transitioned to COMPLETED."},
        400: {"model": ErrorDetail, "description": "Invalid interaction completion."},
        404: {"model": ErrorDetail, "description": "Recommendation not found."},
        409: {"model": ErrorDetail, "description": "Illegal state transition."},
    },
)
def complete_recommendation(
    recommendation_id: str = Path(..., description="Target recommendation ID"),
    request: CompleteRecommendationRequest = ...,
    db: Session = Depends(get_db),
) -> RecommendationOutcomeResponse:
    """Record that a learner completed interacting with a recommendation."""
    outcome_service = OutcomeTrackingService(db)
    try:
        outcome = outcome_service.record_interaction_completion(
            recommendation_id=recommendation_id,
            completed_at=request.completed_at,
        )
        db.commit()
        return RecommendationOutcomeResponse.model_validate(outcome)
    except RecommendationNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except InvalidStateTransitionError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except (InvalidInteractionAttemptError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception:
        db.rollback()
        raise


@router.post(
    "/recommendations/{recommendation_id}/abandon",
    response_model=RecommendationOutcomeResponse,
    summary="Record Recommendation Interaction Abandonment",
    description="Transitions recommendation outcome status from STARTED to ABANDONED (terminal state).",
    responses={
        200: {"model": RecommendationOutcomeResponse, "description": "Outcome transitioned to ABANDONED."},
        400: {"model": ErrorDetail, "description": "Invalid operation."},
        404: {"model": ErrorDetail, "description": "Recommendation not found."},
        409: {"model": ErrorDetail, "description": "Illegal state transition."},
    },
)
def abandon_recommendation(
    recommendation_id: str = Path(..., description="Target recommendation ID"),
    request: AbandonRecommendationRequest = ...,
    db: Session = Depends(get_db),
) -> RecommendationOutcomeResponse:
    """Record that a learner abandoned a started recommendation."""
    outcome_service = OutcomeTrackingService(db)
    try:
        outcome = outcome_service.record_interaction_abandonment(
            recommendation_id=recommendation_id,
            abandoned_at=request.abandoned_at,
        )
        db.commit()
        return RecommendationOutcomeResponse.model_validate(outcome)
    except RecommendationNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except InvalidStateTransitionError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception:
        db.rollback()
        raise


@router.post(
    "/recommendations/{recommendation_id}/evaluate",
    response_model=RecommendationOutcomeResponse,
    summary="Evaluate Recommendation Outcome & Mastery Delta",
    description=(
        "Evaluates pre- and post-interaction mastery on the target skill and transitions "
        "outcome status to IMPROVED or NO_IMPROVEMENT with calculated mastery delta."
    ),
    responses={
        200: {"model": RecommendationOutcomeResponse, "description": "Outcome evaluated and updated."},
        400: {"model": ErrorDetail, "description": "Missing graded assessment or temporal error."},
        404: {"model": ErrorDetail, "description": "Recommendation not found."},
        409: {"model": ErrorDetail, "description": "Illegal state transition or terminal state."},
    },
)
def evaluate_recommendation_outcome(
    recommendation_id: str = Path(..., description="Target recommendation ID"),
    db: Session = Depends(get_db),
) -> RecommendationOutcomeResponse:
    """Evaluate learning gain and record outcome resolution."""
    outcome_service = OutcomeTrackingService(db)
    try:
        outcome, pre_m, post_m, delta = outcome_service.evaluate_outcome(
            recommendation_id=recommendation_id
        )
        db.commit()
        return RecommendationOutcomeResponse.model_validate(outcome)
    except RecommendationNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except InvalidStateTransitionError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except (InvalidInteractionAttemptError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception:
        db.rollback()
        raise
