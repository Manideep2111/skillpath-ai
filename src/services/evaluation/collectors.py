"""Data collectors for recommendation quality and temporal evaluation.

Provides structured, read-only data collection separated cleanly from metric calculations:
- Catalog snapshot extraction at cutoff T.
- Learner cohort retrieval and activity stratification (low, med, high).
- Ground-truth learner interactions and ideal relevance pool collection in (T, actual_horizon].
- Five read-only anomaly audits:
  1. Recommendation prerequisite compliance (A1)
  2. Attempt timestamp order inversions (A2)
  3. Orphaned content-skill references (A3)
  4. Future mastery snapshot leakage (A4)
  5. Learning path loops without progress (A5)
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
import json
import logging
import statistics
from typing import Any, Collection, Dict, List, Optional, Set, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.models.entities import (
    AssessmentResult,
    Attempt,
    ContentItem,
    ContentSkill,
    Learner,
    LearningPathItem,
    MasterySnapshot,
    Recommendation,
    Skill,
    SkillPrerequisite,
)
from src.services.evaluation.business_rules import (
    BusinessRuleAuditor,
    PrerequisiteAuditResult,
    TemporalLeakageAuditResult,
)
from src.services.evaluation.ground_truth import (
    GroundTruthExtractor,
    LearnerGroundTruth,
)
from src.services.evaluation.temporal_split import TemporalWindow
from src.services.mastery_service import MasteryService

logger = logging.getLogger(__name__)


@dataclass
class CatalogSnapshot:
    """Catalog state at cutoff timestamp T."""

    cutoff: datetime
    active_content_ids: Set[str]
    total_active_items: int


@dataclass
class LearnerCohortSnapshot:
    """Learner cohort accounting and activity stratification at cutoff timestamp T."""

    cutoff: datetime
    total_learners: int
    all_learner_ids: List[str]
    cold_start_learner_ids: Set[str]
    sparse_learner_ids: Set[str]
    active_learner_ids: Set[str]
    activity_strata: Dict[str, List[str]]  # "low", "med", "high" -> learner_ids
    learner_attempt_counts: Dict[str, int]


@dataclass
class LearnerInteractionSnapshot:
    """Empirical post-cutoff learner engagement and ground-truth relevance in (T, actual_horizon]."""

    learner_id: str
    cutoff: datetime
    actual_horizon: datetime
    observed_items: Set[str]  # All items attempted or completed in outcome window
    relevant_items: Set[str]  # Items with positive relevance grade >= 1
    relevance_grades: Dict[str, int]  # content_id -> grade (0..3)
    ideal_pool: Dict[str, int]  # External ideal pool for IDCG calculation
    observed_attempt_count: int
    observed_assessment_count: int
    earliest_post_cutoff_assessment: Optional[Tuple[str, datetime, Decimal]] = None
    # (skill_id, graded_at, normalized_score)


@dataclass
class AnomalyAuditResult:
    """Read-only anomaly audit outcome."""

    audit_name: str
    anomaly_type: str
    passed: bool
    total_checked: int
    violations_count: int
    details: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class EvaluationDataCollector:
    """Collects historical snapshots, cohort partitions, and outcome evidence for evaluation."""

    def __init__(
        self,
        session: Session,
        mastery_service: Optional[MasteryService] = None,
        gt_extractor: Optional[GroundTruthExtractor] = None,
        auditor: Optional[BusinessRuleAuditor] = None,
    ) -> None:
        self.session = session
        self.mastery_service = mastery_service or MasteryService(session)
        self.gt_extractor = gt_extractor or GroundTruthExtractor(
            session, mastery_service=self.mastery_service
        )
        self.auditor = auditor or BusinessRuleAuditor(
            session, mastery_service=self.mastery_service
        )

    def collect_active_catalog(self, cutoff: datetime) -> CatalogSnapshot:
        """Identify catalog items that are active and created on or before cutoff T."""
        active_ids = set(
            self.session.scalars(
                select(ContentItem.content_id).where(
                    ContentItem.created_at <= cutoff,
                    ContentItem.is_active.is_(True),
                )
            ).all()
        )
        return CatalogSnapshot(
            cutoff=cutoff,
            active_content_ids=active_ids,
            total_active_items=len(active_ids),
        )

    def collect_learner_cohorts(self, cutoff: datetime) -> LearnerCohortSnapshot:
        """Retrieve all learners and stratify into cold-start, sparse, active, and tertile strata."""
        all_lids = self.session.scalars(
            select(Learner.learner_id).order_by(Learner.learner_id)
        ).all()
        total_learners = len(all_lids)

        # Count completed attempts strictly on or before cutoff T
        attempt_rows = self.session.execute(
            select(Attempt.learner_id, func.count(Attempt.attempt_id))
            .where(
                Attempt.status == "COMPLETED",
                Attempt.completed_at <= cutoff,
                Attempt.started_at <= Attempt.completed_at,
            )
            .group_by(Attempt.learner_id)
        ).all()

        counts_by_learner: Dict[str, int] = {lid: 0 for lid in all_lids}
        for lid, count in attempt_rows:
            counts_by_learner[lid] = int(count)

        cold_start_lids = set()
        sparse_lids = set()
        active_lids = set()

        for lid, count in counts_by_learner.items():
            if count == 0:
                cold_start_lids.add(lid)
            elif count < 5:
                sparse_lids.add(lid)
            else:
                active_lids.add(lid)

        # Compute activity strata: "low", "med", "high"
        # Uses tertile cutpoints from prior attempt counts
        activity_strata: Dict[str, List[str]] = {"low": [], "med": [], "high": []}
        all_counts = [counts_by_learner[lid] for lid in all_lids]

        if len(all_counts) >= 3 and len(set(all_counts)) > 1:
            try:
                cutpoints = statistics.quantiles(all_counts, n=3)
                q1, q2 = cutpoints[0], cutpoints[1]
            except statistics.StatisticsError:
                q1, q2 = 5.0, 15.0
        else:
            q1, q2 = 5.0, 15.0

        for lid in all_lids:
            c = counts_by_learner[lid]
            if c <= q1:
                activity_strata["low"].append(lid)
            elif c <= q2:
                activity_strata["med"].append(lid)
            else:
                activity_strata["high"].append(lid)

        return LearnerCohortSnapshot(
            cutoff=cutoff,
            total_learners=total_learners,
            all_learner_ids=all_lids,
            cold_start_learner_ids=cold_start_lids,
            sparse_learner_ids=sparse_lids,
            active_learner_ids=active_lids,
            activity_strata=activity_strata,
            learner_attempt_counts=counts_by_learner,
        )

    def collect_learner_interactions(
        self,
        learner_id: str,
        window: TemporalWindow,
    ) -> LearnerInteractionSnapshot:
        """Extract post-cutoff learner engagement and empirical relevance in (T, actual_horizon]."""
        gt: LearnerGroundTruth = self.gt_extractor.extract_for_learner(
            learner_id, window
        )

        # All observed items attempted or completed in outcome window
        observed_attempts = self.session.scalars(
            select(Attempt.content_id).where(
                Attempt.learner_id == learner_id,
                Attempt.completed_at > window.cutoff,
                Attempt.completed_at <= window.actual_horizon,
            )
        ).all()

        observed_set = set(observed_attempts)
        # Ensure relevant items are always included in observed items
        observed_set.update(gt.relevant_items)

        # External ideal pool for IDCG is the full ground-truth relevance pool
        ideal_pool = dict(gt.relevance_grades)

        # Find earliest post-cutoff assessment in the outcome window
        earliest_res = self.session.execute(
            select(
                ContentSkill.skill_id,
                AssessmentResult.graded_at,
                AssessmentResult.normalized_score,
            )
            .select_from(AssessmentResult)
            .join(Attempt, Attempt.attempt_id == AssessmentResult.attempt_id)
            .join(ContentSkill, ContentSkill.content_id == Attempt.content_id)
            .where(
                Attempt.learner_id == learner_id,
                Attempt.status == "COMPLETED",
                AssessmentResult.graded_at > window.cutoff,
                AssessmentResult.graded_at <= window.actual_horizon,
                ContentSkill.relevance_weight > 0,
            )
            .order_by(AssessmentResult.graded_at.asc())
        ).first()

        earliest_tuple = None
        if earliest_res:
            earliest_tuple = (
                earliest_res[0],
                earliest_res[1],
                Decimal(str(earliest_res[2])) if earliest_res[2] is not None else Decimal("0.0"),
            )

        return LearnerInteractionSnapshot(
            learner_id=learner_id,
            cutoff=window.cutoff,
            actual_horizon=window.actual_horizon,
            observed_items=observed_set,
            relevant_items=gt.relevant_items,
            relevance_grades=gt.relevance_grades,
            ideal_pool=ideal_pool,
            observed_attempt_count=gt.observed_attempt_count,
            observed_assessment_count=gt.observed_assessment_count,
            earliest_post_cutoff_assessment=earliest_tuple,
        )

    def collect_all_learner_interactions(
        self,
        learner_ids: Collection[str],
        window: TemporalWindow,
    ) -> Dict[str, LearnerInteractionSnapshot]:
        """Collect ground-truth interaction snapshots across multiple learners."""
        snapshots = {}
        for lid in learner_ids:
            snapshots[lid] = self.collect_learner_interactions(lid, window)
        return snapshots

    def run_five_anomaly_audits(
        self,
        cutoff: datetime,
        learner_recommendations: Optional[Dict[str, List[str]]] = None,
        lineage_evaluations: Optional[List[Tuple[str, str, datetime, List[str]]]] = None,
    ) -> Dict[str, AnomalyAuditResult]:
        """Execute five read-only anomaly audits.

        Audits:
        1. PREREQUISITE_COMPLIANCE (A1)
        2. TIMESTAMP_ORDERING (A2)
        3. ORPHANED_CONTENT_SKILLS (A3)
        4. FUTURE_MASTERY_LEAKAGE (A4)
        5. LEARNING_PATH_LOOPS (A5)
        """
        audits: Dict[str, AnomalyAuditResult] = {}

        # ---------------------------------------------------------------------
        # 1. Prerequisite Compliance (A1)
        # ---------------------------------------------------------------------
        prereq_violations = []
        total_recs_checked = 0

        if learner_recommendations:
            prereq_res: PrerequisiteAuditResult = (
                self.auditor.audit_prerequisite_compliance(
                    learner_recommendations, cutoff
                )
            )
            total_recs_checked += prereq_res.total_recommendations
            prereq_violations.extend(prereq_res.violations_details)

        # Also inspect any persisted recommendations in database
        persisted_recs = self.session.scalars(select(Recommendation)).all()
        if persisted_recs:
            total_recs_checked += len(persisted_recs)
            for rec in persisted_recs:
                mapped_skills = self.session.scalars(
                    select(ContentSkill.skill_id).where(
                        ContentSkill.content_id == rec.content_id,
                        ContentSkill.relevance_weight > 0,
                    )
                ).all()
                if not mapped_skills:
                    continue
                prereqs = self.session.scalars(
                    select(SkillPrerequisite).where(
                        SkillPrerequisite.skill_id.in_(mapped_skills),
                        SkillPrerequisite.is_required.is_(True),
                    )
                ).all()
                for p in prereqs:
                    m, _, _, _, _ = self.mastery_service.compute_mastery(
                        rec.learner_id, p.prerequisite_skill_id, rec.decision_timestamp
                    )
                    if m is None or m < p.minimum_mastery:
                        prereq_violations.append(
                            {
                                "recommendation_id": rec.recommendation_id,
                                "learner_id": rec.learner_id,
                                "prerequisite_skill_id": p.prerequisite_skill_id,
                                "required_threshold": str(p.minimum_mastery),
                                "actual_mastery": str(m) if m is not None else "UNKNOWN",
                            }
                        )
                        break

        audits["prerequisite_compliance"] = AnomalyAuditResult(
            audit_name="PREREQUISITE_COMPLIANCE",
            anomaly_type="PREREQUISITE_VIOLATION",
            passed=len(prereq_violations) == 0,
            total_checked=total_recs_checked,
            violations_count=len(prereq_violations),
            details=prereq_violations,
            metadata={"cutoff": cutoff.isoformat()},
        )

        # ---------------------------------------------------------------------
        # 2. Attempt Timestamp Ordering (A2)
        # ---------------------------------------------------------------------
        timestamp_inversions = []
        total_attempts = self.session.scalar(select(func.count(Attempt.attempt_id))) or 0

        # a) completed_at < started_at
        inverted_attempts = self.session.scalars(
            select(Attempt)
            .where(Attempt.completed_at.is_not(None))
            .where(Attempt.completed_at < Attempt.started_at)
        ).all()
        for att in inverted_attempts:
            timestamp_inversions.append(
                {
                    "entity_type": "Attempt",
                    "entity_id": att.attempt_id,
                    "reason": f"completed_at ({att.completed_at}) < started_at ({att.started_at})",
                }
            )

        # b) AssessmentResult graded_at < Attempt completed_at
        premature_assessments = self.session.scalars(
            select(AssessmentResult)
            .join(Attempt, AssessmentResult.attempt_id == Attempt.attempt_id)
            .where(Attempt.completed_at.is_not(None))
            .where(AssessmentResult.graded_at < Attempt.completed_at)
        ).all()
        for res in premature_assessments:
            timestamp_inversions.append(
                {
                    "entity_type": "AssessmentResult",
                    "entity_id": res.result_id,
                    "reason": f"graded_at ({res.graded_at}) < attempt completion",
                }
            )

        # c) Attempt status IN_PROGRESS with non-null completed_at
        invalid_in_progress = self.session.scalars(
            select(Attempt)
            .where(Attempt.status == "IN_PROGRESS")
            .where(Attempt.completed_at.is_not(None))
        ).all()
        for att in invalid_in_progress:
            timestamp_inversions.append(
                {
                    "entity_type": "Attempt",
                    "entity_id": att.attempt_id,
                    "reason": f"status IN_PROGRESS with non-null completed_at ({att.completed_at})",
                }
            )

        audits["timestamp_ordering"] = AnomalyAuditResult(
            audit_name="TIMESTAMP_ORDERING",
            anomaly_type="TIMESTAMP_ORDER_INVERSION",
            passed=len(timestamp_inversions) == 0,
            total_checked=total_attempts,
            violations_count=len(timestamp_inversions),
            details=timestamp_inversions,
        )

        # ---------------------------------------------------------------------
        # 3. Orphaned Content-Skill References (A3)
        # ---------------------------------------------------------------------
        orphaned_skills = []
        total_content_skills = (
            self.session.scalar(select(func.count(ContentSkill.content_id))) or 0
        )

        missing_skills = self.session.execute(
            select(ContentSkill.content_id, ContentSkill.skill_id)
            .outerjoin(Skill, ContentSkill.skill_id == Skill.skill_id)
            .where(Skill.skill_id.is_(None))
        ).all()
        for c_id, s_id in missing_skills:
            orphaned_skills.append(
                {
                    "content_id": c_id,
                    "skill_id": s_id,
                    "reason": f"Skill {s_id} does not exist in skills table",
                }
            )

        missing_content = self.session.execute(
            select(ContentSkill.content_id, ContentSkill.skill_id)
            .outerjoin(ContentItem, ContentSkill.content_id == ContentItem.content_id)
            .where(ContentItem.content_id.is_(None))
        ).all()
        for c_id, s_id in missing_content:
            orphaned_skills.append(
                {
                    "content_id": c_id,
                    "skill_id": s_id,
                    "reason": f"ContentItem {c_id} does not exist in content_items table",
                }
            )

        audits["orphaned_content_skills"] = AnomalyAuditResult(
            audit_name="ORPHANED_CONTENT_SKILLS",
            anomaly_type="NONEXISTENT_SKILL_REFERENCE",
            passed=len(orphaned_skills) == 0,
            total_checked=total_content_skills,
            violations_count=len(orphaned_skills),
            details=orphaned_skills,
        )

        # ---------------------------------------------------------------------
        # 4. Future Mastery Snapshot Leakage (A4)
        # ---------------------------------------------------------------------
        leakage_findings = []
        total_leak_checks = 0

        # a) Inspect MasterySnapshot rows
        snapshots = self.session.scalars(select(MasterySnapshot)).all()
        total_leak_checks += len(snapshots)
        for s in snapshots:
            is_leaking = False
            reason = ""
            if s.max_evidence_graded_at and s.max_evidence_graded_at > s.cutoff_timestamp:
                is_leaking = True
                reason = f"max_evidence_graded_at ({s.max_evidence_graded_at}) > cutoff ({s.cutoff_timestamp})"
            elif s.evidence_result_ids_json:
                try:
                    res_ids = json.loads(s.evidence_result_ids_json)
                    if isinstance(res_ids, list) and res_ids:
                        future_res = self.session.scalars(
                            select(AssessmentResult)
                            .where(AssessmentResult.result_id.in_(res_ids))
                            .where(AssessmentResult.graded_at > s.cutoff_timestamp)
                        ).all()
                        if future_res:
                            is_leaking = True
                            first = future_res[0]
                            reason = f"evidence result {first.result_id} graded at {first.graded_at} > cutoff"
                except (json.JSONDecodeError, TypeError):
                    pass

            if is_leaking:
                leakage_findings.append(
                    {
                        "snapshot_id": s.snapshot_id,
                        "reason": reason,
                    }
                )

        # b) Inspect lineage evaluations if passed from current evaluation batch
        if lineage_evaluations:
            leak_res: TemporalLeakageAuditResult = self.auditor.audit_temporal_leakage(
                lineage_evaluations
            )
            total_leak_checks += leak_res.total_evaluations
            leakage_findings.extend(leak_res.leakage_details)

        audits["future_mastery_leakage"] = AnomalyAuditResult(
            audit_name="FUTURE_MASTERY_LEAKAGE",
            anomaly_type="FUTURE_ATTEMPT_LEAKAGE",
            passed=len(leakage_findings) == 0,
            total_checked=total_leak_checks,
            violations_count=len(leakage_findings),
            details=leakage_findings,
        )

        # ---------------------------------------------------------------------
        # 5. Learning Path Loops Without Progress (A5)
        # ---------------------------------------------------------------------
        # Checks for:
        # a) Path loops: content_id reassigned at a later sequence_order while earlier is incomplete.
        # b) Direct circular prerequisites: A requires B and B requires A.
        # Limitation note: Detects duplicate incomplete sequential assignments and direct
        # mutual prerequisite cycles. Exhaustive arbitrary multi-hop cycle traversal is outside scope.
        loop_findings = []
        total_paths = self.session.scalar(select(func.count(LearningPathItem.path_item_id))) or 0

        path_items = self.session.scalars(
            select(LearningPathItem).order_by(
                LearningPathItem.path_id, LearningPathItem.sequence_order
            )
        ).all()

        paths_by_id: Dict[str, List[LearningPathItem]] = defaultdict(list)
        for item in path_items:
            paths_by_id[item.path_id].append(item)

        for path_id, items in paths_by_id.items():
            seen: Dict[str, Tuple[str, str, int]] = {}
            for item in items:
                if item.content_id in seen:
                    prev_id, prev_status, prev_seq = seen[item.content_id]
                    if prev_status != "COMPLETED":
                        loop_findings.append(
                            {
                                "path_id": path_id,
                                "path_item_id": item.path_item_id,
                                "content_id": item.content_id,
                                "sequence_order": item.sequence_order,
                                "earlier_sequence_order": prev_seq,
                                "earlier_status": prev_status,
                                "reason": (
                                    f"Content {item.content_id} reassigned at seq {item.sequence_order} "
                                    f"while seq {prev_seq} is incomplete (status='{prev_status}')"
                                ),
                            }
                        )
                else:
                    seen[item.content_id] = (
                        item.path_item_id,
                        item.status,
                        item.sequence_order,
                    )

        # Check direct circular prerequisites
        all_prereqs = self.session.scalars(select(SkillPrerequisite)).all()
        prereq_pairs = {(p.skill_id, p.prerequisite_skill_id) for p in all_prereqs}
        for s_id, pre_id in prereq_pairs:
            if (pre_id, s_id) in prereq_pairs and s_id < pre_id:
                loop_findings.append(
                    {
                        "type": "CIRCULAR_PREREQUISITE",
                        "skill_a": s_id,
                        "skill_b": pre_id,
                        "reason": f"Direct circular prerequisite dependency between {s_id} and {pre_id}",
                    }
                )

        audits["learning_path_loops"] = AnomalyAuditResult(
            audit_name="LEARNING_PATH_LOOPS",
            anomaly_type="LEARNING_PATH_LOOP",
            passed=len(loop_findings) == 0,
            total_checked=total_paths + len(all_prereqs),
            violations_count=len(loop_findings),
            details=loop_findings,
            metadata={
                "methodology_note": (
                    "Detects sequential duplicate assignments of incomplete content "
                    "and direct mutual prerequisite cycles."
                )
            },
        )

        return audits
