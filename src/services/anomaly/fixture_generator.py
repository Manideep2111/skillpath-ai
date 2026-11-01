"""Deterministic fixture generator for SkillPath AI anomaly evaluation.

Injects the five canonical SRS anomaly types into an isolated sandbox database
and outputs ground-truth labels to an external CSV file.
Strictly prohibits targeting or modifying the clean baseline database.
"""

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import csv
import json
import sqlite3
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.models.entities import (
    Attempt,
    LearningPathItem,
    MasterySnapshot,
    Recommendation,
)
from src.services.anomaly.sandbox_manager import (
    BASELINE_DB_PATH,
    DEFAULT_SANDBOX_PATH,
    SandboxManager,
    SandboxPathSecurityError,
)

DEFAULT_GROUND_TRUTH_PATH = Path("D:/SkillPathAI/data/ground_truth/anomaly_labels.csv").resolve()

# Canonical SRS Anomaly Types
ANOMALY_TYPE_A1 = "PREREQUISITE_VIOLATION"
ANOMALY_TYPE_A2 = "TIMESTAMP_ORDER_INVERSION"
ANOMALY_TYPE_A3 = "NONEXISTENT_SKILL_REFERENCE"
ANOMALY_TYPE_A4 = "FUTURE_ATTEMPT_LEAKAGE"
ANOMALY_TYPE_A5 = "LEARNING_PATH_LOOP"


