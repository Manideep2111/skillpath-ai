"""SQLAlchemy 2.0 ORM entity definitions for SkillPath AI.

Implements all 10 core entities and 5 supporting entities with check constraints,
foreign keys, indexes, score integrity ratios, and lineage audit fields.
"""

from datetime import datetime
from typing import Optional, List
from sqlalchemy import (
    String,
    Boolean,
    Integer,
    Numeric,
    DateTime,
    Text,
    ForeignKey,
    CheckConstraint,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.database import Base


# ============================================================================
# CORE ENTITY 1: Learner
# ============================================================================
class Learner(Base):
    __tablename__ = "learners"

    learner_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    first_name: Mapped[str] = mapped_column(String(64), nullable=False)
    last_name: Mapped[str] = mapped_column(String(64), nullable=False)
    email: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    experience_level: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "experience_level IN ('BEGINNER', 'INTERMEDIATE', 'ADVANCED')",
            name="chk_learner_experience_level",
        ),
        Index("idx_learners_active", "is_active"),
    )

    # Relationships
    attempts: Mapped[List["Attempt"]] = relationship("Attempt", back_populates="learner")
    learning_paths: Mapped[List["LearningPath"]] = relationship("LearningPath", back_populates="learner")
    mastery_snapshots: Mapped[List["MasterySnapshot"]] = relationship("MasterySnapshot", back_populates="learner")
    recommendations: Mapped[List["Recommendation"]] = relationship("Recommendation", back_populates="learner")


# ============================================================================
# CORE ENTITY 2: Course
# ============================================================================
class Course(Base):
    __tablename__ = "courses"

    course_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    difficulty: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "difficulty IN ('BEGINNER', 'INTERMEDIATE', 'ADVANCED')",
            name="chk_course_difficulty",
        ),
    )

    # Relationships
    content_items: Mapped[List["ContentItem"]] = relationship("ContentItem", back_populates="course")


# ============================================================================
# CORE ENTITY 3: Skill
# ============================================================================
class Skill(Base):
    __tablename__ = "skills"

    skill_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    domain: Mapped[str] = mapped_column(String(64), nullable=False)
    difficulty_level: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "difficulty_level >= 0.0 AND difficulty_level <= 1.0",
            name="chk_skill_difficulty_range",
        ),
        Index("idx_skills_domain", "domain"),
    )

    # Relationships
    prerequisites: Mapped[List["SkillPrerequisite"]] = relationship(
        "SkillPrerequisite",
        foreign_keys="SkillPrerequisite.skill_id",
        back_populates="skill",
    )
    required_for: Mapped[List["SkillPrerequisite"]] = relationship(
        "SkillPrerequisite",
        foreign_keys="SkillPrerequisite.prerequisite_skill_id",
        back_populates="prerequisite_skill",
    )
    content_skills: Mapped[List["ContentSkill"]] = relationship(
    "ContentSkill", back_populates="skill", passive_deletes="all"
)
    mastery_snapshots: Mapped[List["MasterySnapshot"]] = relationship("MasterySnapshot", back_populates="skill")


# ============================================================================
# CORE ENTITY 4: SkillPrerequisite
# ============================================================================
class SkillPrerequisite(Base):
    __tablename__ = "skill_prerequisites"

    skill_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("skills.skill_id", ondelete="RESTRICT"), primary_key=True
    )
    prerequisite_skill_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("skills.skill_id", ondelete="RESTRICT"), primary_key=True
    )
    minimum_mastery: Mapped[float] = mapped_column(Numeric(3, 2), default=0.70, nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "minimum_mastery >= 0.0 AND minimum_mastery <= 1.0",
            name="chk_prereq_min_mastery",
        ),
        CheckConstraint("skill_id <> prerequisite_skill_id", name="chk_prereq_no_self"),
        Index("idx_prereq_parent", "prerequisite_skill_id"),
    )

    # Relationships
    skill: Mapped["Skill"] = relationship(
        "Skill", foreign_keys=[skill_id], back_populates="prerequisites"
    )
    prerequisite_skill: Mapped["Skill"] = relationship(
        "Skill", foreign_keys=[prerequisite_skill_id], back_populates="required_for"
    )


