from __future__ import annotations

import json
import threading
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import (
    Context,
    Decimal,
    ROUND_HALF_EVEN,
    localcontext,
)
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.models.entities import (
    AssessmentResult,
    Attempt,
    ContentItem,
    ContentSkill,
    Learner,
    LearningPath,
    LearningPathItem,
    Recommendation,
    RecommendationOutcome,
    Skill,
    SkillPrerequisite,
)
from src.services.generator.id_factory import (
    format_outcome_id,
    format_recommendation_id,
)
from src.services.mastery_service import MasteryService
from src.services.prerequisite_eligibility import (
    PrerequisiteEligibilityHelper,
)


REC_CONTEXT = Context(
    prec=28,
    rounding=ROUND_HALF_EVEN,
)

ZERO = Decimal("0.0000")
ONE = Decimal("1.0000")
UNKNOWN_GAP = Decimal("0.8500")
TARGET_MASTERY = Decimal("0.7000")
SCORE_QUANTUM = Decimal("0.000001")


@dataclass(frozen=True)
class ScoreComponents:
    gap: Decimal
    difficulty_suitability: Decimal
    path_alignment: Decimal
    practice_urgency: Decimal
    total: Decimal


@dataclass(frozen=True)
class RecommendedItem:
    content_id: str
    title: str
    score: Decimal
    score_components: ScoreComponents
    target_skill_id: str
    reason_codes: tuple[str, ...]
    primary_reason_code: str
    recommendation_id: Optional[str] = None


class RecommendationIdAllocator:
    """Concurrency-safe sequence allocator for recommendation identifiers."""

    _lock = threading.Lock()

    @classmethod
    def allocate_ids(cls, session: Session, count: int, year: int = 2026) -> list[str]:
        if count <= 0:
            return []
        with cls._lock:
            prefix = f"REC-{year:04d}-%"
            max_id = session.scalar(
                select(func.max(Recommendation.recommendation_id)).where(
                    Recommendation.recommendation_id.like(prefix)
                )
            )
            if max_id:
                current_max = int(max_id.split("-")[-1])
            else:
                current_max = 0

            return [
                format_recommendation_id(current_max + i, year=year)
                for i in range(1, count + 1)
            ]


@dataclass(frozen=True)
class RejectionSummary:
    inactive_content: int = 0
    unpublished_content: int = 0
    recent_completions: int = 0
    prerequisite_blocked: int = 0
    no_relevant_skill_gap: int = 0
    future_content: int = 0
    skill_already_mastered: int = 0


@dataclass(frozen=True)
class RecommendationBatch:
    learner_id: str
    cutoff_timestamp: datetime
    items: tuple[RecommendedItem, ...]
    rejection_summary: RejectionSummary