class AnomalyFixtureGenerator:
    """Injects deterministic anomaly fixtures into an isolated sandbox database."""

    def __init__(
        self,
        sandbox_db_path: Path | str = DEFAULT_SANDBOX_PATH,
        ground_truth_csv_path: Path | str = DEFAULT_GROUND_TRUTH_PATH,
    ) -> None:
        self.sandbox_db_path = SandboxManager.assert_safe_destination(sandbox_db_path)
        self.ground_truth_csv_path = Path(ground_truth_csv_path).resolve()

        if not self.sandbox_db_path.exists():
            raise FileNotFoundError(
                f"Sandbox database not found at '{self.sandbox_db_path}'. "
                "Must initialize or clone sandbox before injecting fixtures."
            )

        self._injected_labels: list[dict[str, Any]] = []

    def inject_all(self) -> list[dict[str, Any]]:
        """Inject all 5 canonical anomaly types deterministically and idempotently.

        Returns:
            list[dict[str, Any]]: List of ground-truth label dictionaries.
        """
        self._injected_labels.clear()

        # A1: Prerequisite Violation
        self.inject_a1_prerequisite_violation()

        # A2: Timestamp Order Inversion
        self.inject_a2_timestamp_order_inversion()

        # A3: Nonexistent Skill Reference (FK orphan in content_skills)
        self.inject_a3_nonexistent_skill_reference()

        # A4: Future Attempt Leakage
        self.inject_a4_future_attempt_leakage()

        # A5: Learning Path Loop Without Progress
        self.inject_a5_learning_path_loop()

        # Save to ground-truth CSV file
        self.save_ground_truth_csv()

        return list(self._injected_labels)

    def inject_a1_prerequisite_violation(self) -> dict[str, Any]:
        """A1: Recommendation violates required prerequisite.

        Recommends CNT-000022 (teaches SKL-000004, which strictly requires SKL-000003 at 0.70)
        to cold-start learner LRN-000091 who has zero mastery.
        """
        rec_id = "REC-2026-999901"
        engine = create_engine(f"sqlite:///{self.sandbox_db_path.as_posix()}")
        with Session(engine) as session:
            existing = session.get(Recommendation, rec_id)
            if existing is None:
                rec = Recommendation(
                    recommendation_id=rec_id,
                    learner_id="LRN-000091",
                    content_id="CNT-000022",
                    target_skill_id="SKL-000004",
                    decision_timestamp=datetime(2026, 1, 15, 10, 0, 0),
                    rank_position=1,
                    recommendation_score=Decimal("0.9500"),
                    primary_reason_code="FIXTURE_A1_INJECTION",
                    score_components_json=json.dumps({"readiness": 0.95}),
                    rejection_audit_json=json.dumps({"violations_bypassed": True}),
                    algorithm_version="v1.2.0-fixture",
                )
                session.add(rec)
                session.commit()

        label = {
            "anomaly_id": "ANOM-001",
            "anomaly_type": ANOMALY_TYPE_A1,
            "entity_type": "Recommendation",
            "entity_id": rec_id,
            "severity": "HIGH",
            "description": "Recommendation REC-2026-999901 for LRN-000091 violates prerequisite SKL-000003 (required 0.70, actual 0.00)",
            "injected_at": datetime.now(timezone.utc).isoformat(),
        }
        self._injected_labels.append(label)
        return label

    def inject_a2_timestamp_order_inversion(self) -> dict[str, Any]:
        """A2: Attempt timestamp order is invalid (completed_at < started_at).

        Attempt ATT-999901 has started_at=14:00 and completed_at=13:00.
        """
        att_id = "ATT-999901"
        engine = create_engine(f"sqlite:///{self.sandbox_db_path.as_posix()}")
        with Session(engine) as session:
            existing = session.get(Attempt, att_id)
            if existing is None:
                attempt = Attempt(
                    attempt_id=att_id,
                    learner_id="LRN-000001",
                    content_id="CNT-000001",
                    attempt_number=99,
                    started_at=datetime(2026, 2, 1, 14, 0, 0),
                    completed_at=datetime(2026, 2, 1, 13, 0, 0),  # Inversion
                    time_spent_seconds=1800,
                    status="COMPLETED",
                )
                session.add(attempt)
                session.commit()

        label = {
            "anomaly_id": "ANOM-002",
            "anomaly_type": ANOMALY_TYPE_A2,
            "entity_type": "Attempt",
            "entity_id": att_id,
            "severity": "HIGH",
            "description": "Attempt ATT-999901 completed_at (2026-02-01 13:00) is earlier than started_at (2026-02-01 14:00)",
            "injected_at": datetime.now(timezone.utc).isoformat(),
        }
        self._injected_labels.append(label)
        return label

    def inject_a3_nonexistent_skill_reference(self) -> dict[str, Any]:
        """A3: Content references a nonexistent skill.

        Inserts orphan row ('CNT-000001', 'SKL-999999', 1.0) into content_skills.
        Executed with PRAGMA foreign_keys = OFF only on the isolated sandbox connection.
        """
        conn = sqlite3.connect(self.sandbox_db_path.as_posix())
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT count(*) FROM content_skills WHERE content_id = 'CNT-000001' AND skill_id = 'SKL-999999';"
            )
            count = cursor.fetchone()[0]
            if count == 0:
                conn.execute("PRAGMA foreign_keys = OFF;")
                conn.execute(
                    "INSERT INTO content_skills (content_id, skill_id, relevance_weight) VALUES (?, ?, ?);",
                    ("CNT-000001", "SKL-999999", 1.0),
                )
                conn.commit()
                conn.execute("PRAGMA foreign_keys = ON;")
        finally:
            conn.close()

        label = {
            "anomaly_id": "ANOM-003",
            "anomaly_type": ANOMALY_TYPE_A3,
            "entity_type": "ContentSkill",
            "entity_id": "CNT-000001:SKL-999999",
            "severity": "CRITICAL",
            "description": "ContentSkill references non-existent skill SKL-999999 for content CNT-000001",
            "injected_at": datetime.now(timezone.utc).isoformat(),
        }
        self._injected_labels.append(label)
        return label

    def inject_a4_future_attempt_leakage(self) -> dict[str, Any]:
        """A4: Mastery snapshot uses an assessment graded in the future relative to cutoff.

        Snapshot SNP-999901 cutoff is 2026-01-01, but max_evidence_graded_at is 2026-01-10.
        """
        snp_id = "SNP-999901"
        engine = create_engine(f"sqlite:///{self.sandbox_db_path.as_posix()}")
        with Session(engine) as session:
            existing = session.get(MasterySnapshot, snp_id)
            if existing is None:
                snapshot = MasterySnapshot(
                    snapshot_id=snp_id,
                    learner_id="LRN-000001",
                    skill_id="SKL-000001",
                    mastery_level=Decimal("0.8500"),
                    evidence_count=1,
                    confidence_score=Decimal("0.9000"),
                    cutoff_timestamp=datetime(2026, 1, 1, 0, 0, 0),
                    max_evidence_graded_at=datetime(2026, 1, 10, 0, 0, 0),  # 9 days in future!
                    evidence_result_ids_json=json.dumps(["RES-000001"]),
                    algorithm_version="v1.2.0-fixture",
                    calculated_at=datetime(2026, 1, 10, 1, 0, 0),
                )
                session.add(snapshot)
                session.commit()

        label = {
            "anomaly_id": "ANOM-004",
            "anomaly_type": ANOMALY_TYPE_A4,
            "entity_type": "MasterySnapshot",
            "entity_id": snp_id,
            "severity": "CRITICAL",
            "description": "Mastery snapshot SNP-999901 max_evidence_graded_at (2026-01-10) exceeds cutoff_timestamp (2026-01-01)",
            "injected_at": datetime.now(timezone.utc).isoformat(),
        }
        self._injected_labels.append(label)
        return label

    def inject_a5_learning_path_loop(self) -> dict[str, Any]:
        """A5: Learning path loops without progress.

        Path PATH-2026-000001 already has CNT-000030 at sequence 1 with status 'IN_PROGRESS'.
        Injects duplicate CNT-000030 at sequence 99 with status 'PENDING'.
        """
        lpi_id = "LPI-PATH-2026-000001-099"
        engine = create_engine(f"sqlite:///{self.sandbox_db_path.as_posix()}")
        with Session(engine) as session:
            existing = session.get(LearningPathItem, lpi_id)
            if existing is None:
                item = LearningPathItem(
                    path_item_id=lpi_id,
                    path_id="PATH-2026-000001",
                    content_id="CNT-000030",
                    sequence_order=99,
                    is_mandatory=True,
                    status="PENDING",
                    completed_at=None,
                )
                session.add(item)
                session.commit()

        label = {
            "anomaly_id": "ANOM-005",
            "anomaly_type": ANOMALY_TYPE_A5,
            "entity_type": "LearningPathItem",
            "entity_id": lpi_id,
            "severity": "MEDIUM",
            "description": "Learning path PATH-2026-000001 re-schedules CNT-000030 at sequence 99 while sequence 1 is incomplete (IN_PROGRESS)",
            "injected_at": datetime.now(timezone.utc).isoformat(),
        }
        self._injected_labels.append(label)
        return label

    def save_ground_truth_csv(self, labels: list[dict[str, Any]] | None = None) -> Path:
        """Write ground-truth labels to external CSV file."""
        target_labels = labels if labels is not None else self._injected_labels
        self.ground_truth_csv_path.parent.mkdir(parents=True, exist_ok=True)

        fieldnames = [
            "anomaly_id",
            "anomaly_type",
            "entity_type",
            "entity_id",
            "severity",
            "description",
            "injected_at",
        ]

        with open(self.ground_truth_csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in target_labels:
                writer.writerow(row)

        return self.ground_truth_csv_path
