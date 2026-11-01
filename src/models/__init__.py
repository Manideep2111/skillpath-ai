"""Model exports for SkillPath AI relational schema."""

from src.db.database import Base
from src.models.entities import (
    Learner,
    Course,
    Skill,
    SkillPrerequisite,
    ContentItem,
    ContentSkill,
    Attempt,
    AssessmentResult,
    LearningPath,
    LearningPathItem,
    Recommendation,
    MasterySnapshot,
    RecommendationOutcome,
    AuditEvent,
    DataIssue,
)

__all__ = [
    "Base",
    "Learner",
    "Course",
    "Skill",
    "SkillPrerequisite",
    "ContentItem",
    "ContentSkill",
    "Attempt",
    "AssessmentResult",
    "LearningPath",
    "LearningPathItem",
    "Recommendation",
    "MasterySnapshot",
    "RecommendationOutcome",
    "AuditEvent",
    "DataIssue",
]