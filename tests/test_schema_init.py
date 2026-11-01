"""Automated verification suite for Milestone 1 Database Schema & Pragmas.

Verifies table existence, SQLite foreign key enforcement, WAL mode, synchronous normal,
check constraints, score integrity, and metadata lineage using an isolated temporary database.
"""

from datetime import datetime
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from src.db.database import Base, register_sqlite_pragmas
from src.models import (
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
    Recommendation,
    MasterySnapshot,
    RecommendationOutcome,
    AuditEvent,
    DataIssue,
)

EXPECTED_TABLES = {
    "learners",
    "courses",
    "skills",
    "skill_prerequisites",
    "content_items",
    "content_skills",
    "attempts",
    "assessment_results",
    "learning_paths",
    "learning_path_items",
    "recommendations",
    "mastery_snapshots",
    "recommendation_outcomes",
    "audit_events",
    "data_issues",
}


@pytest.fixture(scope="module")
def isolated_db(tmp_path_factory):
    """Create a temporary SQLite database using tmp_path_factory with active pragmas."""
    temp_dir = tmp_path_factory.mktemp("db_test")
    test_db_path = temp_dir / "isolated_test.db"
    test_db_url = f"sqlite:///{test_db_path.as_posix()}"

    test_engine = create_engine(test_db_url, connect_args={"check_same_thread": False})
    register_sqlite_pragmas(test_engine)

    TestSession = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=test_engine,
        expire_on_commit=False,
    )

    Base.metadata.create_all(bind=test_engine)

    yield test_engine, TestSession

    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()


def test_all_15_tables_created(isolated_db):
    """1. Verify that all 10 core entities and 5 supporting entities exist in the database."""
    test_engine, _ = isolated_db
    inspector = inspect(test_engine)
    existing_tables = set(inspector.get_table_names())
    assert EXPECTED_TABLES.issubset(existing_tables), (
        f"Missing tables: {EXPECTED_TABLES - existing_tables}"
    )


def test_sqlite_foreign_keys_pragmas_enabled(isolated_db):
    """2. Verify that PRAGMA foreign_keys is actively ON (1) on connections."""
    _, TestSession = isolated_db
    with TestSession() as session:
        result = session.execute(text("PRAGMA foreign_keys;")).scalar()
        assert result == 1, f"Expected PRAGMA foreign_keys = 1, got {result}"


def test_sqlite_wal_mode_enabled(isolated_db):
    """3. Verify that SQLite journal_mode is configured to WAL."""
    _, TestSession = isolated_db
    with TestSession() as session:
        mode = session.execute(text("PRAGMA journal_mode;")).scalar()
        assert str(mode).lower() == "wal", f"Expected WAL mode, got {mode}"


def test_sqlite_synchronous_normal_enabled(isolated_db):
    """4. Verify that PRAGMA synchronous is configured to NORMAL (numeric value 1)."""
    _, TestSession = isolated_db
    with TestSession() as session:
        sync_mode = session.execute(text("PRAGMA synchronous;")).scalar()
        assert sync_mode == 1, f"Expected PRAGMA synchronous = 1 (NORMAL), got {sync_mode}"


