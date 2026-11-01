"""Unit test suite for the Learner Skill Mastery Estimation Module.

Tests acceptance criteria MAST-001 through MAST-016:
- Pure Decimal precision and decay weight progression under MASTERY_CONTEXT.
- Unknown state vs. measured zero score distinction.
- Temporal cutoff gating and zero future leakage.
- Evidence lineage invariants (counts, arrays, timestamps, uniqueness).
- Append-only snapshot immutability and SQL statement monitoring.
- Batch learner profile coverage across all active curriculum skills.
"""

from collections import deque
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import sqlite3
from typing import Generator, List, Tuple
import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.db.database import Base
from src.models.entities import (
    Learner,
    Course,
    Skill,
    ContentItem,
    ContentSkill,
    Attempt,
    AssessmentResult,
    MasterySnapshot,
)
from src.services.mastery_service import (
    MasteryService,
    DEFAULT_ALGORITHM_VERSION,
)


def _apply_test_sqlite_pragmas(target_engine: Engine) -> None:
    """Enforce SQLite pragmas on test connections."""
    @event.listens_for(target_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        if isinstance(dbapi_connection, sqlite3.Connection):
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys = ON;")
                cursor.execute("PRAGMA journal_mode = WAL;")
                cursor.execute("PRAGMA synchronous = NORMAL;")
            finally:
                cursor.close()


@pytest.fixture
def isolated_db(tmp_path) -> Generator[Tuple[Session, List[str], Engine], None, None]:
    """Provide an isolated temporary SQLite database session with SQL statement monitoring."""
    db_path = tmp_path / "test_mastery_service.db"
    test_engine = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    _apply_test_sqlite_pragmas(test_engine)

    captured_statements: List[str] = []

    @event.listens_for(test_engine, "before_cursor_execute")
    def intercept_sql(conn, cursor, statement, parameters, context, executemany):
        # Normalize whitespace, uppercase, and strip dialect quotes (", [, ], `)
        clean = " ".join(
            statement.replace('"', "").replace("[", "").replace("]", "").replace("`", "").split()
        ).upper()
        captured_statements.append(clean)

    Base.metadata.create_all(bind=test_engine)
    TestingSession = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)
    session = TestingSession()

    yield session, captured_statements, test_engine

    session.close()
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()


