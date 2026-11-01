"""Automated acceptance test suite for the deterministic synthetic data generator."""

from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
import sqlite3
from typing import Any, Dict, List, Set, Tuple
import pytest
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from src.db.database import Base
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
from src.services.generator.synthetic_engine import (
    SyntheticDataGenerator,
    DEVELOPMENT_CONFIG,
    GeneratorConfig,
    MIN_REQUIRED_WINDOW_SECONDS,
    MAX_ATTEMPT_DURATION_SECONDS,
    MAX_GRADING_DELAY_SECONDS,
)


def _apply_test_sqlite_pragmas(target_engine: Engine) -> None:
    """Register SQLite pragmas directly using SQLAlchemy's connection listener API."""
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
def fresh_session(tmp_path):
    """Provide a fresh SQLite database session isolated in a temporary directory."""
    db_path = tmp_path / "test_synth.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", connect_args={"check_same_thread": False})
    _apply_test_sqlite_pragmas(engine)

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()

    yield session

    session.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_development_profile_exact_entity_counts(fresh_session):
    """1. Verify exact development-tier counts: 100 learners, 10 courses, 50 skills, 100 content, 2000 attempts."""
    generator = SyntheticDataGenerator(fresh_session, DEVELOPMENT_CONFIG)
    summary = generator.generate()

    assert summary["learners"] == 100
    assert summary["courses"] == 10
    assert summary["skills"] == 50
    assert summary["content_items"] == 100
    assert summary["attempts"] == 2000
    assert summary["learning_paths"] == 80


def test_cold_start_learners_explicit_count_and_attempts(fresh_session):
    """2 & 3. Verify exactly 10 cold-start learners (0 attempts) and remaining 90 learners have >= 1 attempt."""
    generator = SyntheticDataGenerator(fresh_session, DEVELOPMENT_CONFIG)
    generator.generate()

    learners = fresh_session.scalars(select(Learner)).all()
    attempt_counts = {
        l_id: count for l_id, count in fresh_session.execute(
            select(Attempt.learner_id, func.count(Attempt.attempt_id)).group_by(Attempt.learner_id)
        ).all()
    }

    expected_cold_ids = generator.get_cold_start_learner_ids()
    assert len(expected_cold_ids) == 10

    zero_attempt_learners = [l for l in learners if attempt_counts.get(l.learner_id, 0) == 0]
    active_learners = [l for l in learners if attempt_counts.get(l.learner_id, 0) > 0]

    assert len(zero_attempt_learners) == 10
    assert {l.learner_id for l in zero_attempt_learners} == expected_cold_ids
    assert len(active_learners) == 90
    assert sum(attempt_counts.values()) == 2000


def test_skill_domain_distribution(fresh_session):
    """4. Verify domain counts: 15 Data Science, 15 Web Dev, 10 DevOps, 10 Cyber Security."""
    generator = SyntheticDataGenerator(fresh_session, DEVELOPMENT_CONFIG)
    generator.generate()

    domain_counts = dict(
        fresh_session.execute(
            select(Skill.domain, func.count(Skill.skill_id)).group_by(Skill.domain)
        ).all()
    )

    assert domain_counts.get("Data Science") == 15
    assert domain_counts.get("Web Development") == 15
    assert domain_counts.get("DevOps") == 10
    assert domain_counts.get("Cyber Security") == 10


def test_configurable_content_type_distribution(fresh_session):
    """5. Verify content type counts: 35 VIDEO, 25 READING, 20 QUIZ, 15 LAB, 5 PROJECT."""
    generator = SyntheticDataGenerator(fresh_session, DEVELOPMENT_CONFIG)
    generator.generate()

    type_counts = dict(
        fresh_session.execute(
            select(ContentItem.content_type, func.count(ContentItem.content_id)).group_by(ContentItem.content_type)
        ).all()
    )

    assert type_counts.get("VIDEO") == 35
    assert type_counts.get("READING") == 25
    assert type_counts.get("QUIZ") == 20
    assert type_counts.get("LAB") == 15
    assert type_counts.get("PROJECT") == 5


def test_custom_valid_content_type_distribution(tmp_path):
    """Verify custom valid content-type proportions are accurately allocated."""
    db_path = tmp_path / "custom_prop.db"
    eng = create_engine(f"sqlite:///{db_path.as_posix()}", connect_args={"check_same_thread": False})
    _apply_test_sqlite_pragmas(eng)
    Base.metadata.create_all(bind=eng)
    sess = sessionmaker(bind=eng)()

    try:
        custom_props = {
            "VIDEO": 0.20,
            "READING": 0.20,
            "QUIZ": 0.20,
            "LAB": 0.20,
            "PROJECT": 0.20,
        }
        cfg = GeneratorConfig(
            profile_name="custom_props",
            seed=20261022,
            num_learners=3,
            num_courses=1,
            num_skills=4,
            num_content_items=100,
            num_attempts=3,
            num_learning_paths=2,
            num_cold_start_learners=1,
            content_type_proportions=custom_props,
        )
        gen = SyntheticDataGenerator(sess, cfg)
        gen.generate()

        type_counts = dict(
            sess.execute(
                select(ContentItem.content_type, func.count(ContentItem.content_id)).group_by(ContentItem.content_type)
            ).all()
        )
        for ct in ["VIDEO", "READING", "QUIZ", "LAB", "PROJECT"]:
            assert type_counts.get(ct) == 20
    finally:
        sess.close()
        eng.dispose()


