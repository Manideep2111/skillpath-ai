"""Pydantic v2 response and request schemas for recommendations API.

Directly models the RecommendationService dataclasses:
ScoreComponents, RecommendedItem, RejectionSummary, and RecommendationBatch,
as well as RecommendationOutcome lifecycle tracking models.
"""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class ScoreComponentsSchema(BaseModel):
    """Component breakdown of the recommendation score."""

    gap: Decimal = Field(
        ...,
        description="Skill gap factor (0.0 to 1.0)",
    )
    difficulty_suitability: Decimal = Field(
        ...,
        description="Difficulty suitability factor (0.0 to 1.0)",
    )
    path_alignment: Decimal = Field(
        ...,
        description="Curriculum path alignment factor (0.0 to 1.0)",
    )
    practice_urgency: Decimal = Field(
        ...,
        description="Spaced repetition practice urgency factor (0.0 to 1.0)",
    )
    total: Decimal = Field(
        ...,
        description="Weighted composite score quantized to 6 decimal places",
    )

    model_config = ConfigDict(from_attributes=True)


class RecommendedItemSchema(BaseModel):
    """An individual recommended learning content item."""

    content_id: str = Field(
        ...,
        description="Unique identifier of the content item",
    )
    title: str = Field(
        ...,
        description="Title of the content item",
    )
    score: Decimal = Field(
        ...,
        description="Composite ranking score (0.0 to 1.0)",
    )
    score_components: ScoreComponentsSchema = Field(
        ...,
        description="Detailed scoring component breakdown",
    )
    target_skill_id: str = Field(
        ...,
        description="Primary skill targeted by this recommendation",
    )
    reason_codes: List[str] = Field(
        ...,
        description="Ordered list of explanation reason codes",
    )
    primary_reason_code: str = Field(
        ...,
        description="Primary explanation code (first in reason_codes)",
    )
    recommendation_id: Optional[str] = Field(
        default=None,
        description="Unique identifier of the persisted recommendation if persisted.",
    )

    model_config = ConfigDict(from_attributes=True)


class RejectionSummarySchema(BaseModel):
    """Summary of candidate items rejected by gating stages."""

    inactive_content: int = Field(
        default=0,
        description="Items rejected because is_active is False",
    )
    unpublished_content: int = Field(
        default=0,
        description="Items rejected because created after cutoff",
    )
    recent_completions: int = Field(
        default=0,
        description="Items rejected due to recent completion within 30 days",
    )
    prerequisite_blocked: int = Field(
        default=0,
        description="Items blocked by unfulfilled or unknown prerequisites",
    )
    no_relevant_skill_gap: int = Field(
        default=0,
        description="Items with no active mapped skills or gaps",
    )
    future_content: int = Field(
        default=0,
        description="Items created after the cutoff timestamp",
    )
    skill_already_mastered: int = Field(
        default=0,
        description="Items where all mapped skills are already mastered",
    )

    model_config = ConfigDict(from_attributes=True)


class RecommendationResponse(BaseModel):
    """Response payload for learner recommendations."""

    learner_id: str = Field(
        ...,
        description="Unique identifier of the learner",
    )
    cutoff_timestamp: datetime = Field(
        ...,
        description="Point-in-time cutoff timestamp (timezone-naive)",
    )
    items: List[RecommendedItemSchema] = Field(
        ...,
        description="Ranked list of recommended content items",
    )
    rejection_summary: RejectionSummarySchema = Field(
        ...,
        description="Gating rejection statistics",
    )

    model_config = ConfigDict(from_attributes=True)


class RecommendationOutcomeResponse(BaseModel):
    """Response payload for recommendation outcome lifecycle state."""

    outcome_id: str = Field(
        ...,
        description="Unique identifier of the outcome record",
    )
    recommendation_id: str = Field(
        ...,
        description="Identifier of the associated recommendation",
    )
    outcome_status: str = Field(
        ...,
        description="Lifecycle state (RECOMMENDED, STARTED, COMPLETED, ABANDONED, IMPROVED, NO_IMPROVEMENT)",
    )
    interaction_attempt_id: Optional[str] = Field(
        default=None,
        description="Identifier of the learner attempt interacting with this recommendation",
    )
    mastery_delta: Optional[Decimal] = Field(
        default=None,
        description="Measured mastery change from pre- to post-interaction",
    )
    recorded_at: datetime = Field(
        ...,
        description="Timestamp of the recorded outcome state change",
    )

    model_config = ConfigDict(from_attributes=True)


