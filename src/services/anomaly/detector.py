"""Anomaly detection service for SkillPath AI.

Detects the five canonical SRS anomaly types:
A1. PREREQUISITE_VIOLATION: Recommendation violates required prerequisite.
A2. TIMESTAMP_ORDER_INVERSION: Attempt timestamp order is invalid.
A3. NONEXISTENT_SKILL_REFERENCE: Content references nonexistent skill in content_skills.
A4. FUTURE_ATTEMPT_LEAKAGE: Mastery snapshot incorporates future evidence after cutoff.
A5. LEARNING_PATH_LOOP: Learning path loops without progress on incomplete content.

Records findings deterministically and idempotently into the data_issues table
in the sandbox database only.
"""

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.entities import (
    AssessmentResult,
    Attempt,
    ContentSkill,
    DataIssue,
    LearningPathItem,
    MasterySnapshot,
    Recommendation,
    Skill,
    SkillPrerequisite,
)
from src.services.anomaly.fixture_generator import (
    ANOMALY_TYPE_A1,
    ANOMALY_TYPE_A2,
    ANOMALY_TYPE_A3,
    ANOMALY_TYPE_A4,
    ANOMALY_TYPE_A5,
)
from src.services.anomaly.sandbox_manager import (
    BASELINE_DB_PATH,
    SandboxPathSecurityError,
)
from src.services.mastery_service import MasteryService

logger = logging.getLogger(__name__)


def generate_issue_id(anomaly_type: str, entity_type: str, entity_id: str) -> str:
    """Generate a deterministic, 24-character issue ID from finding coordinates."""
    payload = f"{anomaly_type}:{entity_type}:{entity_id}".encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()[:20]
    return f"ISS-{digest}"