def _create_base_curriculum(session: Session) -> Tuple[Learner, Course, Skill, ContentItem, ContentSkill]:
    """Helper to stage valid root relational records with positive relevance."""
    now = datetime(2026, 1, 1, 0, 0, 0)
    learner = Learner(
        learner_id="LRN-000001",
        first_name="Ada",
        last_name="Lovelace",
        email="ada@skillpath.local",
        experience_level="BEGINNER",
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    course = Course(
        course_id="CRS-000001",
        title="Intro to Computing",
        code="CS-101",
        difficulty="BEGINNER",
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    skill = Skill(
        skill_id="SKL-000001",
        name="Algorithmic Foundations",
        domain="Computer Science",
        difficulty_level=0.40,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    content = ContentItem(
        content_id="CNT-000001",
        course_id="CRS-000001",
        title="Binary Logic Quiz",
        content_type="QUIZ",
        difficulty=0.40,
        duration_minutes=20,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    content_skill = ContentSkill(
        content_id="CNT-000001",
        skill_id="SKL-000001",
        relevance_weight=1.00,
    )
    session.add_all([learner, course, skill, content, content_skill])
    session.flush()
    return learner, course, skill, content, content_skill


def _add_attempt_and_result(
    session: Session,
    learner_id: str,
    content_id: str,
    attempt_id: str,
    result_id: str,
    score: float,
    started_at: datetime,
    completed_at: datetime,
    graded_at: datetime,
    status: str = "COMPLETED",
    attempt_number: int = 1,
) -> AssessmentResult:
    """Helper to stage an attempt and associated assessment result satisfying all schema constraints."""
    norm_score = round(score / 100.0, 4)
    attempt = Attempt(
        attempt_id=attempt_id,
        learner_id=learner_id,
        content_id=content_id,
        attempt_number=attempt_number,
        started_at=started_at,
        completed_at=completed_at if status == "COMPLETED" else None,
        time_spent_seconds=int((completed_at - started_at).total_seconds()) if status == "COMPLETED" else None,
        status=status,
    )
    session.add(attempt)
    session.flush()

    res = AssessmentResult(
        result_id=result_id,
        attempt_id=attempt_id,
        raw_score=round(score, 2),
        max_score=100.00,
        normalized_score=norm_score,
        is_passed=(norm_score >= 0.70),
        graded_at=graded_at,
    )
    session.add(res)
    session.flush()
    return res


# ============================================================================
# TEST SUITE: MAST-001 THROUGH MAST-016
# ============================================================================

def test_cold_start_learner_produces_unknown_state(isolated_db):
    """MAST-001: Learner with zero attempts produces verified Unknown snapshot state."""
    session, _, _ = isolated_db
    _create_base_curriculum(session)

    cutoff = datetime(2026, 10, 30, 0, 0, 0)
    service = MasteryService(session)
    snapshot = service.get_or_create_snapshot("LRN-000001", "SKL-000001", cutoff)

    assert snapshot.mastery_level is None
    assert snapshot.is_unknown is True
    assert snapshot.evidence_count == 0
    assert snapshot.confidence_score == Decimal("0.0000")
    assert snapshot.max_evidence_graded_at is None
    assert snapshot.evidence_result_ids_json == "[]"


def test_measured_zero_score_differs_from_unknown(isolated_db):
    """MAST-002: Assessed score of 0.0 produces measured zero (not Unknown) with non-null metadata."""
    session, _, _ = isolated_db
    _create_base_curriculum(session)

    t0 = datetime(2026, 10, 15, 10, 0, 0)
    t1 = t0 + timedelta(minutes=15)
    t2 = t1 + timedelta(seconds=10)
    cutoff = datetime(2026, 10, 30, 0, 0, 0)

    _add_attempt_and_result(
        session, "LRN-000001", "CNT-000001", "ATT-LRN-000001-000001",
        "RES-ATT-LRN-000001-000001", 0.0, t0, t1, t2, attempt_number=1
    )

    service = MasteryService(session)
    snapshot = service.get_or_create_snapshot("LRN-000001", "SKL-000001", cutoff)

    assert snapshot.mastery_level == Decimal("0.0000")
    assert snapshot.is_unknown is False
    assert snapshot.evidence_count == 1
    assert snapshot.confidence_score == Decimal("0.3333")
    assert snapshot.max_evidence_graded_at == t2
    assert "RES-ATT-LRN-000001-000001" in snapshot.evidence_result_ids_json


def test_perfect_score_boundary(isolated_db):
    """MAST-003: Single assessment scoring 100/100 produces exact mastery_level 1.0000."""
    session, _, _ = isolated_db
    _create_base_curriculum(session)

    t0 = datetime(2026, 10, 15, 10, 0, 0)
    cutoff = datetime(2026, 10, 30, 0, 0, 0)

    _add_attempt_and_result(
        session, "LRN-000001", "CNT-000001", "ATT-LRN-000001-000001",
        "RES-ATT-LRN-000001-000001", 100.0, t0, t0 + timedelta(minutes=15), t0 + timedelta(minutes=16),
        attempt_number=1
    )

    service = MasteryService(session)
    snapshot = service.get_or_create_snapshot("LRN-000001", "SKL-000001", cutoff)

    assert snapshot.mastery_level == Decimal("1.0000")
    assert snapshot.confidence_score == Decimal("0.3333")


def test_thirty_day_half_life_decay_weights(isolated_db):
    """MAST-004: Two scores evaluated 30 days apart receive weights in exact ratio 1.0 : 0.5."""
    session, _, _ = isolated_db
    _create_base_curriculum(session)

    cutoff = datetime(2026, 10, 30, 0, 0, 0)
    # Attempt 1: exactly 30 days before cutoff -> weight = 0.5000, score = 0.60
    t1 = cutoff - timedelta(days=30)
    # Attempt 2: exactly at cutoff -> weight = 1.0000, score = 0.90
    t2 = cutoff

    _add_attempt_and_result(
        session, "LRN-000001", "CNT-000001", "ATT-LRN-000001-000001",
        "RES-ATT-LRN-000001-000001", 60.0, t1 - timedelta(minutes=20), t1 - timedelta(minutes=5), t1,
        attempt_number=1
    )
    _add_attempt_and_result(
        session, "LRN-000001", "CNT-000001", "ATT-LRN-000001-000002",
        "RES-ATT-LRN-000001-000002", 90.0, t2 - timedelta(minutes=20), t2 - timedelta(minutes=5), t2,
        attempt_number=2
    )

    service = MasteryService(session)
    snapshot = service.get_or_create_snapshot("LRN-000001", "SKL-000001", cutoff)

    # Numerator: (0.50 * 0.60) + (1.00 * 0.90) = 0.30 + 0.90 = 1.2000
    # Denominator: 0.50 + 1.00 = 1.5000
    # Expected M = 1.20 / 1.50 = 0.8000
    assert snapshot.mastery_level == Decimal("0.8000")
    assert snapshot.confidence_score == Decimal("0.6667")
    assert snapshot.evidence_count == 2

    # Negative elapsed time input validation check
    with pytest.raises(ValueError, match="delta_seconds must be non-negative"):
        MasteryService.calculate_recency_weight(Decimal("-10.0"))


def test_relevance_weight_proportional_impact(isolated_db):
    """MAST-005: Two simultaneous assessments with r=1.00 and r=0.50 reflect exact 2:1 influence ratio."""
    session, _, _ = isolated_db
    _create_base_curriculum(session)

    # Add second content item with relevance weight 0.50
    content2 = ContentItem(
        content_id="CNT-000002",
        course_id="CRS-000001",
        title="Secondary Lab",
        content_type="LAB",
        difficulty=0.50,
        duration_minutes=30,
        is_active=True,
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
    )
    cs2 = ContentSkill(
        content_id="CNT-000002",
        skill_id="SKL-000001",
        relevance_weight=0.50,
    )
    session.add_all([content2, cs2])
    session.flush()

    cutoff = datetime(2026, 10, 30, 0, 0, 0)
    # Both graded at identical time (delta = 0 -> w1 = 1.0, w2 = 1.0)
    _add_attempt_and_result(
        session, "LRN-000001", "CNT-000001", "ATT-LRN-000001-000001",
        "RES-ATT-LRN-000001-000001", 100.0, cutoff - timedelta(minutes=30), cutoff - timedelta(minutes=10), cutoff,
        attempt_number=1
    )
    _add_attempt_and_result(
        session, "LRN-000001", "CNT-000002", "ATT-LRN-000001-000002",
        "RES-ATT-LRN-000001-000002", 40.0, cutoff - timedelta(minutes=30), cutoff - timedelta(minutes=10), cutoff,
        attempt_number=1
    )

    service = MasteryService(session)
    snapshot = service.get_or_create_snapshot("LRN-000001", "SKL-000001", cutoff)

    # Numerator: (1.0 * 1.0 * 1.0) + (1.0 * 0.5 * 0.40) = 1.0 + 0.20 = 1.2000
    # Denominator: (1.0 * 1.0) + (1.0 * 0.5) = 1.0 + 0.50 = 1.5000
    # Expected M = 1.20 / 1.50 = 0.8000
    assert snapshot.mastery_level == Decimal("0.8000")


def test_zero_relevance_weight_excluded_from_evidence(isolated_db):
    """MAST-006: Assessment mapped with relevance_weight = 0.00 is excluded from evidence without division error."""
    session, _, _ = isolated_db
    _create_base_curriculum(session)

    content_zero = ContentItem(
        content_id="CNT-ZERO-REL",
        course_id="CRS-000001",
        title="Zero Relevance Item",
        content_type="QUIZ",
        difficulty=0.50,
        duration_minutes=15,
        is_active=True,
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
    )
    cs_zero = ContentSkill(
        content_id="CNT-ZERO-REL",
        skill_id="SKL-000001",
        relevance_weight=0.00,
    )
    session.add_all([content_zero, cs_zero])
    session.flush()

    cutoff = datetime(2026, 10, 30, 0, 0, 0)
    _add_attempt_and_result(
        session, "LRN-000001", "CNT-ZERO-REL", "ATT-ZERO-001",
        "RES-ZERO-001", 95.0, cutoff - timedelta(hours=1), cutoff - timedelta(minutes=30), cutoff,
        attempt_number=1
    )

    service = MasteryService(session)
    snapshot = service.get_or_create_snapshot("LRN-000001", "SKL-000001", cutoff)

    # Must be completely excluded; learner has zero positive-relevance evidence
    assert snapshot.mastery_level is None
    assert snapshot.is_unknown is True
    assert snapshot.evidence_count == 0


def test_three_retakes_on_identical_content(isolated_db):
    """MAST-007: Three retakes on identical quiz evaluate to mathematically proven 0.7286."""
    session, _, _ = isolated_db
    _create_base_curriculum(session)

    cutoff = datetime(2026, 10, 30, 0, 0, 0)
    # Attempt 1: 60 days ago (w = 0.2500, score = 0.3000)
    t1 = cutoff - timedelta(days=60)
    _add_attempt_and_result(
        session, "LRN-000001", "CNT-000001", "ATT-RETAKE-001",
        "RES-RETAKE-001", 30.0, t1 - timedelta(minutes=25), t1 - timedelta(minutes=5), t1,
        attempt_number=1
    )

    # Attempt 2: 30 days ago (w = 0.5000, score = 0.6000)
    t2 = cutoff - timedelta(days=30)
    _add_attempt_and_result(
        session, "LRN-000001", "CNT-000001", "ATT-RETAKE-002",
        "RES-RETAKE-002", 60.0, t2 - timedelta(minutes=25), t2 - timedelta(minutes=5), t2,
        attempt_number=2
    )

    # Attempt 3: 0 days ago (w = 1.0000, score = 0.9000)
    t3 = cutoff
    _add_attempt_and_result(
        session, "LRN-000001", "CNT-000001", "ATT-RETAKE-003",
        "RES-RETAKE-003", 90.0, t3 - timedelta(minutes=25), t3 - timedelta(minutes=5), t3,
        attempt_number=3
    )

    service = MasteryService(session)
    snapshot = service.get_or_create_snapshot("LRN-000001", "SKL-000001", cutoff)

    # Numerator = (0.25 * 0.30) + (0.50 * 0.60) + (1.00 * 0.90) = 0.075 + 0.300 + 0.900 = 1.2750
    # Denominator = 0.25 + 0.50 + 1.00 = 1.7500
    # Quotient = 1.2750 / 1.7500 = 51 / 70 = 0.728571... -> ROUND_HALF_EVEN -> 0.7286
    assert snapshot.mastery_level == Decimal("0.7286")
    assert snapshot.confidence_score == Decimal("1.0000")
    assert snapshot.evidence_count == 3


def test_future_dated_evidence_strict_exclusion(isolated_db):
    """MAST-008: Evidence graded at T - 1s is included; evidence graded at T + 1s is excluded."""
    session, _, _ = isolated_db
    _create_base_curriculum(session)

    cutoff = datetime(2026, 10, 30, 12, 0, 0)
    valid_time = cutoff - timedelta(seconds=1)
    future_time = cutoff + timedelta(seconds=1)

    _add_attempt_and_result(
        session, "LRN-000001", "CNT-000001", "ATT-VALID-PAST",
        "RES-VALID-PAST", 80.0, valid_time - timedelta(minutes=20), valid_time - timedelta(minutes=5), valid_time,
        attempt_number=1
    )
    _add_attempt_and_result(
        session, "LRN-000001", "CNT-000001", "ATT-FUTURE-LEAK",
        "RES-FUTURE-LEAK", 20.0, future_time - timedelta(minutes=20), future_time - timedelta(minutes=5), future_time,
        attempt_number=2
    )

    service = MasteryService(session)
    snapshot = service.get_or_create_snapshot("LRN-000001", "SKL-000001", cutoff)

    assert snapshot.evidence_count == 1
    assert snapshot.mastery_level == Decimal("0.8000")
    assert snapshot.max_evidence_graded_at == valid_time
    assert "RES-VALID-PAST" in snapshot.evidence_result_ids_json
    assert "RES-FUTURE-LEAK" not in snapshot.evidence_result_ids_json


def test_evidence_lineage_count_and_json_agreement(isolated_db):
    """MAST-009: Invariant: evidence_count strictly equals len(json.loads(evidence_result_ids_json))."""
    session, _, _ = isolated_db
    _create_base_curriculum(session)

    cutoff = datetime(2026, 10, 30, 0, 0, 0)
    for i in range(1, 4):
        t = cutoff - timedelta(days=i * 5)
        _add_attempt_and_result(
            session, "LRN-000001", "CNT-000001", f"ATT-LINEAGE-{i:03d}",
            f"RES-LINEAGE-{i:03d}", 75.0, t - timedelta(minutes=20), t - timedelta(minutes=5), t,
            attempt_number=i
        )

    service = MasteryService(session)
    snapshot = service.get_or_create_snapshot("LRN-000001", "SKL-000001", cutoff)

    parsed_ids = json.loads(snapshot.evidence_result_ids_json)
    assert snapshot.evidence_count == len(parsed_ids)
    assert snapshot.evidence_count == 3


def test_max_evidence_timestamp_matches_lineage(isolated_db):
    """MAST-010: Invariant: max_evidence_graded_at strictly matches maximum graded_at in evidence set."""
    session, _, _ = isolated_db
    _create_base_curriculum(session)

    cutoff = datetime(2026, 10, 30, 0, 0, 0)
    t_old = cutoff - timedelta(days=20)
    t_new = cutoff - timedelta(hours=2)

    _add_attempt_and_result(
        session, "LRN-000001", "CNT-000001", "ATT-TIME-01",
        "RES-TIME-01", 70.0, t_old - timedelta(minutes=20), t_old - timedelta(minutes=5), t_old,
        attempt_number=1
    )
    _add_attempt_and_result(
        session, "LRN-000001", "CNT-000001", "ATT-TIME-02",
        "RES-TIME-02", 90.0, t_new - timedelta(minutes=20), t_new - timedelta(minutes=5), t_new,
        attempt_number=2
    )

    service = MasteryService(session)
    snapshot = service.get_or_create_snapshot("LRN-000001", "SKL-000001", cutoff)

    assert snapshot.max_evidence_graded_at == t_new


def test_lineage_ids_strictly_unique(isolated_db):
    """MAST-011: Invariant: zero duplicate identifier strings inside evidence_result_ids_json."""
    session, _, _ = isolated_db
    _create_base_curriculum(session)

    cutoff = datetime(2026, 10, 30, 0, 0, 0)
    for i in range(1, 4):
        t = cutoff - timedelta(days=i)
        _add_attempt_and_result(
            session, "LRN-000001", "CNT-000001", f"ATT-UNIQ-{i}",
            f"RES-UNIQ-{i}", 85.0, t - timedelta(minutes=20), t - timedelta(minutes=5), t,
            attempt_number=i
        )

    service = MasteryService(session)
    snapshot = service.get_or_create_snapshot("LRN-000001", "SKL-000001", cutoff)

    ids = json.loads(snapshot.evidence_result_ids_json)
    assert len(ids) == len(set(ids))


def test_snapshot_immutability_and_statement_monitoring(isolated_db):
    """MAST-012: Statement monitoring verifies zero UPDATE or DELETE statements against core and snapshot tables."""
    session, captured_statements, _ = isolated_db
    _create_base_curriculum(session)

    cutoff = datetime(2026, 10, 30, 0, 0, 0)
    t = cutoff - timedelta(days=2)
    _add_attempt_and_result(
        session, "LRN-000001", "CNT-000001", "ATT-IMMUT-01",
        "RES-IMMUT-01", 85.0, t - timedelta(minutes=20), t - timedelta(minutes=5), t,
        attempt_number=1
    )

    service = MasteryService(session)
    captured_statements.clear()

    service.get_or_create_snapshot("LRN-000001", "SKL-000001", cutoff)

    forbidden_prefixes = [
        "UPDATE MASTERY_SNAPSHOTS",
        "DELETE FROM MASTERY_SNAPSHOTS",
        "UPDATE ATTEMPTS",
        "DELETE FROM ATTEMPTS",
        "UPDATE ASSESSMENT_RESULTS",
        "DELETE FROM ASSESSMENT_RESULTS",
    ]
    for norm_stmt in captured_statements:
        for forbidden in forbidden_prefixes:
            assert not norm_stmt.startswith(forbidden), f"Immutability violated by statement: {norm_stmt}"


def test_idempotent_snapshot_retrieval(isolated_db):
    """MAST-013: Second get_or_create_snapshot call executes SELECT (hit) with 0 INSERT/UPDATE/DELETE."""
    session, captured_statements, _ = isolated_db
    _create_base_curriculum(session)

    cutoff = datetime(2026, 10, 30, 0, 0, 0)
    t = cutoff - timedelta(days=5)
    _add_attempt_and_result(
        session, "LRN-000001", "CNT-000001", "ATT-IDEMP-01",
        "RES-IDEMP-01", 80.0, t - timedelta(minutes=20), t - timedelta(minutes=5), t,
        attempt_number=1
    )

    service = MasteryService(session)
    # First invocation: creates snapshot
    snap1 = service.get_or_create_snapshot("LRN-000001", "SKL-000001", cutoff)
    session.flush()

    captured_statements.clear()
    # Second invocation: retrieves pre-existing snapshot
    snap2 = service.get_or_create_snapshot("LRN-000001", "SKL-000001", cutoff)

    assert snap1.snapshot_id == snap2.snapshot_id
    assert snap1.mastery_level == snap2.mastery_level

    # Verification: SELECT is allowed, but strictly 0 mutations
    select_count = sum(1 for s in captured_statements if s.startswith("SELECT") and "MASTERY_SNAPSHOTS" in s)
    insert_count = sum(1 for s in captured_statements if s.startswith("INSERT INTO MASTERY_SNAPSHOTS"))
    update_count = sum(1 for s in captured_statements if "UPDATE" in s)
    delete_count = sum(1 for s in captured_statements if "DELETE" in s)

    assert select_count >= 1, "Expected SELECT query to locate existing snapshot"
    assert insert_count == 0, "Second call must emit 0 INSERT statements"
    assert update_count == 0, "Second call must emit 0 UPDATE statements"
    assert delete_count == 0, "Second call must emit 0 DELETE statements"


def test_separate_snapshots_for_different_algorithm_versions(isolated_db):
    """MAST-014: Generating with v1.1.0 and v1.2.0 persists two distinct, coexistence-safe snapshots."""
    session, _, _ = isolated_db
    _create_base_curriculum(session)

    cutoff = datetime(2026, 10, 30, 0, 0, 0)
    t = cutoff - timedelta(days=3)
    _add_attempt_and_result(
        session, "LRN-000001", "CNT-000001", "ATT-VER-01",
        "RES-VER-01", 90.0, t - timedelta(minutes=20), t - timedelta(minutes=5), t,
        attempt_number=1
    )

    service_v1 = MasteryService(session, algorithm_version="v1.1.0")
    service_v2 = MasteryService(session, algorithm_version="v1.2.0")

    snap_v1 = service_v1.get_or_create_snapshot("LRN-000001", "SKL-000001", cutoff)
    snap_v2 = service_v2.get_or_create_snapshot("LRN-000001", "SKL-000001", cutoff)

    assert snap_v1.snapshot_id != snap_v2.snapshot_id
    assert snap_v1.algorithm_version == "v1.1.0"
    assert snap_v2.algorithm_version == "v1.2.0"

    all_snaps = session.scalars(
        select(MasterySnapshot).where(
            MasterySnapshot.learner_id == "LRN-000001",
            MasterySnapshot.skill_id == "SKL-000001",
            MasterySnapshot.cutoff_timestamp == cutoff,
        )
    ).all()
    assert len(all_snaps) == 2


def test_compute_learner_profile_includes_all_skills(isolated_db):
    """MAST-015: compute_learner_profile() includes every active curriculum skill with batch resolution."""
    session, _, _ = isolated_db
    _create_base_curriculum(session)

    # Add second active skill with no assessment history
    skill2 = Skill(
        skill_id="SKL-000002",
        name="Data Pipelines",
        domain="Data Engineering",
        difficulty_level=0.60,
        is_active=True,
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
    )
    session.add(skill2)
    session.flush()

    cutoff = datetime(2026, 10, 30, 0, 0, 0)
    t = cutoff - timedelta(days=2)
    _add_attempt_and_result(
        session, "LRN-000001", "CNT-000001", "ATT-PROF-01",
        "RES-PROF-01", 85.0, t - timedelta(minutes=20), t - timedelta(minutes=5), t,
        attempt_number=1
    )

    service = MasteryService(session)
    profile = service.compute_learner_profile("LRN-000001", cutoff)

    assert "SKL-000001" in profile
    assert "SKL-000002" in profile

    # Assessed skill
    assert profile["SKL-000001"].mastery_level == Decimal("0.8500")
    assert profile["SKL-000001"].is_unknown is False
    assert profile["SKL-000001"].evidence_count == 1

    # Unassessed skill is populated with verified Unknown state
    assert profile["SKL-000002"].mastery_level is None
    assert profile["SKL-000002"].is_unknown is True
    assert profile["SKL-000002"].evidence_count == 0
    assert profile["SKL-000002"].confidence_score == Decimal("0.0000")


def test_snapshot_id_deterministic_and_collision_resistant():
    """MAST-016: generate_snapshot_id produces deterministic, collision-resistant 32-character identifiers."""
    ts1 = datetime(2026, 10, 30, 0, 0, 0)
    ts2 = datetime(2026, 10, 30, 0, 0, 1)

    id_base = MasteryService.generate_snapshot_id("LRN-000001", "SKL-000001", ts1, "v1.1.0")
    id_same = MasteryService.generate_snapshot_id("LRN-000001", "SKL-000001", ts1, "v1.1.0")
    assert id_base == id_same
    assert len(id_base) == 32
    assert id_base.startswith("SNP-")

    # Variance across attributes
    assert id_base != MasteryService.generate_snapshot_id("LRN-000002", "SKL-000001", ts1, "v1.1.0")
    assert id_base != MasteryService.generate_snapshot_id("LRN-000001", "SKL-000002", ts1, "v1.1.0")
    assert id_base != MasteryService.generate_snapshot_id("LRN-000001", "SKL-000001", ts2, "v1.1.0")
    assert id_base != MasteryService.generate_snapshot_id("LRN-000001", "SKL-000001", ts1, "v1.2.0")

    # Timezone-aware normalization to UTC test
    tz_plus_5 = timezone(timedelta(hours=5))
    ts_utc = datetime(2026, 10, 30, 0, 0, 0, tzinfo=timezone.utc)
    ts_aware_diff = datetime(2026, 10, 30, 5, 0, 0, tzinfo=tz_plus_5)  # Same instant in time
    id_utc = MasteryService.generate_snapshot_id("LRN-000001", "SKL-000001", ts_utc, "v1.1.0")
    id_diff_tz = MasteryService.generate_snapshot_id("LRN-000001", "SKL-000001", ts_aware_diff, "v1.1.0")
    assert id_utc == id_diff_tz