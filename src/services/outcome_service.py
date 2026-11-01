"""Outcome lifecycle tracking service for SkillPath AI.

Implements state transitions for recommendations:
RECOMMENDED -> STARTED -> COMPLETED -> IMPROVED / NO_IMPROVEMENT
                       -> ABANDONED

Computes point-in-time pre- and post-interaction mastery deltas
using 28-digit Decimal arithmetic, strictly excluding future evidence.
"""

from datetime import datetime
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Optional, Tuple
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.entities import (
    AssessmentResult,
    Attempt,
    Recommendation,
    RecommendationOutcome,
)
from src.services.mastery_service import MasteryService


class OutcomeError(Exception):
    """Base exception for outcome tracking errors."""
    pass


class RecommendationNotFoundError(OutcomeError):
    """Raised when a recommendation ID cannot be found."""
    pass


class InvalidStateTransitionError(OutcomeError):
    """Raised when an illegal lifecycle transition is attempted."""
    pass


class InvalidInteractionAttemptError(OutcomeError):
    """Raised when an attempt does not match the recommendation or is temporally invalid."""
    pass


class OutcomeTrackingService:
    """Service managing recommendation outcome lifecycles and mastery delta calculation."""

    TERMINAL_STATES = frozenset({"ABANDONED", "IMPROVED", "NO_IMPROVEMENT"})

    def __init__(self, db: Session, mastery_service: Optional[MasteryService] = None):
        self.db = db
        self.mastery_service = mastery_service or MasteryService(db)

    def get_outcome(self, recommendation_id: str) -> RecommendationOutcome:
        """Fetch the RecommendationOutcome for a recommendation."""
        outcome = self.db.scalars(
            select(RecommendationOutcome).where(
                RecommendationOutcome.recommendation_id == recommendation_id
            )
        ).first()
        if outcome is None:
            raise RecommendationNotFoundError(
                f"No recommendation outcome found for recommendation '{recommendation_id}'."
            )
        return outcome

    def record_interaction_start(
        self,
        recommendation_id: str,
        attempt_id: str,
        started_at: Optional[datetime] = None,
    ) -> RecommendationOutcome:
        """Transition outcome from RECOMMENDED to STARTED and link attempt."""
        outcome = self.get_outcome(recommendation_id)

        if outcome.outcome_status in self.TERMINAL_STATES:
            raise InvalidStateTransitionError(
                f"Cannot start recommendation in terminal state '{outcome.outcome_status}'."
            )

        if outcome.outcome_status != "RECOMMENDED":
            raise InvalidStateTransitionError(
                f"Cannot transition from '{outcome.outcome_status}' to 'STARTED'. "
                f"Expected status 'RECOMMENDED'."
            )

        rec = self.db.get(Recommendation, recommendation_id)
        if rec is None:
            raise RecommendationNotFoundError(f"Recommendation '{recommendation_id}' does not exist.")

        attempt = self.db.get(Attempt, attempt_id)
        if attempt is None:
            raise InvalidInteractionAttemptError(f"Attempt '{attempt_id}' does not exist.")

        # Validate learner match
        if attempt.learner_id != rec.learner_id:
            raise InvalidInteractionAttemptError(
                f"Attempt '{attempt_id}' learner '{attempt.learner_id}' does not match "
                f"recommendation learner '{rec.learner_id}'."
            )

        # Validate content match
        if attempt.content_id != rec.content_id:
            raise InvalidInteractionAttemptError(
                f"Attempt '{attempt_id}' content '{attempt.content_id}' does not match "
                f"recommended content '{rec.content_id}'."
            )

        # Temporal safety: attempt must start on or after recommendation decision
        transition_time = started_at or attempt.started_at
        if attempt.started_at < rec.decision_timestamp:
            raise InvalidInteractionAttemptError(
                f"Attempt started at {attempt.started_at} which precedes recommendation "
                f"decision timestamp {rec.decision_timestamp}. Temporal inversion rejected."
            )

        outcome.outcome_status = "STARTED"
        outcome.interaction_attempt_id = attempt_id
        outcome.recorded_at = transition_time
        self.db.flush()
        return outcome

    def record_interaction_abandonment(
        self,
        recommendation_id: str,
        abandoned_at: Optional[datetime] = None,
    ) -> RecommendationOutcome:
        """Transition outcome from STARTED to ABANDONED (terminal state)."""
        outcome = self.get_outcome(recommendation_id)

        if outcome.outcome_status in self.TERMINAL_STATES:
            raise InvalidStateTransitionError(
                f"Cannot abandon recommendation in terminal state '{outcome.outcome_status}'."
            )

        if outcome.outcome_status != "STARTED":
            raise InvalidStateTransitionError(
                f"Cannot transition from '{outcome.outcome_status}' to 'ABANDONED'. "
                f"Expected status 'STARTED'."
            )

        transition_time = abandoned_at or datetime.utcnow()
        outcome.outcome_status = "ABANDONED"
        outcome.recorded_at = transition_time
        self.db.flush()
        return outcome

    def record_interaction_completion(
        self,
        recommendation_id: str,
        completed_at: Optional[datetime] = None,
    ) -> RecommendationOutcome:
        """Transition outcome from STARTED to COMPLETED."""
        outcome = self.get_outcome(recommendation_id)

        if outcome.outcome_status in self.TERMINAL_STATES:
            raise InvalidStateTransitionError(
                f"Cannot complete recommendation in terminal state '{outcome.outcome_status}'."
            )

        if outcome.outcome_status != "STARTED":
            raise InvalidStateTransitionError(
                f"Cannot transition from '{outcome.outcome_status}' to 'COMPLETED'. "
                f"Expected status 'STARTED'."
            )

        attempt = self.db.get(Attempt, outcome.interaction_attempt_id)
        if attempt is None:
            raise InvalidInteractionAttemptError("No attempt linked to started recommendation.")

        transition_time = completed_at or attempt.completed_at or datetime.utcnow()
        outcome.outcome_status = "COMPLETED"
        outcome.recorded_at = transition_time
        self.db.flush()
        return outcome

    def evaluate_outcome(
        self,
        recommendation_id: str,
    ) -> Tuple[RecommendationOutcome, Optional[Decimal], Optional[Decimal], Optional[Decimal]]:
        """Evaluate mastery delta and transition from COMPLETED to IMPROVED or NO_IMPROVEMENT.

        Returns:
            Tuple of (outcome, pre_mastery, post_mastery, mastery_delta)
        """
        outcome = self.get_outcome(recommendation_id)

        if outcome.outcome_status in self.TERMINAL_STATES:
            raise InvalidStateTransitionError(
                f"Cannot evaluate recommendation in terminal state '{outcome.outcome_status}'."
            )

        # If currently STARTED, auto-complete if attempt is completed
        if outcome.outcome_status == "STARTED":
            self.record_interaction_completion(recommendation_id)
            outcome = self.get_outcome(recommendation_id)

        if outcome.outcome_status != "COMPLETED":
            raise InvalidStateTransitionError(
                f"Cannot evaluate recommendation from status '{outcome.outcome_status}'. "
                f"Expected status 'COMPLETED'."
            )

        rec = self.db.get(Recommendation, recommendation_id)
        if rec is None:
            raise RecommendationNotFoundError(f"Recommendation '{recommendation_id}' does not exist.")

        attempt = self.db.get(Attempt, outcome.interaction_attempt_id)
        if attempt is None:
            raise InvalidInteractionAttemptError("No attempt linked to completed recommendation.")

        # Find assessment result for the attempt
        assessment = self.db.scalars(
            select(AssessmentResult).where(AssessmentResult.attempt_id == attempt.attempt_id)
        ).first()

        if assessment is None or assessment.graded_at is None:
            raise InvalidInteractionAttemptError(
                f"Cannot evaluate outcome: Attempt '{attempt.attempt_id}' has no graded assessment result."
            )

        # Temporal safety check: assessment must be graded on or after recommendation decision
        if assessment.graded_at < rec.decision_timestamp:
            raise InvalidInteractionAttemptError(
                f"Assessment graded at {assessment.graded_at} precedes recommendation "
                f"decision timestamp {rec.decision_timestamp}."
            )

        # Calculate pre-mastery strictly at recommendation decision_timestamp
        pre_mastery, _, _, _, _ = self.mastery_service.compute_mastery(
            learner_id=rec.learner_id,
            skill_id=rec.target_skill_id,
            cutoff_timestamp=rec.decision_timestamp,
        )

        # Calculate post-mastery strictly at assessment.graded_at
        post_mastery, _, _, _, _ = self.mastery_service.compute_mastery(
            learner_id=rec.learner_id,
            skill_id=rec.target_skill_id,
            cutoff_timestamp=assessment.graded_at,
        )

        # Mastery Delta Calculation with Explicit Unknown vs Zero Policy:
        # 1. If pre_mastery is measured (Decimal) and post_mastery is measured (Decimal):
        #    delta = post_mastery - pre_mastery
        # 2. If pre_mastery is UNKNOWN (None) and post_mastery is measured (Decimal):
        #    Learner progressed from unmeasured to measured evidence.
        #    delta = post_mastery (gain from initial acquisition baseline).
        # 3. If post_mastery is UNKNOWN (None):
        #    delta = Decimal("0.0000")
        if pre_mastery is not None and post_mastery is not None:
            delta = (post_mastery - pre_mastery).quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN)
        elif pre_mastery is None and post_mastery is not None:
            delta = post_mastery.quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN)
        else:
            delta = Decimal("0.0000")

        status = "IMPROVED" if delta > Decimal("0.0000") else "NO_IMPROVEMENT"

        outcome.outcome_status = status
        outcome.mastery_delta = float(delta)
        outcome.recorded_at = assessment.graded_at
        self.db.flush()

        return outcome, pre_mastery, post_mastery, delta