# ============================================================================
# CORE ENTITY 5: ContentItem
# ============================================================================
class ContentItem(Base):
    __tablename__ = "content_items"

    content_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    course_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("courses.course_id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(20), nullable=False)
    difficulty: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "content_type IN ('VIDEO', 'READING', 'QUIZ', 'LAB', 'PROJECT')",
            name="chk_content_type",
        ),
        CheckConstraint("difficulty >= 0.0 AND difficulty <= 1.0", name="chk_content_difficulty"),
        CheckConstraint("duration_minutes > 0", name="chk_content_duration_positive"),
        Index("idx_content_course", "course_id"),
    )

    # Relationships
    course: Mapped["Course"] = relationship("Course", back_populates="content_items")
    content_skills: Mapped[List["ContentSkill"]] = relationship(
        "ContentSkill", back_populates="content_item", cascade="all, delete-orphan"
    )
    attempts: Mapped[List["Attempt"]] = relationship("Attempt", back_populates="content_item")
    path_items: Mapped[List["LearningPathItem"]] = relationship(
        "LearningPathItem", back_populates="content_item"
    )
    recommendations: Mapped[List["Recommendation"]] = relationship(
        "Recommendation", back_populates="content_item"
    )


# ============================================================================
# CORE ENTITY 6: ContentSkill
# ============================================================================
class ContentSkill(Base):
    __tablename__ = "content_skills"

    content_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("content_items.content_id", ondelete="CASCADE"), primary_key=True
    )
    skill_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("skills.skill_id", ondelete="RESTRICT"), primary_key=True
    )
    relevance_weight: Mapped[float] = mapped_column(Numeric(3, 2), default=1.00, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "relevance_weight >= 0.0 AND relevance_weight <= 1.0",
            name="chk_cs_relevance_weight",
        ),
        Index("idx_cs_skill", "skill_id"),
    )

    # Relationships
    content_item: Mapped["ContentItem"] = relationship("ContentItem", back_populates="content_skills")
    skill: Mapped["Skill"] = relationship("Skill", back_populates="content_skills")


# ============================================================================
# CORE ENTITY 7: Attempt
# ============================================================================
class Attempt(Base):
    __tablename__ = "attempts"

    attempt_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    learner_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("learners.learner_id", ondelete="RESTRICT"), nullable=False
    )
    content_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("content_items.content_id", ondelete="RESTRICT"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    time_spent_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    __table_args__ = (
        CheckConstraint("attempt_number >= 1", name="chk_attempt_number_positive"),
        CheckConstraint(
            "time_spent_seconds IS NULL OR time_spent_seconds >= 0",
            name="chk_time_spent_nonneg",
        ),
        CheckConstraint(
            "status IN ('IN_PROGRESS', 'COMPLETED', 'ABANDONED')",
            name="chk_attempt_status",
        ),
        UniqueConstraint("learner_id", "content_id", "attempt_number", name="uq_learner_content_attempt"),
        Index("idx_attempts_learner", "learner_id", "started_at"),
        Index("idx_attempts_content", "content_id"),
    )

    # Relationships
    learner: Mapped["Learner"] = relationship("Learner", back_populates="attempts")
    content_item: Mapped["ContentItem"] = relationship("ContentItem", back_populates="attempts")
    assessment_result: Mapped[Optional["AssessmentResult"]] = relationship(
        "AssessmentResult", back_populates="attempt", uselist=False, cascade="all, delete-orphan"
    )


# ============================================================================
# CORE ENTITY 8: AssessmentResult (Strict Bounded Scores & Ratio Integrity)
# ============================================================================
class AssessmentResult(Base):
    __tablename__ = "assessment_results"

    result_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    attempt_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("attempts.attempt_id", ondelete="CASCADE"), unique=True, nullable=False
    )
    raw_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    max_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    normalized_score: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    is_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    graded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint("raw_score >= 0.0", name="chk_raw_score_nonneg"),
        CheckConstraint("max_score > 0.0", name="chk_max_score_positive"),
        CheckConstraint("raw_score <= max_score", name="chk_raw_le_max"),
        CheckConstraint(
            "normalized_score >= 0.0 AND normalized_score <= 1.0",
            name="chk_normalized_score_range",
        ),
        CheckConstraint(
            "abs(normalized_score - (1.0 * raw_score / max_score)) <= 0.0001",
            name="chk_score_ratio_integrity",
        ),
        Index("idx_assessment_graded", "graded_at"),
    )

    # Relationships
    attempt: Mapped["Attempt"] = relationship("Attempt", back_populates="assessment_result")


