"""Business-rule compliance auditing and three-tier temporal leakage detection.

Implements:
1. Prerequisite compliance audit: Every recommended item must satisfy all required prerequisites
   against point-in-time mastery at cutoff T. Any violation fails the acceptance test.
2. Three-tier temporal leakage detection:
   - Tier 1: Evidence eligibility boundary (what could be used at T).
   - Tier 2: Actual evidence used (lineage IDs recorded in mastery/recommendation calculation).
   - Tier 3: Detected leakage (auditing whether any used evidence had graded_at > T or started_at > T).

CRITICAL: Future records existing in the database are NOT classified as leakage unless
prohibited future evidence actually influenced historical mastery or recommendation generation.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Set, Tuple
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.entities import AssessmentResult, ContentSkill, SkillPrerequisite
from src.services.mastery_service import MasteryService


@dataclass
class PrerequisiteAuditResult:
    """Outcome of prerequisite compliance audit across recommendations."""

    total_recommendations: int
    compliant_recommendations: int
    violations_count: int
    compliance_rate: float
    violations_details: List[Dict[str, str]] = field(default_factory=list)

    @property
    def is_fully_compliant(self) -> bool:
        """True if and only if compliance rate is exactly 100% (0 violations)."""
        return self.violations_count == 0


@dataclass
class TemporalLeakageAuditResult:
    """Outcome of temporal leakage audit across evaluated historical computations."""

    total_evaluations: int
    leaking_evaluations: int
    leakage_rate: float
    leakage_details: List[Dict[str, str]] = field(default_factory=list)

    @property
    def has_zero_leakage(self) -> bool:
        """True if and only if temporal leakage rate is exactly 0.0000."""
        return self.leaking_evaluations == 0


class BusinessRuleAuditor:
    """Audits pedagogical prerequisite compliance and temporal leakage."""

    def __init__(self, session: Session, mastery_service: Optional[MasteryService] = None) -> None:
        self.session = session
        self.mastery_service = mastery_service or MasteryService(session)

    def audit_prerequisite_compliance(
        self,
        learner_recommendations: Dict[str, List[str]],  # learner_id -> [content_ids]
        cutoff: datetime,
    ) -> PrerequisiteAuditResult:
        """Audit every recommended item against required prerequisites at decision cutoff T.

        Any recommendation for content whose prerequisites are unmet by learner at cutoff T
        is flagged as a violation.
        """
        total_recs = 0
        violations = []

        for learner_id, content_ids in learner_recommendations.items():
            for content_id in content_ids:
                total_recs += 1

                # Find all skills mapped to this content with positive relevance
                mapped_skills = self.session.scalars(
                    select(ContentSkill.skill_id)
                    .where(
                        ContentSkill.content_id == content_id,
                        ContentSkill.relevance_weight > 0,
                    )
                ).all()

                if not mapped_skills:
                    continue

                # Query required prerequisites for these skills
                prereqs = self.session.scalars(
                    select(SkillPrerequisite)
                    .where(
                        SkillPrerequisite.skill_id.in_(mapped_skills),
                        SkillPrerequisite.is_required.is_(True),
                    )
                ).all()

                for p in prereqs:
                    # Point-in-time mastery of the prerequisite skill at cutoff T
                    mastery, _, _, _, _ = self.mastery_service.compute_mastery(
                        learner_id=learner_id,
                        skill_id=p.prerequisite_skill_id,
                        cutoff_timestamp=cutoff,
                    )

                    # Required threshold check: unknown (None) or below minimum_mastery is a violation
                    is_unmet = (mastery is None) or (mastery < p.minimum_mastery)
                    if is_unmet:
                        actual_str = f"{mastery:.4f}" if mastery is not None else "UNKNOWN"
                        violations.append(
                            {
                                "learner_id": learner_id,
                                "content_id": content_id,
                                "target_skill_id": p.skill_id,
                                "prerequisite_skill_id": p.prerequisite_skill_id,
                                "required_threshold": str(p.minimum_mastery),
                                "actual_mastery": actual_str,
                                "cutoff": cutoff.isoformat(),
                            }
                        )
                        break  # Count violation once per recommendation item

        violations_count = len(violations)
        compliant_count = total_recs - violations_count
        rate = (compliant_count / float(total_recs)) if total_recs > 0 else 1.0

        return PrerequisiteAuditResult(
            total_recommendations=total_recs,
            compliant_recommendations=compliant_count,
            violations_count=violations_count,
            compliance_rate=rate,
            violations_details=violations,
        )

    def audit_temporal_leakage(
        self,
        evaluated_calculations: List[Tuple[str, str, datetime, List[str]]],
        # List of (learner_id, skill_id, cutoff, used_evidence_result_ids)
    ) -> TemporalLeakageAuditResult:
        """Audit whether future evidence actually influenced historical calculations.

        CRITICAL SEPARATION:
        The presence of future records in the database is normal and NOT leakage.
        Leakage is flagged ONLY if a record in used_evidence_result_ids was graded after cutoff!
        """
        total_evals = len(evaluated_calculations)
        leaking_evals = []

        for learner_id, skill_id, cutoff, used_result_ids in evaluated_calculations:
            if not used_result_ids:
                continue

            # Query the actual grading timestamps of the used evidence IDs
            future_results = self.session.scalars(
                select(AssessmentResult)
                .where(
                    AssessmentResult.result_id.in_(used_result_ids),
                    AssessmentResult.graded_at > cutoff,
                )
            ).all()

            if future_results:
                first = future_results[0]
                leaking_evals.append(
                    {
                        "learner_id": learner_id,
                        "skill_id": skill_id,
                        "cutoff": cutoff.isoformat(),
                        "leaking_result_id": first.result_id,
                        "graded_at": first.graded_at.isoformat(),
                    }
                )

        leaking_count = len(leaking_evals)
        rate = (leaking_count / float(total_evals)) if total_evals > 0 else 0.0

        return TemporalLeakageAuditResult(
            total_evaluations=total_evals,
            leaking_evaluations=leaking_count,
            leakage_rate=rate,
            leakage_details=leaking_evals,
        )