class AnomalyDetectionService:
    """Scans databases for data anomalies and records issues idempotently."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.mastery_service = MasteryService(session)

    def detect_all(self) -> list[DataIssue]:
        """Run detection for all five canonical SRS anomaly types.

        Returns:
            list[DataIssue]: List of all detected DataIssue model instances.
        """
        all_issues: list[DataIssue] = []
        all_issues.extend(self.detect_a1_prerequisite_violations())
        all_issues.extend(self.detect_a2_timestamp_order_inversions())
        all_issues.extend(self.detect_a3_nonexistent_skill_references())
        all_issues.extend(self.detect_a4_future_attempt_leakage())
        all_issues.extend(self.detect_a5_learning_path_loops())
        return all_issues

    def detect_a1_prerequisite_violations(self) -> list[DataIssue]:
        """A1: Recommendation violates required prerequisite.

        Checks each recommendation against required prerequisites at decision_timestamp.
        If the learner has unknown mastery or mastery below minimum_mastery, flags issue.
        """
        issues: list[DataIssue] = []
        recommendations = self.session.scalars(select(Recommendation)).all()

        for rec in recommendations:
            # Gather required prerequisites for the recommendation's target skill
            # and any skills taught by the recommended content
            skill_ids_to_check = set()
            if rec.target_skill_id:
                skill_ids_to_check.add(rec.target_skill_id)

            content_skills = self.session.scalars(
                select(ContentSkill).where(ContentSkill.content_id == rec.content_id)
            ).all()
            for cs in content_skills:
                if cs.relevance_weight > 0:
                    skill_ids_to_check.add(cs.skill_id)

            if not skill_ids_to_check:
                continue

            prereqs = self.session.scalars(
                select(SkillPrerequisite).where(
                    SkillPrerequisite.skill_id.in_(skill_ids_to_check),
                    SkillPrerequisite.is_required.is_(True),
                )
            ).all()

            for p in prereqs:
                mastery, count, _, _, _ = self.mastery_service.compute_mastery(
                    rec.learner_id, p.prerequisite_skill_id, rec.decision_timestamp
                )
                if mastery is None or mastery < p.minimum_mastery:
                    issue_id = generate_issue_id(ANOMALY_TYPE_A1, "Recommendation", rec.recommendation_id)
                    actual_desc = f"{mastery:.2f}" if mastery is not None else "UNKNOWN"
                    desc = (
                        f"Recommendation {rec.recommendation_id} for learner {rec.learner_id} "
                        f"violates required prerequisite {p.prerequisite_skill_id} "
                        f"(required {p.minimum_mastery}, actual {actual_desc})"
                    )
                    issues.append(
                        DataIssue(
                            issue_id=issue_id,
                            anomaly_type=ANOMALY_TYPE_A1,
                            severity="HIGH",
                            entity_type="Recommendation",
                            entity_id=rec.recommendation_id,
                            description=desc,
                            detected_at=datetime.now(timezone.utc),
                            quarantine_status="FLAGGED",
                        )
                    )
                    break  # Flag once per recommendation

        return issues

    def detect_a2_timestamp_order_inversions(self) -> list[DataIssue]:
        """A2: Attempt timestamp order is invalid.

        Detects:
        1. completed_at < started_at
        2. AssessmentResult graded_at < Attempt completed_at
        3. Attempt status IN_PROGRESS with non-null completed_at
        """
        issues: list[DataIssue] = []

        # 1. completed_at < started_at
        inverted_attempts = self.session.scalars(
            select(Attempt)
            .where(Attempt.completed_at.is_not(None))
            .where(Attempt.completed_at < Attempt.started_at)
        ).all()

        for att in inverted_attempts:
            issue_id = generate_issue_id(ANOMALY_TYPE_A2, "Attempt", att.attempt_id)
            desc = (
                f"Attempt {att.attempt_id} completed_at ({att.completed_at}) "
                f"is earlier than started_at ({att.started_at})"
            )
            issues.append(
                DataIssue(
                    issue_id=issue_id,
                    anomaly_type=ANOMALY_TYPE_A2,
                    severity="HIGH",
                    entity_type="Attempt",
                    entity_id=att.attempt_id,
                    description=desc,
                    detected_at=datetime.now(timezone.utc),
                    quarantine_status="FLAGGED",
                )
            )

        # 2. AssessmentResult graded_at < Attempt completed_at
        premature_assessments = self.session.scalars(
            select(AssessmentResult)
            .join(Attempt, AssessmentResult.attempt_id == Attempt.attempt_id)
            .where(Attempt.completed_at.is_not(None))
            .where(AssessmentResult.graded_at < Attempt.completed_at)
        ).all()

        for res in premature_assessments:
            issue_id = generate_issue_id(ANOMALY_TYPE_A2, "AssessmentResult", res.result_id)
            desc = f"AssessmentResult {res.result_id} graded_at ({res.graded_at}) is earlier than attempt completion"
            issues.append(
                DataIssue(
                    issue_id=issue_id,
                    anomaly_type=ANOMALY_TYPE_A2,
                    severity="HIGH",
                    entity_type="AssessmentResult",
                    entity_id=res.result_id,
                    description=desc,
                    detected_at=datetime.now(timezone.utc),
                    quarantine_status="FLAGGED",
                )
            )

        # 3. Attempt IN_PROGRESS with non-null completed_at
        invalid_in_progress = self.session.scalars(
            select(Attempt)
            .where(Attempt.status == "IN_PROGRESS")
            .where(Attempt.completed_at.is_not(None))
        ).all()

        for att in invalid_in_progress:
            issue_id = generate_issue_id(ANOMALY_TYPE_A2, "Attempt", att.attempt_id)
            desc = f"Attempt {att.attempt_id} has status IN_PROGRESS but non-null completed_at ({att.completed_at})"
            issues.append(
                DataIssue(
                    issue_id=issue_id,
                    anomaly_type=ANOMALY_TYPE_A2,
                    severity="HIGH",
                    entity_type="Attempt",
                    entity_id=att.attempt_id,
                    description=desc,
                    detected_at=datetime.now(timezone.utc),
                    quarantine_status="FLAGGED",
                )
            )

        return issues

    def detect_a3_nonexistent_skill_references(self) -> list[DataIssue]:
        """A3: Content references a nonexistent skill.

        Checks content_skills for references to skill_ids that do not exist in the skills table.
        """
        issues: list[DataIssue] = []

        orphan_rows = self.session.execute(
            select(ContentSkill.content_id, ContentSkill.skill_id)
            .outerjoin(Skill, ContentSkill.skill_id == Skill.skill_id)
            .where(Skill.skill_id.is_(None))
        ).all()

        for content_id, skill_id in orphan_rows:
            entity_id = f"{content_id}:{skill_id}"
            issue_id = generate_issue_id(ANOMALY_TYPE_A3, "ContentSkill", entity_id)
            desc = f"ContentSkill references non-existent skill {skill_id} for content {content_id}"
            issues.append(
                DataIssue(
                    issue_id=issue_id,
                    anomaly_type=ANOMALY_TYPE_A3,
                    severity="CRITICAL",
                    entity_type="ContentSkill",
                    entity_id=entity_id,
                    description=desc,
                    detected_at=datetime.now(timezone.utc),
                    quarantine_status="FLAGGED",
                )
            )

        return issues

    def detect_a4_future_attempt_leakage(self) -> list[DataIssue]:
        """A4: Mastery snapshot uses an assessment graded in the future relative to cutoff.

        Detects:
        1. max_evidence_graded_at > cutoff_timestamp
        2. An evidence result in evidence_result_ids_json has AssessmentResult.graded_at > cutoff_timestamp
        """
        issues: list[DataIssue] = []
        snapshots = self.session.scalars(select(MasterySnapshot)).all()

        for s in snapshots:
            is_leaking = False
            leak_reason = ""

            # Check max_evidence_graded_at
            if s.max_evidence_graded_at is not None and s.max_evidence_graded_at > s.cutoff_timestamp:
                is_leaking = True
                leak_reason = (
                    f"max_evidence_graded_at ({s.max_evidence_graded_at}) > "
                    f"cutoff_timestamp ({s.cutoff_timestamp})"
                )

            # Check individual evidence results if not already flagged
            if not is_leaking and s.evidence_result_ids_json:
                try:
                    result_ids = json.loads(s.evidence_result_ids_json)
                    if isinstance(result_ids, list) and result_ids:
                        future_results = self.session.scalars(
                            select(AssessmentResult)
                            .where(AssessmentResult.result_id.in_(result_ids))
                            .where(AssessmentResult.graded_at > s.cutoff_timestamp)
                        ).all()
                        if future_results:
                            is_leaking = True
                            first = future_results[0]
                            leak_reason = (
                                f"evidence result {first.result_id} graded_at ({first.graded_at}) "
                                f"> cutoff_timestamp ({s.cutoff_timestamp})"
                            )
                except (json.JSONDecodeError, TypeError) as exc:
                    logger.warning(
                        "Malformed evidence_result_ids_json in snapshot %s: %s",
                        s.snapshot_id,
                        exc,
                    )

            if is_leaking:
                issue_id = generate_issue_id(ANOMALY_TYPE_A4, "MasterySnapshot", s.snapshot_id)
                desc = f"Mastery snapshot {s.snapshot_id} incorporates future evidence: {leak_reason}"
                issues.append(
                    DataIssue(
                        issue_id=issue_id,
                        anomaly_type=ANOMALY_TYPE_A4,
                        severity="CRITICAL",
                        entity_type="MasterySnapshot",
                        entity_id=s.snapshot_id,
                        description=desc,
                        detected_at=datetime.now(timezone.utc),
                        quarantine_status="FLAGGED",
                    )
                )

        return issues

    def detect_a5_learning_path_loops(self) -> list[DataIssue]:
        """A5: Learning path loops without progress.

        Detects paths where the same content_id is assigned again at a later sequence_order
        while the earlier instance has status != 'COMPLETED'.
        """
        issues: list[DataIssue] = []

        path_items = self.session.scalars(
            select(LearningPathItem).order_by(
                LearningPathItem.path_id, LearningPathItem.sequence_order
            )
        ).all()

        paths_dict: dict[str, list[LearningPathItem]] = defaultdict(list)
        for item in path_items:
            paths_dict[item.path_id].append(item)

        for path_id, items in paths_dict.items():
            seen_content: dict[str, tuple[str, str, int]] = {}
            for item in items:
                if item.content_id in seen_content:
                    prev_id, prev_status, prev_seq = seen_content[item.content_id]
                    if prev_status != "COMPLETED":
                        issue_id = generate_issue_id(
                            ANOMALY_TYPE_A5, "LearningPathItem", item.path_item_id
                        )
                        desc = (
                            f"Learning path {path_id} re-assigns content {item.content_id} "
                            f"at sequence {item.sequence_order} while earlier sequence {prev_seq} "
                            f"({prev_id}) is incomplete (status='{prev_status}')"
                        )
                        issues.append(
                            DataIssue(
                                issue_id=issue_id,
                                anomaly_type=ANOMALY_TYPE_A5,
                                severity="MEDIUM",
                                entity_type="LearningPathItem",
                                entity_id=item.path_item_id,
                                description=desc,
                                detected_at=datetime.now(timezone.utc),
                                quarantine_status="FLAGGED",
                            )
                        )
                else:
                    seen_content[item.content_id] = (
                        item.path_item_id,
                        item.status,
                        item.sequence_order,
                    )

        return issues

    def record_issues(self, issues: list[DataIssue]) -> int:
        """Persist newly detected issues into the data_issues table idempotently.

        Strictly rejects recording to the clean baseline database.

        Args:
            issues: List of DataIssue objects to record.

        Returns:
            int: Number of new issues inserted.

        Raises:
            SandboxPathSecurityError: If session is connected to baseline database.
        """
        # Hard path security assertion
        bind_url = str(self.session.get_bind().url)
        baseline_str = os.path.normcase(str(BASELINE_DB_PATH.resolve()))
        normalized_url = os.path.normcase(bind_url)

        if baseline_str in normalized_url or (
            "skillpath.db" in normalized_url and "sandbox" not in normalized_url
        ):
            raise SandboxPathSecurityError(
                "CRITICAL SAFETY VIOLATION: Refusing to record data issues to clean baseline database! "
                "Issues may only be written to sandbox or test databases."
            )

        new_count = 0
        for issue in issues:
            existing = self.session.get(DataIssue, issue.issue_id)
            if existing is None:
                self.session.add(issue)
                new_count += 1

        self.session.commit()
        return new_count
