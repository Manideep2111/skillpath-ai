"""Learner Skill Mastery Estimation Module for SkillPath AI.

Implements deterministic point-in-time mastery estimation, evidence-volume
confidence scoring, and append-only snapshot persistence according to
SRS v1.2.0-FINAL-SPEC and Technical Design Specification v1.1.0-DESIGN.
"""

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
import hashlib
import json
from typing import Dict, List, Optional, Set, Tuple
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.entities import (
    Skill,
    ContentSkill,
    Attempt,
    AssessmentResult,
    MasterySnapshot,
)

# Explicit high-precision Decimal evaluation context (28 significant digits, half-to-even rounding)
MASTERY_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)

DECIMAL_ZERO = Decimal("0")
DECIMAL_ONE = Decimal("1")
DECIMAL_HALF_LIFE = Decimal("2592000")  # 30 days * 86,400 seconds
DECIMAL_SECONDS_PER_DAY = Decimal("86400")
DECIMAL_MICROS_PER_SEC = Decimal("1000000")
DECIMAL_PRECISION = Decimal("0.0001")
DECIMAL_SATURATION_N = Decimal("3")
DECIMAL_LN2 = Decimal("2").ln(MASTERY_CONTEXT)

# Default algorithm version decoupled from the platform SRS version
DEFAULT_ALGORITHM_VERSION = "v1.1.0"