def test_invalid_foreign_key_rejection(isolated_db):
    """5. Verify that inserting an attempt referencing a nonexistent learner raises IntegrityError."""
    _, TestSession = isolated_db
    with TestSession() as session:
        invalid_attempt = Attempt(
            attempt_id="ATT-TEST-000001",
            learner_id="LRN-NONEXISTENT",  # Foreign key target does not exist
            content_id="CNT-NONEXISTENT",
            attempt_number=1,
            started_at=datetime.utcnow(),
            status="IN_PROGRESS",
        )
        session.add(invalid_attempt)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_raw_score_cannot_exceed_max_score(isolated_db):
    """6. Verify that raw_score > max_score violates the chk_raw_le_max constraint."""
    _, TestSession = isolated_db
    with TestSession() as session:
        now = datetime.utcnow()
        learner = Learner(
            learner_id="LRN-SCORE-001",
            first_name="Score",
            last_name="Tester",
            email="score.tester@skillpath.local",
            experience_level="BEGINNER",
            created_at=now,
            updated_at=now,
        )
        course = Course(
            course_id="CRS-SCORE-001",
            title="Score Test Course",
            code="SCORE-101",
            difficulty="BEGINNER",
            created_at=now,
            updated_at=now,
        )
        content = ContentItem(
            content_id="CNT-SCORE-001",
            course_id="CRS-SCORE-001",
            title="Score Test Quiz",
            content_type="QUIZ",
            difficulty=0.50,
            duration_minutes=15,
            created_at=now,
            updated_at=now,
        )
        attempt = Attempt(
            attempt_id="ATT-SCORE-001",
            learner_id="LRN-SCORE-001",
            content_id="CNT-SCORE-001",
            attempt_number=1,
            started_at=now,
            completed_at=now,
            status="COMPLETED",
        )
        session.add_all([learner, course, content, attempt])
        session.commit()

        # raw_score (105.00) exceeds max_score (100.00)
        invalid_result = AssessmentResult(
            result_id="RES-SCORE-INVALID-MAX",
            attempt_id="ATT-SCORE-001",
            raw_score=105.00,
            max_score=100.00,
            normalized_score=1.0000,
            is_passed=True,
            graded_at=now,
        )
        session.add(invalid_result)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_normalized_score_ratio_integrity(isolated_db):
    """7. Verify that normalized_score deviating from raw_score / max_score by > 0.0001 is rejected."""
    _, TestSession = isolated_db
    with TestSession() as session:
        now = datetime.utcnow()
        learner = Learner(
            learner_id="LRN-RATIO-001",
            first_name="Ratio",
            last_name="Tester",
            email="ratio.tester@skillpath.local",
            experience_level="INTERMEDIATE",
            created_at=now,
            updated_at=now,
        )
        course = Course(
            course_id="CRS-RATIO-001",
            title="Ratio Course",
            code="RATIO-101",
            difficulty="INTERMEDIATE",
            created_at=now,
            updated_at=now,
        )
        content = ContentItem(
            content_id="CNT-RATIO-001",
            course_id="CRS-RATIO-001",
            title="Ratio Quiz",
            content_type="QUIZ",
            difficulty=0.60,
            duration_minutes=20,
            created_at=now,
            updated_at=now,
        )
        attempt = Attempt(
            attempt_id="ATT-RATIO-001",
            learner_id="LRN-RATIO-001",
            content_id="CNT-RATIO-001",
            attempt_number=1,
            started_at=now,
            completed_at=now,
            status="COMPLETED",
        )
        session.add_all([learner, course, content, attempt])
        session.commit()

        # Invalid: raw=75.0, max=100.0 -> expected=0.7500. Providing 0.8500 must violate constraint.
        mismatched_result = AssessmentResult(
            result_id="RES-RATIO-MISMATCH",
            attempt_id="ATT-RATIO-001",
            raw_score=75.00,
            max_score=100.00,
            normalized_score=0.8500,
            is_passed=True,
            graded_at=now,
        )
        session.add(mismatched_result)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        # Valid: raw=75.0, max=100.0, normalized=0.7500 matches within 0.0001
        valid_result = AssessmentResult(
            result_id="RES-RATIO-VALID",
            attempt_id="ATT-RATIO-001",
            raw_score=75.00,
            max_score=100.00,
            normalized_score=0.7500,
            is_passed=True,
            graded_at=now,
        )
        session.add(valid_result)
        session.commit()
        assert valid_result.normalized_score == 0.7500


def test_mastery_snapshot_lineage_and_unknown_property(isolated_db):
    """8. Verify lineage metadata persistence and derived is_unknown property."""
    now = datetime.utcnow()
    _, TestSession = isolated_db
    with TestSession() as session:
        learner = Learner(
            learner_id="LRN-LINEAGE-001",
            first_name="Lineage",
            last_name="Tester",
            email="lineage.tester@skillpath.local",
            experience_level="INTERMEDIATE",
            created_at=now,
            updated_at=now,
        )
        skill = Skill(
            skill_id="SKL-LINEAGE-001",
            name="Lineage Testing Skill",
            domain="Data Engineering",
            difficulty_level=0.40,
            created_at=now,
            updated_at=now,
        )
        session.add_all([learner, skill])
        session.commit()

        # Unknown mastery: mastery_level is None
        unknown_snapshot = MasterySnapshot(
            snapshot_id="SNP-UNKNOWN-001",
            learner_id="LRN-LINEAGE-001",
            skill_id="SKL-LINEAGE-001",
            mastery_level=None,
            evidence_count=0,
            confidence_score=0.0,
            cutoff_timestamp=now,
            max_evidence_graded_at=None,
            evidence_result_ids_json="[]",
            algorithm_version="v1.2.0",
            calculated_at=now,
        )
        session.add(unknown_snapshot)
        session.commit()

        assert unknown_snapshot.is_unknown is True
        assert unknown_snapshot.mastery_level is None

        # Active mastery: lineage metadata populated
        active_snapshot = MasterySnapshot(
            snapshot_id="SNP-ACTIVE-001",
            learner_id="LRN-LINEAGE-001",
            skill_id="SKL-LINEAGE-001",
            mastery_level=0.8500,
            evidence_count=2,
            confidence_score=0.6667,
            cutoff_timestamp=datetime(2026, 10, 30, 0, 0, 0),
            max_evidence_graded_at=datetime(2026, 10, 29, 12, 0, 0),
            evidence_result_ids_json='["RES-001", "RES-002"]',
            algorithm_version="v1.2.0",
            calculated_at=now,
        )
        session.add(active_snapshot)
        session.commit()

        assert active_snapshot.is_unknown is False
        assert active_snapshot.evidence_count == 2
        assert "RES-001" in active_snapshot.evidence_result_ids_json


def test_data_issue_contains_no_ground_truth_column(isolated_db):
    """9. Verify that the operational data_issues table does not contain ground_truth_label."""
    test_engine, _ = isolated_db
    inspector = inspect(test_engine)
    columns = [col["name"] for col in inspector.get_columns("data_issues")]
    assert "ground_truth_label" not in columns, (
        "Ground truth label must NOT exist in the operational data_issues table!"
    )
    assert "quarantine_status" in columns