class StartRecommendationRequest(BaseModel):
    """Request payload to record interaction start on a recommendation."""

    attempt_id: str = Field(
        ...,
        description="Attempt identifier representing the learner's interaction",
        examples=["ATT-LRN-000001-000001"],
    )
    started_at: Optional[datetime] = Field(
        default=None,
        description="Optional explicit start timestamp (must not precede recommendation decision)",
    )


class CompleteRecommendationRequest(BaseModel):
    """Request payload to record completion of a recommendation interaction."""

    completed_at: Optional[datetime] = Field(
        default=None,
        description="Optional explicit completion timestamp",
    )


class AbandonRecommendationRequest(BaseModel):
    """Request payload to record abandonment of a recommendation interaction."""

    abandoned_at: Optional[datetime] = Field(
        default=None,
        description="Optional explicit abandonment timestamp",
    )


class HealthResponse(BaseModel):
    """System health check response."""

    status: str = Field(
        ...,
        description="Service health status ('healthy' or 'unhealthy')",
    )
    database: str = Field(
        ...,
        description="Database connection status ('connected' or 'disconnected')",
    )
    app_name: str = Field(
        ...,
        description="Application name",
    )
    version: str = Field(
        default="1.0.0",
        description="Application version",
    )


class SystemSummaryResponse(BaseModel):
    """High-level system health and dataset summary response."""

    status: str = Field(..., description="Service status ('healthy' or 'unhealthy')")
    database: str = Field(..., description="Database connectivity status ('connected' or 'disconnected')")
    database_file: str = Field(default="skillpath.db", description="Physical database target")
    app_name: str = Field(..., description="Application name")
    version: str = Field(default="1.0.0", description="Application version")
    learners_count: int = Field(default=0, ge=0)
    skills_count: int = Field(default=0, ge=0)
    courses_count: int = Field(default=0, ge=0)
    content_items_count: int = Field(default=0, ge=0)
    attempts_count: int = Field(default=0, ge=0)
    assessment_results_count: int = Field(default=0, ge=0)
    learning_paths_count: int = Field(default=0, ge=0)

    model_config = ConfigDict(from_attributes=True)


class ErrorDetail(BaseModel):
    """Standardized error response payload."""

    detail: str = Field(
        ...,
        description="Human-readable error description",
    )
    error_code: Optional[str] = Field(
        default=None,
        description="Domain-specific error code",
    )


class LearnerSkillOverviewSchema(BaseModel):
    """A skill requiring attention or practiced by the learner."""

    skill_id: str
    skill_name: str
    domain: str
    mastery_score: float = Field(..., ge=0.0, le=1.0)
    confidence: float = Field(..., ge=0.0, le=1.0)

    model_config = ConfigDict(from_attributes=True)


class LearnerRecentActivitySchema(BaseModel):
    """Recent learning interaction attempt."""

    attempt_id: str
    content_id: str
    content_title: str
    score: Optional[float] = None
    is_completed: bool
    started_at: datetime
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class LearnerRecommendedPreviewSchema(BaseModel):
    """Compact recommendation preview for the learner dashboard."""

    content_id: str
    title: str
    target_skill_id: str
    score: float
    difficulty_match: float
    primary_reason_code: str

    model_config = ConfigDict(from_attributes=True)


class LearnerOverviewResponse(BaseModel):
    """Comprehensive learner profile and learning progression summary."""

    learner_id: str
    first_name: str
    last_name: str
    experience_level: str
    total_attempts: int = Field(ge=0)
    completed_attempts: int = Field(ge=0)
    in_progress_attempts: int = Field(ge=0)
    average_score: Optional[float] = None
    skills_practiced_count: int = Field(ge=0)
    skills_needing_attention: List[LearnerSkillOverviewSchema] = Field(default_factory=list)
    recent_activities: List[LearnerRecentActivitySchema] = Field(default_factory=list)
    recommended_preview: List[LearnerRecommendedPreviewSchema] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)