# ============================================================================
# CORE ENTITY 9: LearningPath
# ============================================================================
class LearningPath(Base):
    __tablename__ = "learning_paths"

    path_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    learner_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("learners.learner_id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    target_role: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT', 'ACTIVE', 'COMPLETED', 'ARCHIVED')",
            name="chk_path_status",
        ),
        Index("idx_lp_learner", "learner_id"),
    )

    # Relationships
    learner: Mapped["Learner"] = relationship("Learner", back_populates="learning_paths")
    path_items: Mapped[List["LearningPathItem"]] = relationship(
        "LearningPathItem", back_populates="learning_path", cascade="all, delete-orphan"
    )


# ============================================================================
# SUPPORTING ENTITY 1: LearningPathItem
# ============================================================================
class LearningPathItem(Base):
    __tablename__ = "learning_path_items"

    path_item_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    path_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("learning_paths.path_id", ondelete="CASCADE"), nullable=False
    )
    content_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("content_items.content_id", ondelete="RESTRICT"), nullable=False
    )
    sequence_order: Mapped[int] = mapped_column(Integer, nullable=False)
    is_mandatory: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint("sequence_order >= 1", name="chk_seq_order_positive"),
        CheckConstraint(
            "status IN ('PENDING', 'IN_PROGRESS', 'COMPLETED', 'SKIPPED')",
            name="chk_path_item_status",
        ),
        UniqueConstraint("path_id", "sequence_order", name="uq_path_sequence"),
        Index("idx_lpi_path", "path_id"),
    )

    # Relationships
    learning_path: Mapped["LearningPath"] = relationship("LearningPath", back_populates="path_items")
    content_item: Mapped["ContentItem"] = relationship("ContentItem", back_populates="path_items")


# ============================================================================
# CORE ENTITY 10: Recommendation
# ============================================================================
class Recommendation(Base):
    __tablename__ = "recommendations"

    recommendation_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    learner_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("learners.learner_id", ondelete="RESTRICT"), nullable=False
    )
    content_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("content_items.content_id", ondelete="RESTRICT"), nullable=False
    )
    target_skill_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("skills.skill_id", ondelete="RESTRICT"), nullable=False
    )
    decision_timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    rank_position: Mapped[int] = mapped_column(Integer, nullable=False)
    recommendation_score: Mapped[float] = mapped_column(Numeric(7, 6), nullable=False)
    primary_reason_code: Mapped[str] = mapped_column(String(32), nullable=False)
    score_components_json: Mapped[str] = mapped_column(Text, nullable=False)
    rejection_audit_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    algorithm_version: Mapped[str] = mapped_column(String(16), nullable=False)

    __table_args__ = (
        CheckConstraint("rank_position >= 1", name="chk_rec_rank_positive"),
        CheckConstraint(
            "recommendation_score >= 0.0 AND recommendation_score <= 1.0",
            name="chk_rec_score_bounds",
        ),
        Index("idx_rec_learner", "learner_id", "decision_timestamp"),
    )

    # Relationships
    learner: Mapped["Learner"] = relationship("Learner", back_populates="recommendations")
    content_item: Mapped["ContentItem"] = relationship("ContentItem", back_populates="recommendations")
    target_skill: Mapped["Skill"] = relationship("Skill")
    outcome: Mapped[Optional["RecommendationOutcome"]] = relationship(
        "RecommendationOutcome", back_populates="recommendation", uselist=False
    )