def test_foreign_key_referential_integrity(fresh_session):
    """6. Verify zero foreign key violations across the generated dataset."""
    generator = SyntheticDataGenerator(fresh_session, DEVELOPMENT_CONFIG)
    generator.generate()

    violations = fresh_session.execute(text("PRAGMA foreign_key_check;")).fetchall()
    assert len(violations) == 0


def test_prerequisite_dag_acyclicity_and_maximum_depth(fresh_session):
    """7. Verify prerequisite graph across ALL generated skills is an acyclic DAG with max depth <= 4 and no self-loops."""
    generator = SyntheticDataGenerator(fresh_session, DEVELOPMENT_CONFIG)
    generator.generate()

    # Query every generated skill ID to include isolated skills in the topological validation
    all_skill_ids = fresh_session.scalars(select(Skill.skill_id)).all()
    all_nodes: Set[str] = set(all_skill_ids)
    assert len(all_nodes) == 50

    edges = fresh_session.execute(
        select(SkillPrerequisite.prerequisite_skill_id, SkillPrerequisite.skill_id)
    ).all()

    adj: Dict[str, List[str]] = {s_id: [] for s_id in all_nodes}
    in_degree: Dict[str, int] = {s_id: 0 for s_id in all_nodes}

    for p, c in edges:
        assert p in all_nodes and c in all_nodes
        assert p != c, f"Self-prerequisite detected on skill {p}"
        adj[p].append(c)
        in_degree[c] += 1

    # Kahn's algorithm initialized across all nodes using deque.popleft()
    queue = deque(n for n in all_nodes if in_degree[n] == 0)
    visited_count = 0
    longest_path: Dict[str, int] = {n: 1 for n in all_nodes}

    while queue:
        curr = queue.popleft()
        visited_count += 1
        for neighbor in adj[curr]:
            longest_path[neighbor] = max(longest_path[neighbor], longest_path[curr] + 1)
            assert longest_path[neighbor] <= 4, f"Prerequisite depth exceeded 4 at node {neighbor}"
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    assert visited_count == len(all_nodes), "Cycle detected in prerequisite graph!"
    assert max(longest_path.values()) <= 4


def test_attempt_lifecycle_and_timestamp_ordering(fresh_session):
    """8. Verify attempt statuses and chronological sequencing (started <= completed <= end_date)."""
    generator = SyntheticDataGenerator(fresh_session, DEVELOPMENT_CONFIG)
    generator.generate()

    attempts = fresh_session.scalars(select(Attempt)).all()
    for att in attempts:
        assert att.status in ("COMPLETED", "ABANDONED", "IN_PROGRESS")
        assert att.started_at >= DEVELOPMENT_CONFIG.start_date
        assert att.started_at <= DEVELOPMENT_CONFIG.end_date

        if att.status == "COMPLETED":
            assert att.completed_at is not None
            assert att.completed_at >= att.started_at
            assert att.completed_at <= DEVELOPMENT_CONFIG.end_date
            assert att.time_spent_seconds is not None and att.time_spent_seconds >= 60
        else:
            assert att.completed_at is None


def test_all_timestamps_within_configured_date_range(fresh_session):
    """Verify all generated timestamps strictly fall within [start_date, end_date]."""
    generator = SyntheticDataGenerator(fresh_session, DEVELOPMENT_CONFIG)
    generator.generate()

    start = DEVELOPMENT_CONFIG.start_date
    end = DEVELOPMENT_CONFIG.end_date

    for att in fresh_session.scalars(select(Attempt)).all():
        assert start <= att.started_at <= end
        if att.completed_at is not None:
            assert start <= att.completed_at <= end
            assert att.started_at <= att.completed_at

    for res in fresh_session.scalars(select(AssessmentResult)).all():
        assert start <= res.graded_at <= end

    for lpi in fresh_session.scalars(select(LearningPathItem)).all():
        if lpi.completed_at is not None:
            assert start <= lpi.completed_at <= end

    for l in fresh_session.scalars(select(Learner)).all():
        assert start <= l.created_at <= end
        assert start <= l.updated_at <= end