class MasteryService:
    """Computes, persists, and audits point-in-time learner skill mastery snapshots."""

    def __init__(
        self,
        session: Session,
        algorithm_version: str = DEFAULT_ALGORITHM_VERSION,
    ) -> None:
        self.session = session
        self.algorithm_version = algorithm_version

    @staticmethod
    def calculate_elapsed_seconds(cutoff_timestamp: datetime, graded_at: datetime) -> Decimal:
        """Calculate non-negative elapsed seconds purely using Decimal arithmetic on timedelta components.

        Formula:
            days * 86400 + seconds + microseconds / 1,000,000

        Guarantees zero binary floating-point operations.
        """
        if (cutoff_timestamp.tzinfo is None) != (graded_at.tzinfo is None):
            raise ValueError(
                "cutoff_timestamp and graded_at must either both be timezone-aware or both be timezone-naive"
            )

        td = cutoff_timestamp - graded_at
        with localcontext(MASTERY_CONTEXT):
            raw_seconds = (
                (Decimal(td.days) * DECIMAL_SECONDS_PER_DAY)
                + Decimal(td.seconds)
                + (Decimal(td.microseconds) / DECIMAL_MICROS_PER_SEC)
            )
            return raw_seconds if raw_seconds >= DECIMAL_ZERO else DECIMAL_ZERO

    @staticmethod
    def calculate_recency_weight(delta_seconds: Decimal) -> Decimal:
        """Compute exponential decay weight 2^(-dt / t_half) purely in Decimal using Decimal.exp() and Decimal.ln().

        Evaluates under MASTERY_CONTEXT (28-digit precision, ROUND_HALF_EVEN).
        Validates that delta_seconds is non-negative to prevent weights exceeding 1.0.
        """
        if delta_seconds < DECIMAL_ZERO:
            raise ValueError(f"delta_seconds must be non-negative, got {delta_seconds}")

        with localcontext(MASTERY_CONTEXT):
            exponent = -(delta_seconds / DECIMAL_HALF_LIFE) * DECIMAL_LN2
            weight = exponent.exp()
            return DECIMAL_ONE if weight > DECIMAL_ONE else weight

    @staticmethod
    def compute_confidence_score(evidence_count: int) -> Decimal:
        """Calculate evidence-volume confidence indicator quantized to 4 decimal places.

        Indicator saturates at n = 3 (confidence = 1.0000). Measures observed evidence volume,
        not statistical independence.
        """
        if evidence_count <= 0:
            return Decimal("0.0000")

        with localcontext(MASTERY_CONTEXT):
            ratio = Decimal(evidence_count) / DECIMAL_SATURATION_N
            clamped = ratio if ratio < DECIMAL_ONE else DECIMAL_ONE
            return clamped.quantize(DECIMAL_PRECISION)

    @staticmethod
    def generate_snapshot_id(
        learner_id: str,
        skill_id: str,
        cutoff_timestamp: datetime,
        algorithm_version: str,
    ) -> str:
        """Generate deterministic, collision-resistant 32-character snapshot identifier.

        Format: 'SNP-' + 28 hex characters from SHA-256(learner|skill|canonical_ts|version).
        Normalizes timezone-aware timestamps to UTC before formatting.
        """
        if cutoff_timestamp.tzinfo is not None:
            utc_ts = cutoff_timestamp.astimezone(timezone.utc)
            canonical_ts = utc_ts.strftime("%Y-%m-%dT%H:%M:%S.%f")
        else:
            canonical_ts = cutoff_timestamp.strftime("%Y-%m-%dT%H:%M:%S.%f")

        payload = f"{learner_id}|{skill_id}|{canonical_ts}|{algorithm_version}"
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return f"SNP-{digest[:28]}"

    def _aggregate_evidence(
        self,
        evidence: List[Tuple[str, Decimal, Decimal, datetime]],
        cutoff_timestamp: datetime,
    ) -> Tuple[Optional[Decimal], int, Decimal, Optional[datetime], List[str]]:
        """Shared calculation engine for aggregating evidence into mastery, confidence, and lineage."""
        if not evidence:
            return (None, 0, Decimal("0.0000"), None, [])

        with localcontext(MASTERY_CONTEXT):
            numerator = Decimal("0")
            denominator = Decimal("0")
            result_ids: List[str] = []
            max_graded_at: Optional[datetime] = None

            for res_id, norm_score, rel_weight, graded_at in evidence:
                result_ids.append(res_id)
                if max_graded_at is None or graded_at > max_graded_at:
                    max_graded_at = graded_at

                delta_seconds = self.calculate_elapsed_seconds(cutoff_timestamp, graded_at)
                w_i = self.calculate_recency_weight(delta_seconds)
                effective_weight = w_i * rel_weight

                numerator += effective_weight * norm_score
                denominator += effective_weight

            mastery_level = (numerator / denominator).quantize(DECIMAL_PRECISION)
            count = len(result_ids)
            confidence_score = self.compute_confidence_score(count)

            return (mastery_level, count, confidence_score, max_graded_at, result_ids)

    def get_eligible_evidence(
        self,
        learner_id: str,
        skill_id: str,
        cutoff_timestamp: datetime,
    ) -> List[Tuple[str, Decimal, Decimal, datetime]]:
        """Retrieve completed, positive-relevance assessment results graded <= cutoff_timestamp.

        Returns:
            List of tuples: (result_id, normalized_score, relevance_weight, graded_at)
            ordered chronologically by graded_at ASC, result_id ASC.
        """
        stmt = (
            select(
                AssessmentResult.result_id,
                AssessmentResult.normalized_score,
                ContentSkill.relevance_weight,
                AssessmentResult.graded_at,
            )
            .join(Attempt, AssessmentResult.attempt_id == Attempt.attempt_id)
            .join(ContentSkill, Attempt.content_id == ContentSkill.content_id)
            .where(
                Attempt.learner_id == learner_id,
                ContentSkill.skill_id == skill_id,
                Attempt.status == "COMPLETED",
                Attempt.started_at <= Attempt.completed_at,
                Attempt.completed_at <= AssessmentResult.graded_at,
                AssessmentResult.graded_at <= cutoff_timestamp,
                ContentSkill.relevance_weight > 0.0,
            )
            .order_by(AssessmentResult.graded_at.asc(), AssessmentResult.result_id.asc())
        )
        rows = self.session.execute(stmt).all()
        return [
            (
                r[0],
                Decimal(str(r[1])),
                Decimal(str(r[2])),
                r[3],
            )
            for r in rows
        ]

    def compute_mastery(
        self,
        learner_id: str,
        skill_id: str,
        cutoff_timestamp: datetime,
    ) -> Tuple[Optional[Decimal], int, Decimal, Optional[datetime], List[str]]:
        """Compute point-in-time mastery level, volume indicator, and lineage metadata."""
        evidence = self.get_eligible_evidence(learner_id, skill_id, cutoff_timestamp)
        return self._aggregate_evidence(evidence, cutoff_timestamp)

    def get_or_create_snapshot(
        self,
        learner_id: str,
        skill_id: str,
        cutoff_timestamp: datetime,
    ) -> MasterySnapshot:
        """Idempotently retrieve an existing snapshot or compute and persist a new snapshot.

        Enforces write-once / append-only semantics. Never issues UPDATE or DELETE on mastery_snapshots.
        """
        # Step 1: Check for existing snapshot under the exact unique constraint tuple
        stmt = select(MasterySnapshot).where(
            MasterySnapshot.learner_id == learner_id,
            MasterySnapshot.skill_id == skill_id,
            MasterySnapshot.cutoff_timestamp == cutoff_timestamp,
            MasterySnapshot.algorithm_version == self.algorithm_version,
        )
        existing = self.session.scalars(stmt).first()
        if existing is not None:
            return existing

        # Step 2: Calculate mastery and lineage under pure Decimal arithmetic
        mastery_level, count, confidence, max_graded, result_ids = self.compute_mastery(
            learner_id, skill_id, cutoff_timestamp
        )

        # Step 3: Instantiate immutable snapshot with deterministic identifier
        snapshot_id = self.generate_snapshot_id(
            learner_id, skill_id, cutoff_timestamp, self.algorithm_version
        )
        snapshot = MasterySnapshot(
            snapshot_id=snapshot_id,
            learner_id=learner_id,
            skill_id=skill_id,
            mastery_level=mastery_level,
            evidence_count=count,
            confidence_score=confidence,
            cutoff_timestamp=cutoff_timestamp,
            max_evidence_graded_at=max_graded,
            evidence_result_ids_json=json.dumps(result_ids, separators=(",", ":")),
            algorithm_version=self.algorithm_version,
            calculated_at=datetime.utcnow(),
        )

        self.session.add(snapshot)
        self.session.flush()
        return snapshot

    def compute_learner_profile(
        self,
        learner_id: str,
        cutoff_timestamp: datetime,
    ) -> Dict[str, MasterySnapshot]:
        """Compute or retrieve snapshots for all active curriculum skills via batch resolution.

        Guarantees that 100% of active curriculum skills are present in the returned dictionary,
        populating unassessed skills with verified Unknown snapshots.
        """
        # Step 1: Retrieve all active curriculum skills
        skill_stmt = (
            select(Skill.skill_id)
            .where(Skill.is_active.is_(True))
            .order_by(Skill.skill_id.asc())
        )
        active_skill_ids = self.session.scalars(skill_stmt).all()

        # Step 2: Batch query existing snapshots for this learner at the specified cutoff and version
        snap_stmt = select(MasterySnapshot).where(
            MasterySnapshot.learner_id == learner_id,
            MasterySnapshot.cutoff_timestamp == cutoff_timestamp,
            MasterySnapshot.algorithm_version == self.algorithm_version,
        )
        existing_snapshots = self.session.scalars(snap_stmt).all()
        profile_map: Dict[str, MasterySnapshot] = {s.skill_id: s for s in existing_snapshots}

        missing_skill_ids = [sid for sid in active_skill_ids if sid not in profile_map]
        if not missing_skill_ids:
            return profile_map

        # Step 3: Batch query eligible assessment evidence for missing skills in a single grouped join
        evidence_stmt = (
            select(
                ContentSkill.skill_id,
                AssessmentResult.result_id,
                AssessmentResult.normalized_score,
                ContentSkill.relevance_weight,
                AssessmentResult.graded_at,
            )
            .join(Attempt, AssessmentResult.attempt_id == Attempt.attempt_id)
            .join(ContentSkill, Attempt.content_id == ContentSkill.content_id)
            .where(
                Attempt.learner_id == learner_id,
                ContentSkill.skill_id.in_(missing_skill_ids),
                Attempt.status == "COMPLETED",
                Attempt.started_at <= Attempt.completed_at,
                Attempt.completed_at <= AssessmentResult.graded_at,
                AssessmentResult.graded_at <= cutoff_timestamp,
                ContentSkill.relevance_weight > 0.0,
            )
            .order_by(
                ContentSkill.skill_id.asc(),
                AssessmentResult.graded_at.asc(),
                AssessmentResult.result_id.asc(),
            )
        )
        evidence_rows = self.session.execute(evidence_stmt).all()

        evidence_by_skill: Dict[str, List[Tuple[str, Decimal, Decimal, datetime]]] = defaultdict(list)
        for skill_id, res_id, norm_score, rel_weight, graded_at in evidence_rows:
            evidence_by_skill[skill_id].append(
                (
                    res_id,
                    Decimal(str(norm_score)),
                    Decimal(str(rel_weight)),
                    graded_at,
                )
            )

        # Step 4: Resolve snapshots in memory and batch persist missing records using the unified aggregator
        for sid in missing_skill_ids:
            skill_evidence = evidence_by_skill.get(sid, [])
            mastery_level, count, confidence, max_graded, result_ids = self._aggregate_evidence(
                skill_evidence, cutoff_timestamp
            )

            snap_id = self.generate_snapshot_id(
                learner_id, sid, cutoff_timestamp, self.algorithm_version
            )
            new_snap = MasterySnapshot(
                snapshot_id=snap_id,
                learner_id=learner_id,
                skill_id=sid,
                mastery_level=mastery_level,
                evidence_count=count,
                confidence_score=confidence,
                cutoff_timestamp=cutoff_timestamp,
                max_evidence_graded_at=max_graded,
                evidence_result_ids_json=json.dumps(result_ids, separators=(",", ":")),
                algorithm_version=self.algorithm_version,
                calculated_at=datetime.utcnow(),
            )
            self.session.add(new_snap)
            profile_map[sid] = new_snap

        self.session.flush()
        return profile_map