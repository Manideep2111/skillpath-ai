"""Read-only database validation script for SkillPath AI (Development Dataset).

Validates:
1. Configured URL contract (strictly 'sqlite:///./skillpath.db' for this milestone)
   and physical file resolution matching D:\\SkillPathAI\\skillpath.db.
2. Schema presence for all 15 ORM tables using a read-only engine.
3. Development dataset row counts across all tables.
4. Exactly 10 cold-start learners with zero attempts.
5. Foreign-key referential integrity and orphan checks across all 11 relationships.
6. Attempt and assessment lifecycle timestamps.
7. Assessment score arithmetic and ratio tolerance (0.0001).
8. Prerequisite DAG acyclicity, self-prerequisite absence, and observed depth.
9. Learning-path sequence uniqueness and lifecycle states.
10. Supporting table cleanliness (0 rows) and absence of ground_truth_label in data_issues.

SAFETY GUARANTEE:
Enforces read-only database connections via SQLite 'PRAGMA query_only = ON;'.
Executes zero DDL or DML statements.
"""

from collections import defaultdict, deque
from datetime import datetime
import os
from pathlib import Path
import sys
import traceback
from typing import Any, Dict, List, Set, Tuple
from sqlalchemy import create_engine, event, func, inspect, select, table, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.core.config import settings
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
    MasterySnapshot,
    Recommendation,
    RecommendationOutcome,
    AuditEvent,
    DataIssue,
)

# Explicit target contracts for Milestone 2 Development Dataset
EXPECTED_DATABASE_URL = "sqlite:///./skillpath.db"
PROJECT_ROOT = Path(r"D:\SkillPathAI").resolve()
EXPECTED_DB_PATH = (PROJECT_ROOT / "skillpath.db").resolve()

# Expected development profile counts for the current baseline dataset
EXPECTED_BASELINE_COUNTS: Dict[str, int] = {
    "learners": 100,
    "courses": 10,
    "skills": 50,
    "content_items": 100,
    "attempts": 2000,
    "learning_paths": 80,
    "learning_path_items": 670,
    "assessment_results": 705,
    "skill_prerequisites": 29,
    "content_skills": 193,
    "mastery_snapshots": 0,
    "recommendations": 0,
    "recommendation_outcomes": 0,
    "audit_events": 0,
    "data_issues": 0,
}

ALL_15_TABLES = list(EXPECTED_BASELINE_COUNTS.keys())