def test_deterministic_attempt_timing_calculation_at_maximum_bounds():
    """Verify timing calculation at maximum allowed offset, maximum duration, and maximum grading delay."""
    start = datetime(2026, 1, 1, 0, 0, 0)
    end = start + timedelta(seconds=MIN_REQUIRED_WINDOW_SECONDS)
    total_seconds = int((end - start).total_seconds())
    usable_span = total_seconds - MIN_REQUIRED_WINDOW_SECONDS

    # Call calculate_attempt_timing directly at the extreme boundary
    started_at, completed_at, graded_at = SyntheticDataGenerator.calculate_attempt_timing(
        start_date=start,
        offset_fraction=1.0,  # Maximum permitted offset
        usable_span_seconds=usable_span,
        duration_seconds=MAX_ATTEMPT_DURATION_SECONDS,
        grading_delay_seconds=MAX_GRADING_DELAY_SECONDS,
    )

    assert started_at >= start
    assert completed_at > started_at
    assert graded_at > completed_at
    assert graded_at <= end
    assert graded_at == end  # Mathematically touches the exact end_date without any min() or clamping


def test_short_date_window_boundary_exact_minimum_and_invalid(tmp_path):
    """Verify timestamp generation at exact minimum window (7260s) and rejection of window 1s shorter."""
    db_path1 = tmp_path / "min_win.db"
    eng1 = create_engine(f"sqlite:///{db_path1.as_posix()}", connect_args={"check_same_thread": False})
    _apply_test_sqlite_pragmas(eng1)
    Base.metadata.create_all(bind=eng1)
    sess1 = sessionmaker(bind=eng1)()

    try:
        start = datetime(2026, 10, 30, 0, 0, 0)
        # Exact minimum valid window: 7260 seconds
        end_exact = start + timedelta(seconds=MIN_REQUIRED_WINDOW_SECONDS)
        cfg_exact = GeneratorConfig(
            profile_name="exact_min",
            seed=20261022,
            num_learners=3,
            num_courses=1,
            num_skills=4,
            num_content_items=5,
            num_attempts=3,
            num_learning_paths=2,
            num_cold_start_learners=1,
            start_date=start,
            end_date=end_exact,
        )
        gen = SyntheticDataGenerator(sess1, cfg_exact)
        gen.generate()

        for att in sess1.scalars(select(Attempt)).all():
            assert start <= att.started_at <= end_exact
            if att.completed_at is not None:
                assert start <= att.completed_at <= end_exact
                assert att.started_at <= att.completed_at
    finally:
        sess1.close()
        eng1.dispose()

    # Rejection of window one second shorter (7259 seconds)
    with pytest.raises(ValueError, match="must span at least 7260s"):
        GeneratorConfig(
            profile_name="too_short_by_one_second",
            seed=20261022,
            num_learners=3,
            num_courses=1,
            num_skills=4,
            num_content_items=5,
            num_attempts=3,
            num_learning_paths=2,
            num_cold_start_learners=1,
            start_date=start,
            end_date=start + timedelta(seconds=MIN_REQUIRED_WINDOW_SECONDS - 1),
        )


def test_valid_ten_thousand_second_window(tmp_path):
    """Verify timestamp generation succeeds without truncation in a valid 10,000-second window."""
    db_path = tmp_path / "ten_k_win.db"
    eng = create_engine(f"sqlite:///{db_path.as_posix()}", connect_args={"check_same_thread": False})
    _apply_test_sqlite_pragmas(eng)
    Base.metadata.create_all(bind=eng)
    sess = sessionmaker(bind=eng)()

    try:
        start = datetime(2026, 10, 30, 0, 0, 0)
        end = start + timedelta(seconds=10000)
        cfg = GeneratorConfig(
            profile_name="ten_k",
            seed=20261022,
            num_learners=3,
            num_courses=1,
            num_skills=4,
            num_content_items=5,
            num_attempts=3,
            num_learning_paths=2,
            num_cold_start_learners=1,
            start_date=start,
            end_date=end,
        )
        gen = SyntheticDataGenerator(sess, cfg)
        gen.generate()

        for att in sess.scalars(select(Attempt)).all():
            assert start <= att.started_at <= end
            if att.completed_at is not None:
                assert start <= att.completed_at <= end
                assert att.started_at <= att.completed_at
    finally:
        sess.close()
        eng.dispose()


def test_assessment_eligibility_and_score_invariants(fresh_session):
    """9. Verify assessment results exist only for completed QUIZ/LAB/PROJECT and satisfy score invariants."""
    generator = SyntheticDataGenerator(fresh_session, DEVELOPMENT_CONFIG)
    generator.generate()

    results = fresh_session.scalars(select(AssessmentResult)).all()
    assert len(results) > 0

    content_map = dict(
        fresh_session.execute(select(ContentItem.content_id, ContentItem.content_type)).all()
    )

    for res in results:
        attempt = fresh_session.get(Attempt, res.attempt_id)
        assert attempt is not None
        assert attempt.status == "COMPLETED"
        assert content_map[attempt.content_id] in ("QUIZ", "LAB", "PROJECT")

        assert 0.0 <= float(res.raw_score) <= float(res.max_score)
        assert float(res.max_score) == 100.0
        expected_norm = round(float(res.raw_score) / 100.0, 4)
        assert abs(float(res.normalized_score) - expected_norm) <= 0.0001
        assert res.graded_at >= attempt.completed_at
        assert res.graded_at <= DEVELOPMENT_CONFIG.end_date