class RecommendationService:
    ALGORITHM_VERSION = "v1.1.0"
    RECENT_COMPLETION_DAYS = 30
    PRACTICE_URGENCY_DAYS = Decimal("60.0")

    TARGET_MASTERY = Decimal("0.7000")
    UNKNOWN_SKILL_GAP = Decimal("0.8500")
    UNKNOWN_DIFFICULTY_PRIOR = {
        "BEGINNER": Decimal("0.1500"),
        "INTERMEDIATE": Decimal("0.4000"),
        "ADVANCED": Decimal("0.7000"),
    }

    GAP_WEIGHT = Decimal("0.40")
    DIFFICULTY_WEIGHT = Decimal("0.25")
    PATH_WEIGHT = Decimal("0.20")
    URGENCY_WEIGHT = Decimal("0.15")

    def __init__(
        self,
        db: Session,
        mastery_service: Optional[MasteryService] = None,
    ):
        self.db = db
        self.mastery_service = mastery_service or MasteryService(db)

    @staticmethod
    def _as_decimal(value) -> Decimal:
        return Decimal(str(value))

    @staticmethod
    def _validate_cutoff(cutoff_timestamp: datetime) -> None:
        if not isinstance(cutoff_timestamp, datetime):
            raise ValueError("cutoff_timestamp must be a datetime.")

        if cutoff_timestamp.tzinfo is not None:
            raise ValueError(
                "cutoff_timestamp must be timezone-naive."
            )

    def _get_historical_mastery(
        self,
        learner_id: str,
        cutoff_timestamp: datetime,
    ) -> dict[str, Optional[Decimal]]:
        """
        Compute mastery at the requested cutoff without creating snapshots.

        Only valid, completed attempts with assessment results graded by
        the cutoff contribute to mastery.
        """
        active_skill_ids = self.db.scalars(
            select(Skill.skill_id).where(
                Skill.is_active.is_(True)
            )
        ).all()

        mastery_map: dict[str, Optional[Decimal]] = {
            skill_id: None for skill_id in active_skill_ids
        }

        rows = self.db.execute(
            select(
                Skill.skill_id,
                AssessmentResult.result_id,
                AssessmentResult.normalized_score,
                ContentSkill.relevance_weight,
                AssessmentResult.graded_at,
            )
            .select_from(AssessmentResult)
            .join(
                Attempt,
                Attempt.attempt_id == AssessmentResult.attempt_id,
            )
            .join(
                ContentSkill,
                ContentSkill.content_id == Attempt.content_id,
            )
            .join(
                Skill,
                Skill.skill_id == ContentSkill.skill_id,
            )
            .where(
                Attempt.learner_id == learner_id,
                Attempt.status == "COMPLETED",
                Attempt.started_at <= Attempt.completed_at,
                Attempt.completed_at <= AssessmentResult.graded_at,
                AssessmentResult.graded_at <= cutoff_timestamp,
                ContentSkill.relevance_weight > 0,
                Skill.is_active.is_(True),
            )
            .order_by(
                Skill.skill_id,
                AssessmentResult.graded_at,
                AssessmentResult.result_id,
            )
        ).all()

        evidence_by_skill = defaultdict(list)

        for (
            skill_id,
            result_id,
            normalized_score,
            relevance_weight,
            graded_at,
        ) in rows:
            evidence_by_skill[skill_id].append(
                (
                    result_id,
                    self._as_decimal(normalized_score),
                    self._as_decimal(relevance_weight),
                    graded_at,
                )
            )

        for skill_id, evidence in evidence_by_skill.items():
            mastery, _, _, _, _ = (
                self.mastery_service._aggregate_evidence(
                    evidence,
                    cutoff_timestamp,
                )
            )
            mastery_map[skill_id] = mastery

        return mastery_map

    def _get_evidence_counts(
        self,
        learner_id: str,
        cutoff_timestamp: datetime,
    ) -> dict[str, int]:
        rows = self.db.execute(
            select(
                ContentSkill.skill_id,
                AssessmentResult.result_id,
            )
            .select_from(AssessmentResult)
            .join(
                Attempt,
                Attempt.attempt_id == AssessmentResult.attempt_id,
            )
            .join(
                ContentSkill,
                ContentSkill.content_id == Attempt.content_id,
            )
            .join(
                Skill,
                Skill.skill_id == ContentSkill.skill_id,
            )
            .where(
                Attempt.learner_id == learner_id,
                Attempt.status == "COMPLETED",
                Attempt.started_at <= Attempt.completed_at,
                Attempt.completed_at <= AssessmentResult.graded_at,
                AssessmentResult.graded_at <= cutoff_timestamp,
                ContentSkill.relevance_weight > 0,
                Skill.is_active.is_(True),
            )
        ).all()

        counts: dict[str, int] = defaultdict(int)

        for skill_id, _ in rows:
            counts[skill_id] += 1

        return dict(counts)

    def _get_prerequisites(
        self,
    ) -> dict[str, list[tuple[str, str, Decimal, bool]]]:
        """
        Return target_skill_id -> prerequisite definitions.

        Each prerequisite tuple is:
        (prerequisite_skill_id, prerequisite_name,
         minimum_mastery, is_required).
        """
        rows = self.db.execute(
            select(
                SkillPrerequisite.skill_id,
                SkillPrerequisite.prerequisite_skill_id,
                Skill.name,
                SkillPrerequisite.minimum_mastery,
                SkillPrerequisite.is_required,
            )
            .join(
                Skill,
                Skill.skill_id
                == SkillPrerequisite.prerequisite_skill_id,
            )
        ).all()

        result = defaultdict(list)

        for (
            target_skill_id,
            prerequisite_skill_id,
            prerequisite_name,
            minimum_mastery,
            is_required,
        ) in rows:
            result[target_skill_id].append(
                (
                    prerequisite_skill_id,
                    prerequisite_name,
                    self._as_decimal(minimum_mastery),
                    bool(is_required),
                )
            )

        return dict(result)

    def _get_recently_completed_content(
        self,
        learner_id: str,
        cutoff_timestamp: datetime,
    ) -> set[str]:
        """
        Find content successfully completed in the 30-day lookback window.

        VIDEO and READING:
            Completed attempt is sufficient.

        QUIZ, LAB, PROJECT:
            Completed attempt must also have a passing assessment result.
        """
        window_start = cutoff_timestamp - timedelta(
            days=self.RECENT_COMPLETION_DAYS
        )

        rows = self.db.execute(
            select(
                Attempt.content_id,
                ContentItem.content_type,
                AssessmentResult.is_passed,
            )
            .select_from(Attempt)
            .join(
                ContentItem,
                ContentItem.content_id == Attempt.content_id,
            )
            .outerjoin(
                AssessmentResult,
                AssessmentResult.attempt_id == Attempt.attempt_id,
            )
            .where(
                Attempt.learner_id == learner_id,
                Attempt.status == "COMPLETED",
                Attempt.completed_at >= window_start,
                Attempt.completed_at <= cutoff_timestamp,
                Attempt.started_at <= Attempt.completed_at,
            )
        ).all()

        assessed_types = {"QUIZ", "LAB", "PROJECT"}
        completed_content = set()

        for content_id, content_type, is_passed in rows:
            if content_type in assessed_types:
                if is_passed is True:
                    completed_content.add(content_id)
            else:
                completed_content.add(content_id)

        return completed_content

    def _get_attempt_history(
        self,
        learner_id: str,
        cutoff_timestamp: datetime,
    ) -> tuple[set[str], dict[str, datetime], dict[str, bool]]:
        """
        Return:
        - IDs of content attempted by the learner by cutoff.
        - Latest attempt start time for each skill.
        - Whether the latest assessed attempt for each skill failed.
        """
        rows = self.db.execute(
            select(
                Attempt.content_id,
                Attempt.started_at,
                ContentSkill.skill_id,
                AssessmentResult.is_passed,
                AssessmentResult.graded_at,
            )
            .select_from(Attempt)
            .join(
                ContentSkill,
                ContentSkill.content_id == Attempt.content_id,
            )
            .outerjoin(
                AssessmentResult,
                AssessmentResult.attempt_id == Attempt.attempt_id,
            )
            .where(
                Attempt.learner_id == learner_id,
                Attempt.started_at <= cutoff_timestamp,
                ContentSkill.relevance_weight > 0,
            )
            .order_by(
                Attempt.started_at,
                Attempt.attempt_id,
            )
        ).all()

        attempted_content = set()
        latest_attempt_by_skill = {}
        latest_failed_by_skill = {}

        for (
            content_id,
            started_at,
            skill_id,
            is_passed,
            graded_at,
        ) in rows:
            attempted_content.add(content_id)

            previous_time = latest_attempt_by_skill.get(skill_id)

            if previous_time is None or started_at > previous_time:
                latest_attempt_by_skill[skill_id] = started_at

                # Only a graded assessment provides pass/fail evidence.
                latest_failed_by_skill[skill_id] = (
                    is_passed is False
                    and graded_at is not None
                    and graded_at <= cutoff_timestamp
                )

        return (
            attempted_content,
            latest_attempt_by_skill,
            latest_failed_by_skill,
        )

    def _get_path_alignment(
        self,
        learner_id: str,
        cutoff_timestamp: datetime,
    ) -> dict[str, Decimal]:
        """
        Assign path-alignment factors to content items in active paths.
        """
        paths = self.db.scalars(
            select(LearningPath).where(
                LearningPath.learner_id == learner_id,
                LearningPath.status == "ACTIVE",
                LearningPath.created_at <= cutoff_timestamp,
            )
        ).all()

        factors: dict[str, Decimal] = {}

        for path in paths:
            items = self.db.scalars(
                select(LearningPathItem)
                .where(
                    LearningPathItem.path_id == path.path_id,
                )
                .order_by(
                    LearningPathItem.sequence_order,
                    LearningPathItem.path_item_id,
                )
            ).all()

            pending_items = [
                item
                for item in items
                if not (
                    item.status == "COMPLETED"
                    and item.completed_at is not None
                    and item.completed_at <= cutoff_timestamp
                )
            ]

            if not pending_items:
                continue

            next_content_id = pending_items[0].content_id

            factors[next_content_id] = max(
                factors.get(next_content_id, ZERO),
                ONE,
            )

            for item in items:
                if item.content_id != next_content_id:
                    factors[item.content_id] = max(
                        factors.get(item.content_id, ZERO),
                        Decimal("0.5000"),
                    )

        return factors

    def _select_target_skill(
        self,
        mapped_skills: list[tuple[str, str, Decimal]],
        mastery_map: dict[str, Optional[Decimal]],
    ) -> Optional[tuple[str, str, Decimal]]:
        """
        Choose the largest weighted skill gap.

        Ties are resolved by skill_id ascending.
        """
        candidates = []

        for skill_id, skill_name, relevance in mapped_skills:
            mastery = mastery_map.get(skill_id)

            if mastery is not None and mastery >= self.TARGET_MASTERY:
                continue

            gap = (
                self.UNKNOWN_SKILL_GAP
                if mastery is None
                else ONE - mastery
            )

            weighted_gap = relevance * gap

            candidates.append(
                (
                    weighted_gap,
                    skill_id,
                    skill_name,
                    relevance,
                )
            )

        if not candidates:
            return None

        candidates.sort(
            key=lambda candidate: (
                -candidate[0],
                candidate[1],
            )
        )

        _, skill_id, skill_name, relevance = candidates[0]

        return skill_id, skill_name, relevance

    def _difficulty_factor(
        self,
        learner_experience_level: str,
        mastery_map: dict[str, Optional[Decimal]],
        content_difficulty: Decimal,
    ) -> Decimal:
        known_masteries = [
            mastery
            for mastery in mastery_map.values()
            if mastery is not None
        ]

        if known_masteries:
            mean_mastery = sum(
                known_masteries,
                ZERO,
            ) / Decimal(len(known_masteries))
        else:
            mean_mastery = self.UNKNOWN_DIFFICULTY_PRIOR.get(
                learner_experience_level,
                self.UNKNOWN_DIFFICULTY_PRIOR["BEGINNER"],
            )

        target_difficulty = min(
            ONE,
            mean_mastery + Decimal("0.1500"),
        )

        suitability = ONE - abs(
            content_difficulty - target_difficulty
        )

        return max(
            ZERO,
            min(ONE, suitability),
        )

    def _urgency_factor(
        self,
        target_skill_id: str,
        latest_attempt_by_skill: dict[str, datetime],
        cutoff_timestamp: datetime,
    ) -> Decimal:
        latest_attempt = latest_attempt_by_skill.get(
            target_skill_id
        )

        if latest_attempt is None:
            return Decimal("0.5000")

        elapsed_seconds = Decimal(
            str(
                (
                    cutoff_timestamp - latest_attempt
                ).total_seconds()
            )
        )

        elapsed_days = elapsed_seconds / Decimal("86400")

        return min(
            ONE,
            max(
                ZERO,
                elapsed_days / self.PRACTICE_URGENCY_DAYS,
            ),
        )

    def _reason_codes(
        self,
        target_skill_id: str,
        mastery_map: dict[str, Optional[Decimal]],
        evidence_counts: dict[str, int],
        latest_failed_by_skill: dict[str, bool],
        attempted_content: set[str],
        content_id: str,
        path_factor: Decimal,
        prerequisites_by_skill: dict[
            str, list[tuple[str, str, Decimal, bool]]
        ],
        has_any_attempts: bool,
        urgency_factor: Decimal,
    ) -> tuple[str, ...]:
        """
        Generate deterministic explanation codes.

        The first code is the primary explanation.
        """
        mastery = mastery_map.get(target_skill_id)
        reasons = []

        if not has_any_attempts:
            reasons.append("COLD_START")

        if path_factor == ONE:
            reasons.append("PATH_ALIGNED")

        if latest_failed_by_skill.get(target_skill_id, False):
            reasons.append("ASSESSMENT_REVIEW")

        if mastery is None:
            required_prerequisites = [
                prerequisite
                for prerequisite in prerequisites_by_skill.get(
                    target_skill_id, []
                )
                if prerequisite[3]
            ]

            if required_prerequisites:
                reasons.append("PREREQUISITES_MET")
            elif not required_prerequisites:
                reasons.append("FOUNDATIONAL_CONTENT")

        if urgency_factor >= Decimal("0.7500"):
            reasons.append("PRACTICE_DUE")

        evidence_count = evidence_counts.get(target_skill_id, 0)

        if evidence_count in (1, 2):
            reasons.append("LOW_EVIDENCE")

        reasons.append("SKILL_GAP")

        # Remove duplicate codes while preserving priority order.
        return tuple(dict.fromkeys(reasons))

    def _persist_recommendations(
        self,
        learner_id: str,
        cutoff_timestamp: datetime,
        selected_items: tuple[RecommendedItem, ...],
        rejection_summary: RejectionSummary,
    ) -> tuple[RecommendedItem, ...]:
        if not selected_items:
            return ()

        count = len(selected_items)
        rejection_audit_json = json.dumps(asdict(rejection_summary), sort_keys=True)

        for attempt_idx in range(3):
            try:
                allocated_ids = RecommendationIdAllocator.allocate_ids(
                    self.db, count=count, year=cutoff_timestamp.year
                )
                persisted_items = []

                for rank, (item, rec_id) in enumerate(zip(selected_items, allocated_ids), start=1):
                    score_components_json = json.dumps(
                        {
                            "gap": str(item.score_components.gap),
                            "difficulty_suitability": str(item.score_components.difficulty_suitability),
                            "path_alignment": str(item.score_components.path_alignment),
                            "practice_urgency": str(item.score_components.practice_urgency),
                            "total": str(item.score_components.total),
                        },
                        sort_keys=True,
                    )

                    rec_entity = Recommendation(
                        recommendation_id=rec_id,
                        learner_id=learner_id,
                        content_id=item.content_id,
                        target_skill_id=item.target_skill_id,
                        decision_timestamp=cutoff_timestamp,
                        rank_position=rank,
                        recommendation_score=item.score,
                        primary_reason_code=item.primary_reason_code,
                        score_components_json=score_components_json,
                        rejection_audit_json=rejection_audit_json,
                        algorithm_version=self.ALGORITHM_VERSION,
                    )
                    self.db.add(rec_entity)

                    outcome_id = format_outcome_id(rec_id)
                    outcome_entity = RecommendationOutcome(
                        outcome_id=outcome_id,
                        recommendation_id=rec_id,
                        outcome_status="RECOMMENDED",
                        interaction_attempt_id=None,
                        mastery_delta=None,
                        recorded_at=cutoff_timestamp,
                    )
                    self.db.add(outcome_entity)

                    persisted_items.append(
                        RecommendedItem(
                            content_id=item.content_id,
                            title=item.title,
                            score=item.score,
                            score_components=item.score_components,
                            target_skill_id=item.target_skill_id,
                            reason_codes=item.reason_codes,
                            primary_reason_code=item.primary_reason_code,
                            recommendation_id=rec_id,
                        )
                    )

                self.db.flush()
                return tuple(persisted_items)
            except IntegrityError:
                self.db.rollback()
                if attempt_idx == 2:
                    raise
        return ()

    def get_recommendations(
        self,
        learner_id: str,
        cutoff_timestamp: datetime,
        top_k: int = 5,
        persist: bool = False,
    ) -> RecommendationBatch:
        """
        Generate deterministic, explainable recommendations.

        When persist=True, atomically flushes Recommendation and initial
        RecommendationOutcome records within the current transaction.
        """
        if not isinstance(learner_id, str) or not learner_id.strip():
            raise ValueError("learner_id must be a non-empty string.")

        self._validate_cutoff(cutoff_timestamp)

        if isinstance(top_k, bool) or not isinstance(top_k, int):
            raise ValueError("top_k must be an integer greater than zero.")

        if top_k < 1:
            raise ValueError("top_k must be an integer greater than zero.")

        if persist:
            existing_recs = self.db.scalars(
                select(Recommendation)
                .where(
                    Recommendation.learner_id == learner_id,
                    Recommendation.decision_timestamp == cutoff_timestamp,
                )
                .order_by(Recommendation.rank_position)
            ).all()

            if existing_recs:
                persisted_items = []
                for rec in existing_recs[:top_k]:
                    content = self.db.get(ContentItem, rec.content_id)
                    title = content.title if content else ""
                    raw_comp = json.loads(rec.score_components_json)
                    comp = ScoreComponents(
                        gap=Decimal(raw_comp["gap"]),
                        difficulty_suitability=Decimal(raw_comp["difficulty_suitability"]),
                        path_alignment=Decimal(raw_comp["path_alignment"]),
                        practice_urgency=Decimal(raw_comp["practice_urgency"]),
                        total=Decimal(raw_comp["total"]),
                    )
                    persisted_items.append(
                        RecommendedItem(
                            content_id=rec.content_id,
                            title=title,
                            score=Decimal(str(rec.recommendation_score)),
                            score_components=comp,
                            target_skill_id=rec.target_skill_id,
                            reason_codes=(rec.primary_reason_code,),
                            primary_reason_code=rec.primary_reason_code,
                            recommendation_id=rec.recommendation_id,
                        )
                    )
                rej = RejectionSummary()
                if existing_recs[0].rejection_audit_json:
                    try:
                        rej_dict = json.loads(existing_recs[0].rejection_audit_json)
                        rej = RejectionSummary(**rej_dict)
                    except Exception:
                        pass

                return RecommendationBatch(
                    learner_id=learner_id,
                    cutoff_timestamp=cutoff_timestamp,
                    items=tuple(persisted_items),
                    rejection_summary=rej,
                )

        learner = self.db.get(Learner, learner_id)

        if learner is None:
            raise ValueError(
                f"Learner '{learner_id}' does not exist."
            )

        if not learner.is_active:
            return RecommendationBatch(
                learner_id=learner_id,
                cutoff_timestamp=cutoff_timestamp,
                items=(),
                rejection_summary=RejectionSummary(),
            )

        with localcontext(REC_CONTEXT):
            mastery_map = self._get_historical_mastery(
                learner_id,
                cutoff_timestamp,
            )

            evidence_counts = self._get_evidence_counts(
                learner_id,
                cutoff_timestamp,
            )

            prerequisites_by_skill = self._get_prerequisites()

            recently_completed = self._get_recently_completed_content(
                learner_id,
                cutoff_timestamp,
            )

            (
                attempted_content,
                latest_attempt_by_skill,
                latest_failed_by_skill,
            ) = self._get_attempt_history(
                learner_id,
                cutoff_timestamp,
            )

            path_alignment = self._get_path_alignment(
                learner_id,
                cutoff_timestamp,
            )

            skills = {
                skill.skill_id: skill.name
                for skill in self.db.scalars(
                    select(Skill).where(
                        Skill.is_active.is_(True)
                    )
                ).all()
            }

            all_content = self.db.scalars(
                select(ContentItem).order_by(
                    ContentItem.content_id
                )
            ).all()

            rejection_counts = {
                "inactive_content": 0,
                "unpublished_content": 0,
                "recent_completions": 0,
                "prerequisite_blocked": 0,
                "no_relevant_skill_gap": 0,
                "future_content": 0,
                "skill_already_mastered": 0,
            }

            candidates = []

            has_any_attempts = bool(attempted_content)

            for content in all_content:
                # Gate 1: inactive content.
                if not content.is_active:
                    rejection_counts["inactive_content"] += 1
                    continue

                # Gate 2: content must exist at the historical cutoff.
                if content.created_at > cutoff_timestamp:
                    rejection_counts["future_content"] += 1
                    rejection_counts["unpublished_content"] += 1
                    continue

                mapping_rows = self.db.execute(
                    select(
                        ContentSkill.skill_id,
                        ContentSkill.relevance_weight,
                    ).where(
                        ContentSkill.content_id == content.content_id,
                    )
                ).all()

                mapped_skills = [
                    (
                        skill_id,
                        skills[skill_id],
                        self._as_decimal(relevance_weight),
                    )
                    for skill_id, relevance_weight in mapping_rows
                    if (
                        skill_id in skills
                        and self._as_decimal(relevance_weight) > ZERO
                    )
                ]

                # Gate 3: must map to at least one active, relevant skill.
                if not mapped_skills:
                    rejection_counts["no_relevant_skill_gap"] += 1
                    continue

                # Gate 4: prevent successful recent repeats.
                if content.content_id in recently_completed:
                    rejection_counts["recent_completions"] += 1
                    continue

                # Gate 5: prerequisite eligibility before scoring.
                eligibility = (
                    PrerequisiteEligibilityHelper.check_prerequisites(
                        content_id=content.content_id,
                        mapped_skills=mapped_skills,
                        prerequisites_by_skill=prerequisites_by_skill,
                        mastery_map=mastery_map,
                    )
                )

                if not eligibility.is_eligible:
                    if eligibility.rejection_code in {
                        "PREREQUISITE_UNKNOWN",
                        "PREREQUISITES_UNMET",
                    }:
                        rejection_counts["prerequisite_blocked"] += 1
                    else:
                        rejection_counts["no_relevant_skill_gap"] += 1

                    continue

                # Gate 6: mastered content is not recommended.
                if all(
                    mastery_map.get(skill_id) is not None
                    and mastery_map[skill_id] >= self.TARGET_MASTERY
                    for skill_id, _, _ in mapped_skills
                ):
                    rejection_counts["skill_already_mastered"] += 1
                    rejection_counts["no_relevant_skill_gap"] += 1
                    continue

                target = self._select_target_skill(
                    mapped_skills,
                    mastery_map,
                )

                if target is None:
                    rejection_counts["skill_already_mastered"] += 1
                    continue

                target_skill_id, _, _ = target
                target_mastery = mastery_map.get(target_skill_id)

                gap_factor = (
                    self.UNKNOWN_SKILL_GAP
                    if target_mastery is None
                    else ONE - target_mastery
                )

                difficulty_factor = self._difficulty_factor(
                    learner.experience_level,
                    mastery_map,
                    self._as_decimal(content.difficulty),
                )

                path_factor = path_alignment.get(
                    content.content_id,
                    ZERO,
                )

                urgency_factor = self._urgency_factor(
                    target_skill_id,
                    latest_attempt_by_skill,
                    cutoff_timestamp,
                )

                total = (
                    self.GAP_WEIGHT * gap_factor
                    + self.DIFFICULTY_WEIGHT * difficulty_factor
                    + self.PATH_WEIGHT * path_factor
                    + self.URGENCY_WEIGHT * urgency_factor
                )

                score = total.quantize(
                    SCORE_QUANTUM,
                    rounding=ROUND_HALF_EVEN,
                )

                components = ScoreComponents(
                    gap=gap_factor,
                    difficulty_suitability=difficulty_factor,
                    path_alignment=path_factor,
                    practice_urgency=urgency_factor,
                    total=score,
                )

                reason_codes = self._reason_codes(
                    target_skill_id=target_skill_id,
                    mastery_map=mastery_map,
                    evidence_counts=evidence_counts,
                    latest_failed_by_skill=latest_failed_by_skill,
                    attempted_content=attempted_content,
                    content_id=content.content_id,
                    path_factor=path_factor,
                    prerequisites_by_skill=prerequisites_by_skill,
                    has_any_attempts=has_any_attempts,
                    urgency_factor=urgency_factor,
                )

                candidates.append(
                    (
                        score,
                        content.duration_minutes,
                        content.content_id,
                        RecommendedItem(
                            content_id=content.content_id,
                            title=content.title,
                            score=score,
                            score_components=components,
                            target_skill_id=target_skill_id,
                            reason_codes=reason_codes,
                            primary_reason_code=reason_codes[0],
                        ),
                    )
                )

            candidates.sort(
                key=lambda candidate: (
                    -candidate[0],
                    abs(candidate[1] - 30),
                    candidate[2],
                )
            )

            selected_items = tuple(
                candidate[3]
                for candidate in candidates[:top_k]
            )

            rejection_summary = RejectionSummary(
                **rejection_counts
            )

            if persist:
                selected_items = self._persist_recommendations(
                    learner_id=learner_id,
                    cutoff_timestamp=cutoff_timestamp,
                    selected_items=selected_items,
                    rejection_summary=rejection_summary,
                )

            return RecommendationBatch(
                learner_id=learner_id,
                cutoff_timestamp=cutoff_timestamp,
                items=selected_items,
                rejection_summary=rejection_summary,
            )