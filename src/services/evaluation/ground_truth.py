"""Ground-truth relevance extraction from post-cutoff learner engagement and outcomes.

Implements the authoritative four-tier relevance mapping:
- Grade 0: Unobserved / Non-relevant (no completed interaction in outcome window)
- Grade 1: Engaged (completed content attempt in outcome window)
- Grade 2: Proficient (completed attempt with normalized assessment score >= 0.70)
- Grade 3: Target Gap Closed (prior mastery at cutoff T was < 0.70, assessment passed, and mastery improved)

CRITICAL: Pre-cutoff skill gaps are calculated exclusively from information available at cutoff T.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Dict, Optional, Set
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.entities import AssessmentResult, Attempt, ContentSkill
from src.services.evaluation.temporal_split import TemporalWindow
from src.services.mastery_service import MasteryService


@dataclass
class LearnerGroundTruth:
    """Empirical ground-truth relevance labels for a learner within an outcome window."""

    learner_id: str
    cutoff: datetime
    actual_horizon: datetime
    relevant_items: Set[str] = field(default_factory=set)
    relevance_grades: Dict[str, int] = field(default_factory=dict)
    observed_attempt_count: int = 0
    observed_assessment_count: int = 0

    @property
    def has_relevant_outcomes(self) -> bool:
        """True if the learner had at least one relevant outcome in the window."""
        return len(self.relevant_items) > 0


class GroundTruthExtractor:
    """Extracts empirical learning outcomes from post-cutoff database events."""

    def __init__(self, session: Session, mastery_service: Optional[MasteryService] = None) -> None:
        self.session = session
        self.mastery_service = mastery_service or MasteryService(session)

    def extract_for_learner(
        self,
        learner_id: str,
        window: TemporalWindow,
    ) -> LearnerGroundTruth:
        """Extract ground-truth relevance for learner in the half-open interval (cutoff, horizon].

        Pre-cutoff mastery gaps are computed strictly as of window.cutoff.
        """
        gt = LearnerGroundTruth(
            learner_id=learner_id,
            cutoff=window.cutoff,
            actual_horizon=window.actual_horizon,
        )

        # 1. Fetch completed attempts in outcome window: cutoff < completed_at <= actual_horizon
        attempts = self.session.scalars(
            select(Attempt)
            .where(
                Attempt.learner_id == learner_id,
                Attempt.status == "COMPLETED",
                Attempt.completed_at > window.cutoff,
                Attempt.completed_at <= window.actual_horizon,
                Attempt.started_at <= Attempt.completed_at,
            )
            .order_by(Attempt.completed_at)
        ).all()

        gt.observed_attempt_count = len(attempts)
        if not attempts:
            return gt

        attempt_ids = [a.attempt_id for a in attempts]
        content_by_attempt = {a.attempt_id: a.content_id for a in attempts}

        # Baseline assignment: Grade 1 (Engaged) for all completed content items
        for att in attempts:
            gt.relevant_items.add(att.content_id)
            gt.relevance_grades[att.content_id] = max(
                gt.relevance_grades.get(att.content_id, 0),
                1,
            )

        # 2. Fetch assessment results in outcome window: cutoff < graded_at <= actual_horizon
        results = self.session.scalars(
            select(AssessmentResult)
            .where(
                AssessmentResult.attempt_id.in_(attempt_ids),
                AssessmentResult.graded_at > window.cutoff,
                AssessmentResult.graded_at <= window.actual_horizon,
            )
        ).all()

        gt.observed_assessment_count = len(results)

        # Assess Grade 2 (Proficient) and Grade 3 (Target Gap Closed)
        for res in results:
            content_id = content_by_attempt.get(res.attempt_id)
            if not content_id:
                continue

            is_passed = res.is_passed or (res.normalized_score and res.normalized_score >= Decimal("0.70"))
            if not is_passed:
                continue

            # Qualifies for at least Grade 2 (Proficient)
            current_grade = max(gt.relevance_grades.get(content_id, 0), 2)
            gt.relevance_grades[content_id] = current_grade

            # Check if qualifies for Grade 3 (Target Gap Closed)
            # Find mapped skills with positive relevance
            mapped_skills = self.session.scalars(
                select(ContentSkill.skill_id)
                .where(
                    ContentSkill.content_id == content_id,
                    ContentSkill.relevance_weight > 0,
                )
            ).all()

            for skill_id in mapped_skills:
                # Prior mastery calculated EXCLUSIVELY as of cutoff T
                pre_mastery, _, _, _, _ = self.mastery_service.compute_mastery(
                    learner_id=learner_id,
                    skill_id=skill_id,
                    cutoff_timestamp=window.cutoff,
                )

                # Prior gap: unknown (None) or < 0.70
                had_prior_gap = (pre_mastery is None) or (pre_mastery < Decimal("0.70"))

                if had_prior_gap:
                    # Post mastery evaluated after the assessment
                    post_mastery, _, _, _, _ = self.mastery_service.compute_mastery(
                        learner_id=learner_id,
                        skill_id=skill_id,
                        cutoff_timestamp=res.graded_at,
                    )
                    # Improvement condition: pre was None and post is measured > 0, or post > pre
                    improved = False
                    if pre_mastery is None:
                        improved = post_mastery is not None and post_mastery > Decimal("0.00")
                    elif post_mastery is not None and post_mastery > pre_mastery:
                        improved = True

                    if improved:
                        gt.relevance_grades[content_id] = 3
                        break  # Highest possible grade reached

        return gt