def test_learning_paths_distribution_and_lifecycle_consistency(fresh_session):
    """10. Verify 80 learning paths distributed across population, and valid item lifecycle states."""
    generator = SyntheticDataGenerator(fresh_session, DEVELOPMENT_CONFIG)
    generator.generate()

    paths = fresh_session.scalars(select(LearningPath)).all()
    assert len(paths) == 80

    learners_with_paths = {p.learner_id for p in paths}
    assert len(learners_with_paths) == 80

    cold_ids = generator.get_cold_start_learner_ids()
    cold_start_with_paths = learners_with_paths.intersection(cold_ids)
    assert len(cold_start_with_paths) > 0, "Cold-start learners must be represented in learning paths!"

    # Verify lifecycle constraints on path items
    for path in paths:
        items = fresh_session.scalars(
            select(LearningPathItem)
            .where(LearningPathItem.path_id == path.path_id)
            .order_by(LearningPathItem.sequence_order)
        ).all()

        is_cold = generator.is_cold_start_learner(path.learner_id)
        seen_non_completed = False
        prev_completed_time: datetime | None = None

        for item in items:
            assert item.status in ("COMPLETED", "IN_PROGRESS", "PENDING", "SKIPPED")
            if is_cold:
                assert item.status != "COMPLETED", "Cold-start learner path must have zero completed items!"
                assert item.completed_at is None
            elif item.status == "COMPLETED":
                assert not seen_non_completed, "Completed items must strictly precede pending/in-progress items!"
                assert item.completed_at is not None
                assert DEVELOPMENT_CONFIG.start_date <= item.completed_at <= DEVELOPMENT_CONFIG.end_date
                if prev_completed_time is not None:
                    assert item.completed_at >= prev_completed_time
                prev_completed_time = item.completed_at
            else:
                seen_non_completed = True
                assert item.completed_at is None, f"{item.status} item must have completed_at=None"


def test_empty_supporting_tables_clean_baseline(fresh_session):
    """11. Verify clean baseline isolation: supporting tables have 0 rows."""
    generator = SyntheticDataGenerator(fresh_session, DEVELOPMENT_CONFIG)
    generator.generate()

    excluded = [MasterySnapshot, Recommendation, RecommendationOutcome, AuditEvent, DataIssue]
    for entity in excluded:
        count = fresh_session.scalar(select(func.count()).select_from(entity))
        assert count == 0, f"Table {entity.__tablename__} must remain empty in clean baseline!"


def test_dataset_signature_reproducibility_across_databases(tmp_path):
    """12. Verify two independent databases generated with seed 20261022 produce identical logical signatures."""
    db1 = tmp_path / "db1.db"
    db2 = tmp_path / "db2.db"

    eng1 = create_engine(f"sqlite:///{db1.as_posix()}", connect_args={"check_same_thread": False})
    eng2 = create_engine(f"sqlite:///{db2.as_posix()}", connect_args={"check_same_thread": False})
    _apply_test_sqlite_pragmas(eng1)
    _apply_test_sqlite_pragmas(eng2)
    Base.metadata.create_all(bind=eng1)
    Base.metadata.create_all(bind=eng2)

    sess1 = sessionmaker(bind=eng1)()
    sess2 = sessionmaker(bind=eng2)()

    try:
        gen1 = SyntheticDataGenerator(sess1, DEVELOPMENT_CONFIG)
        gen2 = SyntheticDataGenerator(sess2, DEVELOPMENT_CONFIG)
        gen1.generate()
        gen2.generate()

        sig1 = gen1.compute_dataset_signature()
        sig2 = gen2.compute_dataset_signature()

        assert sig1 == sig2
        assert len(sig1) == 64
    finally:
        sess1.close()
        sess2.close()
        eng1.dispose()
        eng2.dispose()