# ============================================================================
# SUPPORTING ENTITY 2: MasterySnapshot (With Lineage Audit Metadata)
# ============================================================================
class MasterySnapshot(Base):
    __tablename__ = "mastery_snapshots"

    snapshot_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    learner_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("learners.learner_id", ondelete="RESTRICT"), nullable=False
    )
    skill_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("skills.skill_id", ondelete="RESTRICT"), nullable=False
    )
    mastery_level: Mapped[Optional[float]] = mapped_column(Numeric(5, 4), nullable=True)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    cutoff_timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    max_evidence_graded_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    evidence_result_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(16), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint("evidence_count >= 0", name="chk_evidence_count_nonneg"),
        CheckConstraint(
            "confidence_score >= 0.0 AND confidence_score <= 1.0",
            name="chk_confidence_score_range",
        ),
        CheckConstraint(
            "mastery_level IS NULL OR (mastery_level >= 0.0 AND mastery_level <= 1.0)",
            name="chk_mastery_level_range",
        ),
        UniqueConstraint(
            "learner_id", "skill_id", "cutoff_timestamp", "algorithm_version",
            name="uq_learner_skill_cutoff",
        ),
        Index("idx_mastery_lookup", "learner_id", "skill_id", "cutoff_timestamp"),
        Index("idx_mastery_leakage_audit", "cutoff_timestamp", "max_evidence_graded_at"),
    )

    # Derived state per SRS Section G/I
    @property
    def is_unknown(self) -> bool:
        """Derived property: True if no assessment evidence was available at cutoff."""
        return self.mastery_level is None

    # Relationships
    learner: Mapped["Learner"] = relationship("Learner", back_populates="mastery_snapshots")
    skill: Mapped["Skill"] = relationship("Skill", back_populates="mastery_snapshots")


# ============================================================================
# SUPPORTING ENTITY 3: RecommendationOutcome
# ============================================================================
class RecommendationOutcome(Base):
    __tablename__ = "recommendation_outcomes"

    outcome_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    recommendation_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("recommendations.recommendation_id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    outcome_status: Mapped[str] = mapped_column(String(32), nullable=False)
    interaction_attempt_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("attempts.attempt_id", ondelete="SET NULL"), nullable=True
    )
    mastery_delta: Mapped[Optional[float]] = mapped_column(Numeric(5, 4), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "outcome_status IN ('RECOMMENDED', 'STARTED', 'COMPLETED', 'ABANDONED', 'IMPROVED', 'NO_IMPROVEMENT')",
            name="chk_outcome_status_valid",
        ),
        Index("idx_ro_status", "outcome_status"),
    )

    # Relationships
    recommendation: Mapped["Recommendation"] = relationship("Recommendation", back_populates="outcome")
    attempt: Mapped[Optional["Attempt"]] = relationship("Attempt")


# ============================================================================
# SUPPORTING ENTITY 4: AuditEvent
# ============================================================================
class AuditEvent(Base):
    __tablename__ = "audit_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_name: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    details_json: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        Index("idx_audit_time", "occurred_at"),
    )


# ============================================================================
# SUPPORTING ENTITY 5: DataIssue (OPERATIONAL LOG ONLY - NO GROUND TRUTH)
# ============================================================================
class DataIssue(Base):
    __tablename__ = "data_issues"

    issue_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    anomaly_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    quarantine_status: Mapped[str] = mapped_column(String(16), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')",
            name="chk_issue_severity",
        ),
        CheckConstraint(
            "quarantine_status IN ('FLAGGED', 'QUARANTINED', 'RESOLVED', 'IGNORED')",
            name="chk_issue_quarantine_status",
        ),
        Index("idx_issues_type", "anomaly_type", "quarantine_status"),
    )