def create_readonly_engine(db_path: Path) -> Engine:
    """Create an isolated SQLAlchemy engine enforcing SQLite read-only mode."""
    engine_url = f"sqlite:///{db_path.as_posix()}"
    ro_engine = create_engine(engine_url, connect_args={"check_same_thread": False})

    @event.listens_for(ro_engine, "connect")
    def set_sqlite_readonly(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        try:
            # Native SQLite driver enforcement: blocks all writes, modifications, and DDL
            cursor.execute("PRAGMA query_only = ON;")
            cursor.execute("PRAGMA foreign_keys = ON;")
        finally:
            cursor.close()

    return ro_engine


class ValidationReporter:
    """Collects, categorizes, and formats validation results."""

    def __init__(self) -> None:
        self.results: List[Dict[str, Any]] = []
        self.failed_categories: Set[str] = set()
        self.warning_categories: Set[str] = set()

    def record(self, category: str, check_name: str, status: str, details: str = "") -> None:
        """Record an individual check outcome."""
        if status == "FAIL":
            self.failed_categories.add(category)
        elif status == "WARNING":
            self.warning_categories.add(category)

        self.results.append({
            "category": category,
            "check": check_name,
            "status": status,
            "details": details.strip(),
        })

    def print_report(self, physical_path: Path, access_mode: str) -> None:
        """Render a structured summary report to stdout."""
        print("=" * 80)
        print("SKILLPATH AI — DATABASE AUDIT & DATASET VALIDATION REPORT")
        print("=" * 80)
        print(f"Target Database File : {physical_path}")
        print(f"Driver Enforcement   : {access_mode}")
        print(f"Validation Timestamp : {datetime.utcnow().isoformat()}Z")
        print("-" * 80)

        current_category = None
        for res in self.results:
            if res["category"] != current_category:
                current_category = res["category"]
                print(f"\n[{current_category}]")

            badge = f"[{res['status']}]"
            print(f"  {badge:<9} {res['check']}")
            if res["details"]:
                for line in res["details"].split("\n"):
                    print(f"            {line}")

        print("\n" + "=" * 80)
        print("VALIDATION SUMMARY")
        print("=" * 80)
        total_checks = len(self.results)
        fails = sum(1 for r in self.results if r["status"] == "FAIL")
        warnings = sum(1 for r in self.results if r["status"] == "WARNING")
        passes = sum(1 for r in self.results if r["status"] == "PASS")

        print(f"Total Checks Executed : {total_checks}")
        print(f"Checks Passed         : {passes}")
        print(f"Warnings Logged       : {warnings}")
        print(f"Failed Checks         : {fails}")
        print("-" * 80)
        overall = "FAILED" if fails > 0 else ("PASSED WITH WARNINGS" if warnings > 0 else "PASSED")
        print(f"OVERALL VALIDATION STATUS: {overall}")
        print("=" * 80)


# ============================================================================
# VALIDATION MODULES (STRICTLY READ-ONLY)
# ============================================================================

def validate_database_and_schema(ro_engine: Engine, reporter: ValidationReporter) -> None:
    """A. Database and Schema: verify dialect, physical file match, and table completeness."""
    cat = "A. Database and Schema"

    # 1. Dialect verification
    if ro_engine.dialect.name != "sqlite":
        reporter.record(cat, "Dialect Check", "FAIL", f"Expected 'sqlite', found '{ro_engine.dialect.name}'")
        return
    reporter.record(cat, "Dialect Check", "PASS", "Active dialect is SQLite")

    # 2. Physical database target verification via PRAGMA database_list on read-only connection
    resolved_path = None
    with ro_engine.connect() as conn:
        rows = conn.execute(text("PRAGMA database_list;")).fetchall()
        for r in rows:
            if len(r) >= 3 and r[1] == "main" and r[2]:
                resolved_path = Path(r[2]).resolve()
                break

    if not resolved_path:
        reporter.record(cat, "Physical File Resolution", "FAIL", "Could not resolve physical database path via PRAGMA")
        return

    if os.path.normcase(str(resolved_path)) != os.path.normcase(str(EXPECTED_DB_PATH)):
        reporter.record(
            cat,
            "Physical File Match",
            "FAIL",
            f"Physical path '{resolved_path}' does not match expected '{EXPECTED_DB_PATH}'",
        )
        return
    reporter.record(cat, "Physical File Match", "PASS", f"Connected directly to {resolved_path}")

    # 3. Table existence check
    inspector = inspect(ro_engine)
    existing_tables = set(inspector.get_table_names())
    missing_tables = set(ALL_15_TABLES) - existing_tables
    unexpected_tables = existing_tables - set(ALL_15_TABLES)

    if missing_tables:
        reporter.record(cat, "Schema Completeness", "FAIL", f"Missing expected tables: {sorted(missing_tables)}")
    elif unexpected_tables:
        reporter.record(cat, "Schema Completeness", "WARNING", f"Unexpected extra tables: {sorted(unexpected_tables)}")
    else:
        reporter.record(cat, "Schema Completeness", "PASS", "All 15 expected ORM tables exist in schema")

    # 4. Report actual row counts for every table and verify queries succeed
    table_counts: List[str] = []
    count_errors: List[str] = []

    with ro_engine.connect() as conn:
        for tbl in sorted(existing_tables):
            try:
                cnt = conn.scalar(select(func.count()).select_from(table(tbl)))
                table_counts.append(f"{tbl}: {cnt} rows")
            except Exception as e:
                err_msg = f"{tbl}: count query error ({e})"
                table_counts.append(err_msg)
                count_errors.append(err_msg)

    if count_errors:
        reporter.record(
            cat,
            "Schema Table Row Counts",
            "FAIL",
            "Count query failed for table(s):\n" + "\n".join(count_errors),
        )
    else:
        reporter.record(cat, "Schema Table Row Counts", "PASS", "\n".join(table_counts))


def validate_dataset_acceptance_counts(ro_engine: Engine, reporter: ValidationReporter) -> None:
    """B. Dataset Acceptance Criteria: verify actual counts against development targets."""
    cat = "B. Dataset Acceptance Criteria"
    inspector = inspect(ro_engine)
    existing_tables = set(inspector.get_table_names())

    mismatches = []
    matches = []
    with ro_engine.connect() as conn:
        for tbl, expected in EXPECTED_BASELINE_COUNTS.items():
            if tbl not in existing_tables:
                mismatches.append(f"{tbl}: table missing (expected {expected})")
                continue
            actual = conn.scalar(select(func.count()).select_from(table(tbl)))
            if actual != expected:
                mismatches.append(f"{tbl}: actual={actual}, expected={expected}")
            else:
                matches.append(f"{tbl}={actual}")

    if mismatches:
        reporter.record(
            cat,
            "Development Profile Row Counts",
            "FAIL",
            "Count discrepancies detected:\n" + "\n".join(mismatches),
        )
    else:
        summary_str = ", ".join(matches[:5]) + ", ..."
        reporter.record(
            cat,
            "Development Profile Row Counts",
            "PASS",
            f"All 15 tables match expected development baseline counts ({summary_str})",
        )


def validate_cold_start_learners(session: Session, reporter: ValidationReporter) -> None:
    """C. Cold-Start Learners: verify exactly 10 learners have zero historical attempts."""
    cat = "C. Cold-Start Learners"

    all_learners = set(session.scalars(select(Learner.learner_id)).all())
    active_learners = set(session.scalars(select(Attempt.learner_id.distinct())).all())

    cold_start_ids = sorted(list(all_learners - active_learners))
    actual_count = len(cold_start_ids)

    if actual_count == 10:
        details = f"Verified exactly 10 cold-start learners with zero attempts:\nIDs: {', '.join(cold_start_ids)}"
        reporter.record(cat, "Cold-Start Learner Count", "PASS", details)
    else:
        reporter.record(
            cat,
            "Cold-Start Learner Count",
            "FAIL",
            f"Expected exactly 10 cold-start learners, found {actual_count}. IDs: {cold_start_ids}",
        )


def validate_referential_integrity(ro_engine: Engine, session: Session, reporter: ValidationReporter) -> None:
    """D. Referential Integrity: run SQLite foreign-key check and scan all 11 relationships for orphans."""
    cat = "D. Referential Integrity"

    # 1. Native SQLite foreign-key engine check
    with ro_engine.connect() as conn:
        violations = conn.execute(text("PRAGMA foreign_key_check;")).fetchall()

    if violations:
        lines = [f"Table '{v[0]}', rowid {v[1]} references missing parent '{v[2]}'" for v in violations[:10]]
        reporter.record(cat, "PRAGMA foreign_key_check", "FAIL", f"Found {len(violations)} violations:\n" + "\n".join(lines))
    else:
        reporter.record(cat, "PRAGMA foreign_key_check", "PASS", "SQLite foreign_key_check reported 0 violations")

    # 2. Check all 11 relationships for orphan records
    orphan_checks: List[Tuple[str, str, Any]] = [
        ("content_items", "course_id -> courses.course_id",
         select(func.count(ContentItem.content_id)).outerjoin(Course, ContentItem.course_id == Course.course_id).where(Course.course_id.is_(None))),
        ("skill_prerequisites", "skill_id -> skills.skill_id",
         select(func.count(SkillPrerequisite.skill_id)).outerjoin(Skill, SkillPrerequisite.skill_id == Skill.skill_id).where(Skill.skill_id.is_(None))),
        ("skill_prerequisites", "prerequisite_skill_id -> skills.skill_id",
         select(func.count(SkillPrerequisite.skill_id)).outerjoin(Skill, SkillPrerequisite.prerequisite_skill_id == Skill.skill_id).where(Skill.skill_id.is_(None))),
        ("content_skills", "content_id -> content_items.content_id",
         select(func.count(ContentSkill.content_id)).outerjoin(ContentItem, ContentSkill.content_id == ContentItem.content_id).where(ContentItem.content_id.is_(None))),
        ("content_skills", "skill_id -> skills.skill_id",
         select(func.count(ContentSkill.skill_id)).outerjoin(Skill, ContentSkill.skill_id == Skill.skill_id).where(Skill.skill_id.is_(None))),
        ("attempts", "learner_id -> learners.learner_id",
         select(func.count(Attempt.attempt_id)).outerjoin(Learner, Attempt.learner_id == Learner.learner_id).where(Learner.learner_id.is_(None))),
        ("attempts", "content_id -> content_items.content_id",
         select(func.count(Attempt.attempt_id)).outerjoin(ContentItem, Attempt.content_id == ContentItem.content_id).where(ContentItem.content_id.is_(None))),
        ("assessment_results", "attempt_id -> attempts.attempt_id",
         select(func.count(AssessmentResult.result_id)).outerjoin(Attempt, AssessmentResult.attempt_id == Attempt.attempt_id).where(Attempt.attempt_id.is_(None))),
        ("learning_paths", "learner_id -> learners.learner_id",
         select(func.count(LearningPath.path_id)).outerjoin(Learner, LearningPath.learner_id == Learner.learner_id).where(Learner.learner_id.is_(None))),
        ("learning_path_items", "path_id -> learning_paths.path_id",
         select(func.count(LearningPathItem.path_item_id)).outerjoin(LearningPath, LearningPathItem.path_id == LearningPath.path_id).where(LearningPath.path_id.is_(None))),
        ("learning_path_items", "content_id -> content_items.content_id",
         select(func.count(LearningPathItem.path_item_id)).outerjoin(ContentItem, LearningPathItem.content_id == ContentItem.content_id).where(ContentItem.content_id.is_(None))),
    ]

    orphan_failures = []
    for tbl, rel_desc, query in orphan_checks:
        cnt = session.scalar(query)
        if cnt and cnt > 0:
            orphan_failures.append(f"Table '{tbl}' ({rel_desc}): {cnt} orphan records")

    if orphan_failures:
        reporter.record(cat, "Orphan Record Analysis", "FAIL", "\n".join(orphan_failures))
    else:
        reporter.record(cat, "Orphan Record Analysis", "PASS", "Verified zero orphans across all 11 foreign-key relationships")


def validate_timestamp_integrity(session: Session, reporter: ValidationReporter) -> None:
    """E. Timestamp Integrity: verify chronological ordering and lifecycle timestamp rules."""
    cat = "E. Timestamp Integrity"

    # Rule 1: Any attempt with a completed_at timestamp must have completed_at >= started_at
    inverted_attempts = session.execute(
        select(Attempt.attempt_id, Attempt.started_at, Attempt.completed_at)
        .where(Attempt.completed_at.is_not(None))
        .where(Attempt.completed_at < Attempt.started_at)
    ).all()

    # Rule 2: COMPLETED attempts must have completed_at is not None
    missing_completed_at = session.execute(
        select(Attempt.attempt_id, Attempt.status)
        .where(Attempt.status == "COMPLETED")
        .where(Attempt.completed_at.is_(None))
    ).all()

    # Rule 3: IN_PROGRESS attempts must not have a completed_at timestamp
    invalid_in_progress = session.execute(
        select(Attempt.attempt_id, Attempt.status, Attempt.completed_at)
        .where(Attempt.status == "IN_PROGRESS")
        .where(Attempt.completed_at.is_not(None))
    ).all()

    # Rule 4: Assessment results must be graded at or after attempt completion
    premature_assessments = session.execute(
        select(AssessmentResult.result_id, AssessmentResult.graded_at, Attempt.completed_at)
        .join(Attempt, AssessmentResult.attempt_id == Attempt.attempt_id)
        .where(Attempt.completed_at.is_not(None))
        .where(AssessmentResult.graded_at < Attempt.completed_at)
    ).all()

    issues = []
    if inverted_attempts:
        issues.append(f"{len(inverted_attempts)} attempts have completed_at < started_at")
    if missing_completed_at:
        issues.append(f"{len(missing_completed_at)} COMPLETED attempts have completed_at=None")
    if invalid_in_progress:
        issues.append(f"{len(invalid_in_progress)} IN_PROGRESS attempts have a non-null completed_at")
    if premature_assessments:
        issues.append(f"{len(premature_assessments)} assessment results have graded_at earlier than attempt completed_at")

    if issues:
        reporter.record(cat, "Lifecycle Timestamp Invariants", "FAIL", "\n".join(issues))
    else:
        reporter.record(
            cat,
            "Lifecycle Timestamp Invariants",
            "PASS",
            "All attempts satisfy started_at <= completed_at <= graded_at, and in-progress attempts have completed_at=None",
        )


def validate_assessment_score_integrity(session: Session, reporter: ValidationReporter) -> None:
    """F. Assessment Score Integrity: bounds, normalization ratio tolerance (0.0001), and pass/fail rules."""
    cat = "F. Assessment Score Integrity"

    # Rule 1: Score bounds: raw_score >= 0.0, max_score > 0.0, raw_score <= max_score
    invalid_bounds = session.execute(
        select(AssessmentResult.result_id, AssessmentResult.raw_score, AssessmentResult.max_score)
        .where(
            (AssessmentResult.raw_score < 0.0)
            | (AssessmentResult.max_score <= 0.0)
            | (AssessmentResult.raw_score > AssessmentResult.max_score)
        )
    ).all()

    # Rule 2: Unrounded mathematical ratio check: abs(normalized_score - (raw_score / max_score)) <= 0.0001
    results = session.scalars(select(AssessmentResult)).all()
    ratio_violations = []
    pass_flag_mismatches = []

    for r in results:
        raw_val = float(r.raw_score)
        max_val = float(r.max_score)
        norm_val = float(r.normalized_score)
        actual_ratio = raw_val / max_val

        # Compare directly against the unrounded ratio
        if abs(norm_val - actual_ratio) > 0.0001:
            ratio_violations.append(f"{r.result_id}: norm={norm_val}, unrounded ratio={actual_ratio:.6f}")

        # Check pass flag against standard passing threshold 0.70 (from SRS FR-006 and generator implementation)
        expected_passed = norm_val >= 0.70
        if r.is_passed != expected_passed:
            pass_flag_mismatches.append(f"{r.result_id}: is_passed={r.is_passed}, norm_score={norm_val}")

    # Rule 3: 1-to-1 attempt relationship (no duplicate assessment results for an attempt)
    duplicate_attempts = session.execute(
        select(AssessmentResult.attempt_id, func.count(AssessmentResult.result_id))
        .group_by(AssessmentResult.attempt_id)
        .having(func.count(AssessmentResult.result_id) > 1)
    ).all()

    # Rule 4: Content eligibility: assessment results attach only to completed attempts of QUIZ, LAB, PROJECT
    ineligible_results = session.execute(
        select(AssessmentResult.result_id, ContentItem.content_type, Attempt.status)
        .join(Attempt, AssessmentResult.attempt_id == Attempt.attempt_id)
        .join(ContentItem, Attempt.content_id == ContentItem.content_id)
        .where((Attempt.status != "COMPLETED") | (~ContentItem.content_type.in_(["QUIZ", "LAB", "PROJECT"])))
    ).all()

    issues = []
    if invalid_bounds:
        issues.append(f"{len(invalid_bounds)} records violate 0 <= raw <= max score bounds")
    if ratio_violations:
        issues.append(f"{len(ratio_violations)} records violate unrounded ratio tolerance abs(norm - raw/max) <= 0.0001")
    if pass_flag_mismatches:
        issues.append(f"{len(pass_flag_mismatches)} records have pass/fail flag inconsistent with threshold 0.70")
    if duplicate_attempts:
        issues.append(f"{len(duplicate_attempts)} attempts have multiple assessment results")
    if ineligible_results:
        issues.append(f"{len(ineligible_results)} assessment results attach to non-completed attempts or non-assessed content")

    if issues:
        reporter.record(cat, "Score Arithmetic and Eligibility", "FAIL", "\n".join(issues))
    else:
        reporter.record(
            cat,
            "Score Arithmetic and Eligibility",
            "PASS",
            f"All {len(results)} assessment results satisfy raw/max bounds, unrounded ratio tolerance, 1-to-1 uniqueness, and content eligibility",
        )


def validate_prerequisite_graph(session: Session, reporter: ValidationReporter) -> None:
    """G. Prerequisite Graph: check self-prerequisites, cycles, edge counts, and observed graph depth."""
    cat = "G. Prerequisite Graph"

    all_skill_ids = session.scalars(select(Skill.skill_id)).all()
    all_nodes: Set[str] = set(all_skill_ids)

    edges = session.execute(
        select(SkillPrerequisite.prerequisite_skill_id, SkillPrerequisite.skill_id)
    ).all()

    # Self-prerequisite check
    self_loops = [f"Skill {p} references itself" for p, c in edges if p == c]

    # Build adjacency and in-degree tables
    adj: Dict[str, List[str]] = {s_id: [] for s_id in all_nodes}
    in_degree: Dict[str, int] = {s_id: 0 for s_id in all_nodes}

    for p, c in edges:
        if p in all_nodes and c in all_nodes and p != c:
            adj[p].append(c)
            in_degree[c] += 1

    # Kahn's algorithm for cycle detection and topological depth measurement
    queue = deque(n for n in all_nodes if in_degree[n] == 0)
    visited_count = 0
    longest_path: Dict[str, int] = {n: 1 for n in all_nodes}

    while queue:
        curr = queue.popleft()
        visited_count += 1
        for neighbor in adj[curr]:
            longest_path[neighbor] = max(longest_path[neighbor], longest_path[curr] + 1)
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    is_dag = (visited_count == len(all_nodes))
    max_observed_depth = max(longest_path.values()) if longest_path else 0

    issues = []
    if self_loops:
        issues.append("\n".join(self_loops))
    if not is_dag:
        issues.append(f"Cycle detected in prerequisite graph (visited {visited_count} of {len(all_nodes)} nodes)")

    # Check maximum depth against SRS Section H.2 generator specification (max depth: 4)
    if max_observed_depth > 4:
        issues.append(f"Prerequisite maximum depth ({max_observed_depth}) exceeds SRS maximum limit of 4")

    if issues:
        reporter.record(cat, "Prerequisite DAG Topology", "FAIL", "\n".join(issues))
    else:
        details = (
            f"Nodes: {len(all_nodes)}, Edges: {len(edges)}, Cycles: 0, "
            f"Max Observed Depth: {max_observed_depth} (within SRS limit <= 4)"
        )
        reporter.record(cat, "Prerequisite DAG Topology", "PASS", details)


def validate_learning_paths(session: Session, reporter: ValidationReporter) -> None:
    """H. Learning Paths: unique sequence positions, lifecycle timestamps, and ordering."""
    cat = "H. Learning Paths"

    paths = session.scalars(select(LearningPath)).all()
    cold_start_ids = set(session.scalars(select(Learner.learner_id)).all()) - set(
        session.scalars(select(Attempt.learner_id.distinct())).all()
    )

    duplicate_sequence_errors = []
    sequence_gap_warnings = []
    lifecycle_errors = []
    cold_start_completions_found = 0

    for path in paths:
        items = session.scalars(
            select(LearningPathItem)
            .where(LearningPathItem.path_id == path.path_id)
            .order_by(LearningPathItem.sequence_order)
        ).all()

        orders = [item.sequence_order for item in items]

        # 1. Check database uniqueness rule: no duplicate sequence_order per path
        if len(orders) != len(set(orders)):
            duplicate_sequence_errors.append(f"Path {path.path_id} contains duplicate sequence positions: {orders}")

        # 2. Check contiguous 1..N ordering as diagnostic warning
        if orders != list(range(1, len(items) + 1)):
            sequence_gap_warnings.append(f"Path {path.path_id} has non-contiguous sequence positions: {orders}")

        is_cold = path.learner_id in cold_start_ids

        for item in items:
            if is_cold and item.status == "COMPLETED":
                cold_start_completions_found += 1

            if item.status == "COMPLETED":
                if item.completed_at is None:
                    lifecycle_errors.append(f"Path {path.path_id}: item at sequence {item.sequence_order} is COMPLETED but completed_at is None")
            elif item.status in ("PENDING", "IN_PROGRESS", "SKIPPED"):
                if item.completed_at is not None:
                    lifecycle_errors.append(f"Path {path.path_id}: item at sequence {item.sequence_order} is {item.status} but has completed_at timestamp")

    # Evaluate results
    if duplicate_sequence_errors or lifecycle_errors:
        errs = duplicate_sequence_errors + lifecycle_errors
        reporter.record(cat, "Learning Path Sequencing and Lifecycle", "FAIL", "\n".join(errs))
    else:
        reporter.record(
            cat,
            "Learning Path Sequencing and Lifecycle",
            "PASS",
            f"All {len(paths)} learning paths satisfy unique sequence positions and status/timestamp rules",
        )

    # Diagnostic warnings
    if sequence_gap_warnings:
        reporter.record(
            cat,
            "Learning Path Sequence Gaps",
            "WARNING",
            f"{len(sequence_gap_warnings)} paths have non-contiguous sequence numbers (allowed by schema)",
        )

    if cold_start_completions_found > 0:
        reporter.record(
            cat,
            "Cold-Start Path Progress",
            "WARNING",
            f"{cold_start_completions_found} completed items found in paths owned by cold-start learners",
        )
    else:
        reporter.record(
            cat,
            "Cold-Start Path Progress",
            "PASS",
            "Cold-start learners with learning paths have zero completed items",
        )


def validate_anomaly_isolation(ro_engine: Engine, session: Session, reporter: ValidationReporter) -> None:
    """I. Anomaly Isolation: verify supporting tables are empty and inspect operational table schema columns."""
    cat = "I. Anomaly and Supporting Table Isolation"

    supporting_tables = [
        ("mastery_snapshots", MasterySnapshot),
        ("recommendations", Recommendation),
        ("recommendation_outcomes", RecommendationOutcome),
        ("audit_events", AuditEvent),
        ("data_issues", DataIssue),
    ]

    populated_tables = []
    for tbl_name, model_cls in supporting_tables:
        count = session.scalar(select(func.count()).select_from(model_cls))
        if count and count > 0:
            populated_tables.append(f"{tbl_name}: {count} rows")

    if populated_tables:
        reporter.record(
            cat,
            "Supporting Table Cleanliness",
            "FAIL",
            "Supporting operational tables must remain empty in clean baseline. Found rows:\n" + "\n".join(populated_tables),
        )
    else:
        reporter.record(
            cat,
            "Supporting Table Cleanliness",
            "PASS",
            "All 5 supporting tables (mastery, recommendations, outcomes, audit, data_issues) contain exactly 0 rows",
        )

    # Verify operational database schema does not define a ground_truth_label column
    inspector = inspect(ro_engine)
    data_issues_cols = [c["name"] for c in inspector.get_columns("data_issues")]
    if "ground_truth_label" in data_issues_cols:
        reporter.record(
            cat,
            "Operational Schema Column Absence (ground_truth_label)",
            "FAIL",
            "Schema check failed: 'data_issues' table contains 'ground_truth_label' column.",
        )
    else:
        reporter.record(
            cat,
            "Operational Schema Column Absence (ground_truth_label)",
            "PASS",
            "Verified operational database schema ('data_issues' table) contains zero 'ground_truth_label' columns. "
            "(Note: This check inspects operational table schema only and does not verify any separate ground-truth files.)",
        )


# ============================================================================
# MAIN READ-ONLY AUDIT WORKFLOW
# ============================================================================

def main() -> int:
    """Execute complete read-only validation workflow."""
    reporter = ValidationReporter()

    # 1. Configured URL contract verification before opening database
    # For this milestone, the validation script accepts only the exact configured database URL 'sqlite:///./skillpath.db'.
    if settings.database_url != EXPECTED_DATABASE_URL:
        sys.stderr.write(
            f"\n[FATAL] Configured database URL mismatch!\n"
            f"  Configured: '{settings.database_url}'\n"
            f"  Expected:   '{EXPECTED_DATABASE_URL}'\n"
            "For this milestone, only the exact configured URL 'sqlite:///./skillpath.db' is accepted.\n"
            "Aborting validation to avoid inspecting an unintended database.\n"
        )
        return 1

    # 2. Physical file verification
    if not EXPECTED_DB_PATH.exists():
        sys.stderr.write(f"\n[FATAL] Expected database file does not exist: {EXPECTED_DB_PATH}\n")
        return 1

    # 3. Establish read-only engine and session
    ro_engine = create_readonly_engine(EXPECTED_DB_PATH)
    ReadonlySession = sessionmaker(bind=ro_engine, autocommit=False, autoflush=False)
    session = ReadonlySession()

    try:
        # Execute validation sections A through I
        validate_database_and_schema(ro_engine, reporter)
        validate_dataset_acceptance_counts(ro_engine, reporter)
        validate_cold_start_learners(session, reporter)
        validate_referential_integrity(ro_engine, session, reporter)
        validate_timestamp_integrity(session, reporter)
        validate_assessment_score_integrity(session, reporter)
        validate_prerequisite_graph(session, reporter)
        validate_learning_paths(session, reporter)
        validate_anomaly_isolation(ro_engine, session, reporter)
    except Exception as exc:
        sys.stderr.write(f"\n[ERROR] Validation crashed during execution: {exc}\n")
        traceback.print_exc(file=sys.stderr)
        reporter.record(
            "Runtime Execution",
            "Validation Execution Flow",
            "FAIL",
            f"Unhandled exception during check execution:\n{exc}\n{traceback.format_exc().strip()}",
        )
    finally:
        session.rollback()
        session.close()
        ro_engine.dispose()

    access_mode = "SQLite PRAGMA query_only = ON (Driver-enforced read-only mode)"
    reporter.print_report(EXPECTED_DB_PATH, access_mode)

    return 1 if reporter.failed_categories else 0


if __name__ == "__main__":
    sys.exit(main())