def test_dataset_signature_sensitivity_across_all_ten_tables(fresh_session):
    """13. Verify signature changes when any field in each of the ten baseline tables is mutated."""
    generator = SyntheticDataGenerator(fresh_session, DEVELOPMENT_CONFIG)
    generator.generate()

    baseline_sig = generator.compute_dataset_signature()

    # Table 1: Learner (first_name)
    row_learner = fresh_session.scalars(select(Learner).order_by(Learner.learner_id)).first()
    assert row_learner is not None
    orig_fn = row_learner.first_name
    row_learner.first_name = orig_fn + "_MUTATED"
    fresh_session.flush()
    assert generator.compute_dataset_signature() != baseline_sig
    row_learner.first_name = orig_fn
    fresh_session.flush()
    assert generator.compute_dataset_signature() == baseline_sig

    # Table 2: Course (title)
    row_course = fresh_session.scalars(select(Course).order_by(Course.course_id)).first()
    assert row_course is not None
    orig_ct = row_course.title
    row_course.title = orig_ct + "_MUTATED"
    fresh_session.flush()
    assert generator.compute_dataset_signature() != baseline_sig
    row_course.title = orig_ct
    fresh_session.flush()
    assert generator.compute_dataset_signature() == baseline_sig

    # Table 3: Skill (name)
    row_skill = fresh_session.scalars(select(Skill).order_by(Skill.skill_id)).first()
    assert row_skill is not None
    orig_sn = row_skill.name
    row_skill.name = orig_sn + "_MUTATED"
    fresh_session.flush()
    assert generator.compute_dataset_signature() != baseline_sig
    row_skill.name = orig_sn
    fresh_session.flush()
    assert generator.compute_dataset_signature() == baseline_sig

    # Table 4: SkillPrerequisite (minimum_mastery)
    row_prereq = fresh_session.scalars(
        select(SkillPrerequisite).order_by(SkillPrerequisite.skill_id, SkillPrerequisite.prerequisite_skill_id)
    ).first()
    if row_prereq:
        orig_mm = float(row_prereq.minimum_mastery)
        row_prereq.minimum_mastery = 0.85
        fresh_session.flush()
        assert generator.compute_dataset_signature() != baseline_sig
        row_prereq.minimum_mastery = orig_mm
        fresh_session.flush()
        assert generator.compute_dataset_signature() == baseline_sig

    # Table 5: ContentItem (duration_minutes)
    row_content = fresh_session.scalars(select(ContentItem).order_by(ContentItem.content_id)).first()
    assert row_content is not None
    orig_dur = row_content.duration_minutes
    row_content.duration_minutes = orig_dur + 5
    fresh_session.flush()
    assert generator.compute_dataset_signature() != baseline_sig
    row_content.duration_minutes = orig_dur
    fresh_session.flush()
    assert generator.compute_dataset_signature() == baseline_sig

    # Table 6: ContentSkill (relevance_weight)
    row_cs = fresh_session.scalars(
        select(ContentSkill).order_by(ContentSkill.content_id, ContentSkill.skill_id)
    ).first()
    assert row_cs is not None
    orig_rw = float(row_cs.relevance_weight)
    row_cs.relevance_weight = 0.65
    fresh_session.flush()
    assert generator.compute_dataset_signature() != baseline_sig
    row_cs.relevance_weight = orig_rw
    fresh_session.flush()
    assert generator.compute_dataset_signature() == baseline_sig

    # Table 7: Attempt (time_spent_seconds)
    row_att = fresh_session.scalars(select(Attempt).order_by(Attempt.attempt_id)).first()
    assert row_att is not None
    orig_tss = row_att.time_spent_seconds
    row_att.time_spent_seconds = (orig_tss or 100) + 10
    fresh_session.flush()
    assert generator.compute_dataset_signature() != baseline_sig
    row_att.time_spent_seconds = orig_tss
    fresh_session.flush()
    assert generator.compute_dataset_signature() == baseline_sig

    # Table 8: AssessmentResult (raw_score, normalized_score, and is_passed consistently)
    row_res = fresh_session.scalars(select(AssessmentResult).order_by(AssessmentResult.result_id)).first()
    assert row_res is not None
    orig_raw = float(row_res.raw_score)
    orig_norm = float(row_res.normalized_score)
    orig_passed = bool(row_res.is_passed)

    # Guaranteed different replacement value keeping score invariants consistent
    new_raw = 50.00 if orig_raw != 50.00 else 75.00
    new_norm = round(new_raw / 100.0, 4)
    new_passed = (new_norm >= 0.70)

    row_res.raw_score = new_raw
    row_res.normalized_score = new_norm
    row_res.is_passed = new_passed
    fresh_session.flush()
    assert generator.compute_dataset_signature() != baseline_sig

    # Restore all changed fields and verify original baseline signature returns
    row_res.raw_score = orig_raw
    row_res.normalized_score = orig_norm
    row_res.is_passed = orig_passed
    fresh_session.flush()
    assert generator.compute_dataset_signature() == baseline_sig

    # Table 9: LearningPath (title)
    row_lp = fresh_session.scalars(select(LearningPath).order_by(LearningPath.path_id)).first()
    assert row_lp is not None
    orig_pt = row_lp.title
    row_lp.title = orig_pt + "_MUTATED"
    fresh_session.flush()
    assert generator.compute_dataset_signature() != baseline_sig
    row_lp.title = orig_pt
    fresh_session.flush()
    assert generator.compute_dataset_signature() == baseline_sig

    # Table 10: LearningPathItem (status)
    row_lpi = fresh_session.scalars(
        select(LearningPathItem).order_by(LearningPathItem.path_item_id)
    ).first()
    assert row_lpi is not None
    orig_status = row_lpi.status
    row_lpi.status = "SKIPPED"
    fresh_session.flush()
    assert generator.compute_dataset_signature() != baseline_sig
    row_lpi.status = orig_status
    fresh_session.flush()
    assert generator.compute_dataset_signature() == baseline_sig


def test_transaction_rollback_cleans_all_tables_on_failure(fresh_session):
    """14. Verify full rollback across all tables after an exception and confirm session usability."""
    generator = SyntheticDataGenerator(fresh_session, DEVELOPMENT_CONFIG)

    # Inject failure after courses, skills, and content have been flushed
    def failing_learners():
        raise RuntimeError("Simulated mid-pipeline crash during learner generation")

    generator._generate_learners = failing_learners

    with pytest.raises(RuntimeError, match="Simulated mid-pipeline crash"):
        generator.generate()

    # Verify that all 15 tables are completely empty
    all_tables = [
        Learner, Course, Skill, SkillPrerequisite, ContentItem, ContentSkill,
        Attempt, AssessmentResult, LearningPath, LearningPathItem,
        MasterySnapshot, Recommendation, RecommendationOutcome, AuditEvent, DataIssue
    ]
    for entity in all_tables:
        count = fresh_session.scalar(select(func.count()).select_from(entity))
        assert count == 0, f"Table '{entity.__tablename__}' was not rolled back; contains {count} rows!"

    # Verify session remains usable for subsequent operations
    assert fresh_session.scalar(select(func.count()).select_from(Learner)) == 0
    test_learner = Learner(
        learner_id="LRN-RECOVERY",
        first_name="Recovered",
        last_name="User",
        email="recovered@skillpath.local",
        experience_level="BEGINNER",
        is_active=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    fresh_session.add(test_learner)
    fresh_session.commit()
    assert fresh_session.scalar(select(func.count()).select_from(Learner)) == 1


def test_transaction_rollback_preserves_preexisting_data_on_mid_pipeline_failure(fresh_session):
    """Verify rollback preserves a pre-existing record and cleans all flushed records when a failure occurs.

    Note: Bypassing _verify_database_empty is controlled test instrumentation to verify
    transactional recovery when previous rows exist in the session/database.
    """
    existing_course = Course(
        course_id="CRS-PREEXIST",
        title="Pre-existing Course",
        code="PRE-101",
        difficulty="BEGINNER",
        is_active=True,
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
    )
    fresh_session.add(existing_course)
    fresh_session.commit()

    generator = SyntheticDataGenerator(fresh_session, DEVELOPMENT_CONFIG)
    # Controlled test instrumentation: bypass initial emptiness check to evaluate rollback recovery
    generator._verify_database_empty = lambda: None

    def failing_courses():
        raise RuntimeError("Controlled mid-pipeline crash after skills have been flushed")

    generator._generate_courses = failing_courses

    with pytest.raises(RuntimeError, match="Controlled mid-pipeline crash"):
        generator.generate()

    # Verify pre-existing record is preserved untouched
    persisted = fresh_session.get(Course, "CRS-PREEXIST")
    assert persisted is not None
    assert persisted.title == "Pre-existing Course"
    assert persisted.code == "PRE-101"

    # Verify all newly generated tables were rolled back cleanly
    assert fresh_session.scalar(select(func.count()).select_from(Skill)) == 0
    assert fresh_session.scalar(select(func.count()).select_from(Learner)) == 0
    assert fresh_session.scalar(select(func.count()).select_from(Course)) == 1


def test_populated_database_refusal_preserves_existing_data(fresh_session):
    """15. Verify refusal to generate when data exists, preserving original rows unchanged."""
    existing_course = Course(
        course_id="CRS-PREEXIST",
        title="Pre-existing Catalog Course",
        code="PRE-101",
        difficulty="BEGINNER",
        is_active=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    fresh_session.add(existing_course)
    fresh_session.commit()

    all_tables = [
        Learner, Course, Skill, SkillPrerequisite, ContentItem, ContentSkill,
        Attempt, AssessmentResult, LearningPath, LearningPathItem,
        MasterySnapshot, Recommendation, RecommendationOutcome, AuditEvent, DataIssue
    ]
    initial_counts = {entity: fresh_session.scalar(select(func.count()).select_from(entity)) for entity in all_tables}

    generator = SyntheticDataGenerator(fresh_session, DEVELOPMENT_CONFIG)
    with pytest.raises(RuntimeError, match="Target database is not empty"):
        generator.generate()

    # Pre-existing record must remain untouched
    persisted = fresh_session.get(Course, "CRS-PREEXIST")
    assert persisted is not None
    assert persisted.title == "Pre-existing Catalog Course"
    assert persisted.code == "PRE-101"
    assert persisted.difficulty == "BEGINNER"

    # All table counts must remain identical
    post_counts = {entity: fresh_session.scalar(select(func.count()).select_from(entity)) for entity in all_tables}
    assert initial_counts == post_counts


def test_refusal_to_run_twice_preventing_duplicate_append(fresh_session):
    """16. Verify generator refuses to append duplicate data on a second invocation."""
    generator = SyntheticDataGenerator(fresh_session, DEVELOPMENT_CONFIG)
    summary = generator.generate()
    assert summary["attempts"] == 2000

    all_tables = [
        Learner, Course, Skill, SkillPrerequisite, ContentItem, ContentSkill,
        Attempt, AssessmentResult, LearningPath, LearningPathItem
    ]
    initial_counts = {entity: fresh_session.scalar(select(func.count()).select_from(entity)) for entity in all_tables}

    # Second invocation must be rejected
    with pytest.raises(RuntimeError, match="Target database is not empty"):
        generator.generate()

    # Confirm counts across all tables remain exactly unchanged
    post_counts = {entity: fresh_session.scalar(select(func.count()).select_from(entity)) for entity in all_tables}
    assert initial_counts == post_counts


def test_generator_config_validation():
    """17. Verify GeneratorConfig rejects invalid parameters, booleans, and boundary violations."""
    # 1. Boolean rejection
    with pytest.raises(ValueError, match="must be an int"):
        GeneratorConfig(
            profile_name="bad",
            seed=True,  # type: ignore
            num_learners=100,
            num_courses=10,
            num_skills=50,
            num_content_items=100,
            num_attempts=2000,
            num_learning_paths=80,
            num_cold_start_learners=10,
        )

    # 2. Empty profile name
    with pytest.raises(ValueError, match="non-empty string"):
        GeneratorConfig(
            profile_name="",
            seed=20261022,
            num_learners=100,
            num_courses=10,
            num_skills=50,
            num_content_items=100,
            num_attempts=2000,
            num_learning_paths=80,
            num_cold_start_learners=10,
        )

    # 3. Content-type proportions: extra key
    with pytest.raises(ValueError, match="Unexpected extra content types"):
        GeneratorConfig(
            profile_name="bad_extra",
            seed=20261022,
            num_learners=100,
            num_courses=10,
            num_skills=50,
            num_content_items=100,
            num_attempts=2000,
            num_learning_paths=80,
            num_cold_start_learners=10,
            content_type_proportions={
                "VIDEO": 0.35, "READING": 0.25, "QUIZ": 0.20, "LAB": 0.10, "PROJECT": 0.05, "EXTRA": 0.05
            },
        )

    # 4. Content-type proportions: missing key
    with pytest.raises(ValueError, match="Missing required content types"):
        GeneratorConfig(
            profile_name="bad_missing",
            seed=20261022,
            num_learners=100,
            num_courses=10,
            num_skills=50,
            num_content_items=100,
            num_attempts=2000,
            num_learning_paths=80,
            num_cold_start_learners=10,
            content_type_proportions={
                "VIDEO": 0.35, "READING": 0.25, "QUIZ": 0.20, "LAB": 0.20
            },
        )

    # 5. Content-type proportions: negative value
    with pytest.raises(ValueError, match="non-negative finite number"):
        GeneratorConfig(
            profile_name="bad_neg",
            seed=20261022,
            num_learners=100,
            num_courses=10,
            num_skills=50,
            num_content_items=100,
            num_attempts=2000,
            num_learning_paths=80,
            num_cold_start_learners=10,
            content_type_proportions={
                "VIDEO": -0.10, "READING": 0.40, "QUIZ": 0.30, "LAB": 0.20, "PROJECT": 0.20
            },
        )

    # 6. Content-type proportions: non-finite value
    with pytest.raises(ValueError, match="non-negative finite number"):
        GeneratorConfig(
            profile_name="bad_nan",
            seed=20261022,
            num_learners=100,
            num_courses=10,
            num_skills=50,
            num_content_items=100,
            num_attempts=2000,
            num_learning_paths=80,
            num_cold_start_learners=10,
            content_type_proportions={
                "VIDEO": float("nan"), "READING": 0.25, "QUIZ": 0.20, "LAB": 0.15, "PROJECT": 0.05
            },
        )

    # 7. Content-type proportions: invalid sum
    with pytest.raises(ValueError, match="must sum to 1.0"):
        GeneratorConfig(
            profile_name="bad_sum",
            seed=20261022,
            num_learners=100,
            num_courses=10,
            num_skills=50,
            num_content_items=100,
            num_attempts=2000,
            num_learning_paths=80,
            num_cold_start_learners=10,
            content_type_proportions={
                "VIDEO": 0.30, "READING": 0.25, "QUIZ": 0.20, "LAB": 0.15, "PROJECT": 0.05
            },
        )

    # 8. Negative seed
    with pytest.raises(ValueError, match="non-negative integer"):
        GeneratorConfig(
            profile_name="bad_seed",
            seed=-1,
            num_learners=100,
            num_courses=10,
            num_skills=50,
            num_content_items=100,
            num_attempts=2000,
            num_learning_paths=80,
            num_cold_start_learners=10,
        )

    # 9. Cold start exceeds or equals total learners
    with pytest.raises(ValueError, match="strictly less than num_learners"):
        GeneratorConfig(
            profile_name="bad",
            seed=20261022,
            num_learners=100,
            num_courses=10,
            num_skills=50,
            num_content_items=100,
            num_attempts=2000,
            num_learning_paths=80,
            num_cold_start_learners=100,
        )

    # 10. Attempts fewer than active learners
    with pytest.raises(ValueError, match="must be >= active learners"):
        GeneratorConfig(
            profile_name="bad",
            seed=20261022,
            num_learners=100,
            num_courses=10,
            num_skills=50,
            num_content_items=100,
            num_attempts=50,  # 50 attempts for 90 active learners
            num_learning_paths=80,
            num_cold_start_learners=10,
        )

    # 11. Learning paths exceed learners
    with pytest.raises(ValueError, match="cannot exceed num_learners"):
        GeneratorConfig(
            profile_name="bad",
            seed=20261022,
            num_learners=100,
            num_courses=10,
            num_skills=50,
            num_content_items=100,
            num_attempts=2000,
            num_learning_paths=150,
            num_cold_start_learners=10,
        )

    # 12. Inverted date range
    with pytest.raises(ValueError, match="must be strictly after start_date"):
        GeneratorConfig(
            profile_name="bad",
            seed=20261022,
            num_learners=100,
            num_courses=10,
            num_skills=50,
            num_content_items=100,
            num_attempts=2000,
            num_learning_paths=80,
            num_cold_start_learners=10,
            start_date=datetime(2026, 10, 30),
            end_date=datetime(2026, 1, 1),
        )


def test_timezone_validation():
    """Verify timezone validation: reject mixed naive/aware and accept compatible aware datetimes."""
    # 1. Reject mixed naive/aware timestamps
    with pytest.raises(ValueError, match="timezone-aware"):
        GeneratorConfig(
            profile_name="mixed_tz",
            seed=20261022,
            num_learners=100,
            num_courses=10,
            num_skills=50,
            num_content_items=100,
            num_attempts=2000,
            num_learning_paths=80,
            num_cold_start_learners=10,
            start_date=datetime(2026, 1, 1),
            end_date=datetime(2026, 10, 30, tzinfo=timezone.utc),
        )

    # 2. Accept compatible UTC-aware timestamps
    cfg_utc = GeneratorConfig(
        profile_name="aware_utc",
        seed=20261022,
        num_learners=100,
        num_courses=10,
        num_skills=50,
        num_content_items=100,
        num_attempts=2000,
        num_learning_paths=80,
        num_cold_start_learners=10,
        start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end_date=datetime(2026, 10, 30, tzinfo=timezone.utc),
    )
    assert cfg_utc.start_date.tzinfo == timezone.utc
    assert cfg_utc.end_date.tzinfo == timezone.utc

    # 3. Accept compatible aware timestamps with different timezone offsets
    tz_plus_5 = timezone(timedelta(hours=5))
    cfg_diff_tz = GeneratorConfig(
        profile_name="aware_diff_tz",
        seed=20261022,
        num_learners=100,
        num_courses=10,
        num_skills=50,
        num_content_items=100,
        num_attempts=2000,
        num_learning_paths=80,
        num_cold_start_learners=10,
        start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end_date=datetime(2026, 10, 30, tzinfo=tz_plus_5),
    )
    assert cfg_diff_tz.start_date.tzinfo == timezone.utc
    assert cfg_diff_tz.end_date.tzinfo == tz_plus_5


def test_generator_config_immutability():
    """Verify content_type_proportions cannot be mutated on an instantiated configuration."""
    props = {
        "VIDEO": 0.35, "READING": 0.25, "QUIZ": 0.20, "LAB": 0.15, "PROJECT": 0.05
    }
    cfg = GeneratorConfig(
        profile_name="immutability_test",
        seed=20261022,
        num_learners=100,
        num_courses=10,
        num_skills=50,
        num_content_items=100,
        num_attempts=2000,
        num_learning_paths=80,
        num_cold_start_learners=10,
        content_type_proportions=props,
    )

    # Modifying caller's original dictionary must not alter the configuration
    props["VIDEO"] = 0.99
    assert cfg.content_type_proportions["VIDEO"] == 0.35

    # Direct mutation of the mapping proxy must raise TypeError
    with pytest.raises(TypeError):
        cfg.content_type_proportions["VIDEO"] = 0.99  # type: ignore