"""Automated verification suite for database-level constraints, cascades, and boundaries.

Tests cover:
1. Enum rejection (Learner, Course, ContentItem, Attempt).
2. Acceptance of valid zero assessment scores.
3. Rejection of negative raw scores and zero maximum scores.
4. Prevention of self-prerequisites (skill cannot require itself).
5. Uniqueness of (learner_id, content_id, attempt_number).
6. Uniqueness of (path_id, sequence_order).
7. Cascade deletion of AssessmentResult upon Attempt deletion.
8. Cascade deletion of ContentSkill upon ContentItem deletion and RESTRICT on Skill deletion.
9. Permissibility of storing timestamp-inverted attempts for anomaly fixture support.
"""

from datetime import datetime, timedelta
import pytest
from sqlalchemy import create_engine, select, text
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
)


@pytest.fixture(scope="module")
def isolated_db(tmp_path_factory):
    """Create an isolated temporary SQLite database with active pragmas."""
    temp_dir = tmp_path_factory.mktemp("db_constraints_test")
    test_db_path = temp_dir / "isolated_constraints.db"
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


def test_invalid_enum_values_rejected(isolated_db):
    """1. Verify that invalid enum strings are rejected for Learner, Course, ContentItem, and Attempt."""
    _, TestSession = isolated_db
    now = datetime.utcnow()

    with TestSession() as session:
        # A. Invalid Learner.experience_level
        invalid_learner = Learner(
            learner_id="LRN-ENUM-BAD",
            first_name="Invalid",
            last_name="Learner",
            email="invalid.learner@skillpath.local",
            experience_level="EXPERT",  # Allowed: 'BEGINNER', 'INTERMEDIATE', 'ADVANCED'
            created_at=now,
            updated_at=now,
        )
        session.add(invalid_learner)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        # B. Invalid Course.difficulty
        invalid_course = Course(
            course_id="CRS-ENUM-BAD",
            title="Invalid Difficulty Course",
            code="BAD-DIFF-101",
            difficulty="MASTER",  # Allowed: 'BEGINNER', 'INTERMEDIATE', 'ADVANCED'
            created_at=now,
            updated_at=now,
        )
        session.add(invalid_course)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        # Create valid Course to support ContentItem test
        valid_course = Course(
            course_id="CRS-ENUM-OK",
            title="Valid Course",
            code="OK-101",
            difficulty="BEGINNER",
            created_at=now,
            updated_at=now,
        )
        session.add(valid_course)
        session.commit()

        # C. Invalid ContentItem.content_type
        invalid_content = ContentItem(
            content_id="CNT-ENUM-BAD",
            course_id="CRS-ENUM-OK",
            title="Invalid Type Item",
            content_type="PODCAST",  # Allowed: 'VIDEO', 'READING', 'QUIZ', 'LAB', 'PROJECT'
            difficulty=0.50,
            duration_minutes=30,
            created_at=now,
            updated_at=now,
        )
        session.add(invalid_content)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        # Create valid Learner & ContentItem to support Attempt test
        valid_learner = Learner(
            learner_id="LRN-ENUM-OK",
            first_name="Valid",
            last_name="Learner",
            email="valid.learner@skillpath.local",
            experience_level="BEGINNER",
            created_at=now,
            updated_at=now,
        )
        valid_content = ContentItem(
            content_id="CNT-ENUM-OK",
            course_id="CRS-ENUM-OK",
            title="Valid Content Item",
            content_type="QUIZ",
            difficulty=0.50,
            duration_minutes=15,
            created_at=now,
            updated_at=now,
        )
        session.add_all([valid_learner, valid_content])
        session.commit()

        # D. Invalid Attempt.status
        invalid_attempt = Attempt(
            attempt_id="ATT-ENUM-BAD",
            learner_id="LRN-ENUM-OK",
            content_id="CNT-ENUM-OK",
            attempt_number=1,
            started_at=now,
            status="PAUSED",  # Allowed: 'IN_PROGRESS', 'COMPLETED', 'ABANDONED'
        )
        session.add(invalid_attempt)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_zero_assessment_score_accepted(isolated_db):
    """2. Verify that a measured zero assessment score is accepted by the database constraints."""
    _, TestSession = isolated_db
    now = datetime.utcnow()

    with TestSession() as session:
        learner = Learner(
            learner_id="LRN-ZERO-001",
            first_name="Zero",
            last_name="Scorer",
            email="zero.scorer@skillpath.local",
            experience_level="BEGINNER",
            created_at=now,
            updated_at=now,
        )
        course = Course(
            course_id="CRS-ZERO-001",
            title="Zero Score Course",
            code="ZERO-101",
            difficulty="BEGINNER",
            created_at=now,
            updated_at=now,
        )
        content = ContentItem(
            content_id="CNT-ZERO-001",
            course_id="CRS-ZERO-001",
            title="Zero Score Quiz",
            content_type="QUIZ",
            difficulty=0.20,
            duration_minutes=10,
            created_at=now,
            updated_at=now,
        )
        attempt = Attempt(
            attempt_id="ATT-ZERO-001",
            learner_id="LRN-ZERO-001",
            content_id="CNT-ZERO-001",
            attempt_number=1,
            started_at=now,
            completed_at=now,
            status="COMPLETED",
        )
        session.add_all([learner, course, content, attempt])
        session.commit()

        # Valid measured zero score
        zero_result = AssessmentResult(
            result_id="RES-ZERO-001",
            attempt_id="ATT-ZERO-001",
            raw_score=0.0,
            max_score=100.0,
            normalized_score=0.0,
            is_passed=False,
            graded_at=now,
        )
        session.add(zero_result)
        session.commit()

        # Verify persistence and values
        persisted = session.scalar(
            select(AssessmentResult).where(AssessmentResult.result_id == "RES-ZERO-001")
        )
        assert persisted is not None
        assert float(persisted.raw_score) == 0.0
        assert float(persisted.normalized_score) == 0.0
        assert persisted.is_passed is False


def test_negative_raw_score_and_zero_max_score_rejected(isolated_db):
    """3. Verify that negative raw scores and zero max scores are rejected by check constraints."""
    _, TestSession = isolated_db
    now = datetime.utcnow()

    with TestSession() as session:
        learner = Learner(
            learner_id="LRN-BOUNDS-001",
            first_name="Bounds",
            last_name="Tester",
            email="bounds.tester@skillpath.local",
            experience_level="BEGINNER",
            created_at=now,
            updated_at=now,
        )
        course = Course(
            course_id="CRS-BOUNDS-001",
            title="Bounds Course",
            code="BOUNDS-101",
            difficulty="BEGINNER",
            created_at=now,
            updated_at=now,
        )
        content = ContentItem(
            content_id="CNT-BOUNDS-001",
            course_id="CRS-BOUNDS-001",
            title="Bounds Quiz",
            content_type="QUIZ",
            difficulty=0.30,
            duration_minutes=15,
            created_at=now,
            updated_at=now,
        )
        attempt1 = Attempt(
            attempt_id="ATT-BOUNDS-001",
            learner_id="LRN-BOUNDS-001",
            content_id="CNT-BOUNDS-001",
            attempt_number=1,
            started_at=now,
            completed_at=now,
            status="COMPLETED",
        )
        attempt2 = Attempt(
            attempt_id="ATT-BOUNDS-002",
            learner_id="LRN-BOUNDS-001",
            content_id="CNT-BOUNDS-001",
            attempt_number=2,
            started_at=now,
            completed_at=now,
            status="COMPLETED",
        )
        session.add_all([learner, course, content, attempt1, attempt2])
        session.commit()

        # A. Negative raw score (-1.00) must violate chk_raw_score_nonneg
        negative_raw = AssessmentResult(
            result_id="RES-BOUNDS-NEG",
            attempt_id="ATT-BOUNDS-001",
            raw_score=-1.00,
            max_score=100.00,
            normalized_score=0.0000,
            is_passed=False,
            graded_at=now,
        )
        session.add(negative_raw)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        # B. Zero max score (0.00) must violate chk_max_score_positive
        zero_max = AssessmentResult(
            result_id="RES-BOUNDS-ZERO-MAX",
            attempt_id="ATT-BOUNDS-002",
            raw_score=0.00,
            max_score=0.00,
            normalized_score=0.0000,
            is_passed=False,
            graded_at=now,
        )
        session.add(zero_max)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_skill_cannot_be_its_own_prerequisite(isolated_db):
    """4. Verify that a skill cannot reference itself as a prerequisite (chk_prereq_no_self)."""
    _, TestSession = isolated_db
    now = datetime.utcnow()

    with TestSession() as session:
        skill = Skill(
            skill_id="SKL-SELF-001",
            name="Self Loop Skill",
            domain="Computer Science",
            difficulty_level=0.50,
            created_at=now,
            updated_at=now,
        )
        session.add(skill)
        session.commit()

        self_prereq = SkillPrerequisite(
            skill_id="SKL-SELF-001",
            prerequisite_skill_id="SKL-SELF-001",
            minimum_mastery=0.70,
            is_required=True,
            created_at=now,
        )
        session.add(self_prereq)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_duplicate_learner_content_attempt_number_rejected(isolated_db):
    """5. Verify that duplicate (learner_id, content_id, attempt_number) records are rejected."""
    _, TestSession = isolated_db
    now = datetime.utcnow()

    with TestSession() as session:
        learner = Learner(
            learner_id="LRN-UQATT-001",
            first_name="Unique",
            last_name="Attempt",
            email="uq.attempt@skillpath.local",
            experience_level="BEGINNER",
            created_at=now,
            updated_at=now,
        )
        course = Course(
            course_id="CRS-UQATT-001",
            title="Unique Attempt Course",
            code="UQATT-101",
            difficulty="BEGINNER",
            created_at=now,
            updated_at=now,
        )
        content = ContentItem(
            content_id="CNT-UQATT-001",
            course_id="CRS-UQATT-001",
            title="Unique Attempt Item",
            content_type="LAB",
            difficulty=0.40,
            duration_minutes=25,
            created_at=now,
            updated_at=now,
        )
        session.add_all([learner, course, content])
        session.commit()

        # First attempt (attempt_number=1)
        attempt1 = Attempt(
            attempt_id="ATT-UQATT-001-A",
            learner_id="LRN-UQATT-001",
            content_id="CNT-UQATT-001",
            attempt_number=1,
            started_at=now,
            status="COMPLETED",
        )
        session.add(attempt1)
        session.commit()

        # Duplicate attempt (same learner, content, attempt_number=1)
        attempt2 = Attempt(
            attempt_id="ATT-UQATT-001-B",
            learner_id="LRN-UQATT-001",
            content_id="CNT-UQATT-001",
            attempt_number=1,
            started_at=now + timedelta(hours=1),
            status="IN_PROGRESS",
        )
        session.add(attempt2)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_duplicate_learning_path_sequence_order_rejected(isolated_db):
    """6. Verify that duplicate sequence positions in the same learning path are rejected."""
    _, TestSession = isolated_db
    now = datetime.utcnow()

    with TestSession() as session:
        learner = Learner(
            learner_id="LRN-PATH-001",
            first_name="Path",
            last_name="Learner",
            email="path.learner@skillpath.local",
            experience_level="INTERMEDIATE",
            created_at=now,
            updated_at=now,
        )
        course = Course(
            course_id="CRS-PATH-001",
            title="Path Course",
            code="PATH-101",
            difficulty="INTERMEDIATE",
            created_at=now,
            updated_at=now,
        )
        content1 = ContentItem(
            content_id="CNT-PATH-001",
            course_id="CRS-PATH-001",
            title="Path Content 1",
            content_type="READING",
            difficulty=0.30,
            duration_minutes=20,
            created_at=now,
            updated_at=now,
        )
        content2 = ContentItem(
            content_id="CNT-PATH-002",
            course_id="CRS-PATH-001",
            title="Path Content 2",
            content_type="QUIZ",
            difficulty=0.50,
            duration_minutes=20,
            created_at=now,
            updated_at=now,
        )
        learning_path = LearningPath(
            path_id="PATH-2026-TEST01",
            learner_id="LRN-PATH-001",
            title="Data Track",
            status="ACTIVE",
            created_at=now,
            updated_at=now,
        )
        session.add_all([learner, course, content1, content2, learning_path])
        session.commit()

        # Item at sequence position 1
        item1 = LearningPathItem(
            path_item_id="LPI-PATH-001",
            path_id="PATH-2026-TEST01",
            content_id="CNT-PATH-001",
            sequence_order=1,
            is_mandatory=True,
            status="COMPLETED",
        )
        session.add(item1)
        session.commit()

        # Conflicting item at duplicate sequence position 1 in same path
        item2 = LearningPathItem(
            path_item_id="LPI-PATH-002",
            path_id="PATH-2026-TEST01",
            content_id="CNT-PATH-002",
            sequence_order=1,
            is_mandatory=True,
            status="PENDING",
        )
        session.add(item2)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_attempt_delete_cascades_to_assessment_result(isolated_db):
    """7. Verify that deleting an Attempt removes its AssessmentResult via configured cascade."""
    _, TestSession = isolated_db
    now = datetime.utcnow()

    with TestSession() as session:
        learner = Learner(
            learner_id="LRN-CASC-001",
            first_name="Cascade",
            last_name="Tester",
            email="cascade.tester@skillpath.local",
            experience_level="ADVANCED",
            created_at=now,
            updated_at=now,
        )
        course = Course(
            course_id="CRS-CASC-001",
            title="Cascade Course",
            code="CASC-101",
            difficulty="ADVANCED",
            created_at=now,
            updated_at=now,
        )
        content = ContentItem(
            content_id="CNT-CASC-001",
            course_id="CRS-CASC-001",
            title="Cascade Quiz",
            content_type="QUIZ",
            difficulty=0.70,
            duration_minutes=30,
            created_at=now,
            updated_at=now,
        )
        attempt = Attempt(
            attempt_id="ATT-CASC-001",
            learner_id="LRN-CASC-001",
            content_id="CNT-CASC-001",
            attempt_number=1,
            started_at=now,
            completed_at=now,
            status="COMPLETED",
        )
        result = AssessmentResult(
            result_id="RES-CASC-001",
            attempt_id="ATT-CASC-001",
            raw_score=80.0,
            max_score=100.0,
            normalized_score=0.8000,
            is_passed=True,
            graded_at=now,
        )
        session.add_all([learner, course, content, attempt, result])
        session.commit()

        # Delete the attempt using SQLAlchemy session
        attempt_to_delete = session.get(Attempt, "ATT-CASC-001")
        session.delete(attempt_to_delete)
        session.commit()

    # Verify absence using a fresh, independent session
    with TestSession() as fresh_session:
        deleted_attempt = fresh_session.get(Attempt, "ATT-CASC-001")
        deleted_result = fresh_session.get(AssessmentResult, "RES-CASC-001")
        assert deleted_attempt is None
        assert deleted_result is None

        # Verify directly at raw SQL engine level
        raw_count = fresh_session.execute(
            text("SELECT count(*) FROM assessment_results WHERE attempt_id = 'ATT-CASC-001'")
        ).scalar()
        assert raw_count == 0


def test_content_delete_cascades_and_skill_delete_restricts(isolated_db):
    """8. Verify ContentItem delete cascades to ContentSkill, and Skill delete is RESTRICTed."""
    _, TestSession = isolated_db
    now = datetime.utcnow()

    with TestSession() as session:
        course = Course(
            course_id="CRS-REL-001",
            title="Relational Test Course",
            code="REL-101",
            difficulty="BEGINNER",
            created_at=now,
            updated_at=now,
        )
        content = ContentItem(
            content_id="CNT-REL-001",
            course_id="CRS-REL-001",
            title="Relational Item",
            content_type="LAB",
            difficulty=0.50,
            duration_minutes=20,
            created_at=now,
            updated_at=now,
        )
        skill = Skill(
            skill_id="SKL-REL-001",
            name="Relational Integrity Skill",
            domain="Database",
            difficulty_level=0.50,
            created_at=now,
            updated_at=now,
        )
        cs_link = ContentSkill(
            content_id="CNT-REL-001",
            skill_id="SKL-REL-001",
            relevance_weight=1.00,
        )
        session.add_all([course, content, skill, cs_link])
        session.commit()

        # A. Attempting to delete referenced Skill must raise IntegrityError (ON DELETE RESTRICT)
        skill_to_delete = session.get(Skill, "SKL-REL-001")
        session.delete(skill_to_delete)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        # Verify ContentSkill still exists
        link_after_failed_delete = session.scalar(
            select(ContentSkill).where(
                ContentSkill.content_id == "CNT-REL-001",
                ContentSkill.skill_id == "SKL-REL-001",
            )
        )
        assert link_after_failed_delete is not None

        # B. Deleting ContentItem must cascade-delete the ContentSkill mapping
        content_to_delete = session.get(ContentItem, "CNT-REL-001")
        session.delete(content_to_delete)
        session.commit()

    # Verify cascade deletion using a fresh, independent session
    with TestSession() as fresh_session:
        remaining_content = fresh_session.get(ContentItem, "CNT-REL-001")
        remaining_link = fresh_session.scalar(
            select(ContentSkill).where(ContentSkill.content_id == "CNT-REL-001")
        )
        remaining_skill = fresh_session.get(Skill, "SKL-REL-001")

        assert remaining_content is None
        assert remaining_link is None
        # Parent Skill must still exist untouched
        assert remaining_skill is not None


def test_inverted_attempt_timestamp_permitted_in_storage(isolated_db):
    """9. Verify schema allows completed_at < started_at to support Anomaly Type 2 fixture creation."""
    _, TestSession = isolated_db
    now = datetime.utcnow()
    earlier = now - timedelta(hours=1)

    with TestSession() as session:
        learner = Learner(
            learner_id="LRN-ANOM2-001",
            first_name="Anomaly",
            last_name="Tester",
            email="anomaly2.tester@skillpath.local",
            experience_level="BEGINNER",
            created_at=now,
            updated_at=now,
        )
        course = Course(
            course_id="CRS-ANOM2-001",
            title="Anomaly Course",
            code="ANOM2-101",
            difficulty="BEGINNER",
            created_at=now,
            updated_at=now,
        )
        content = ContentItem(
            content_id="CNT-ANOM2-001",
            course_id="CRS-ANOM2-001",
            title="Anomaly Item",
            content_type="READING",
            difficulty=0.30,
            duration_minutes=15,
            created_at=now,
            updated_at=now,
        )
        session.add_all([learner, course, content])
        session.commit()

        # Inverted attempt: completed_at precedes started_at (Anomaly Type 2 fixture)
        inverted_attempt = Attempt(
            attempt_id="ATT-ANOM2-INVERTED-001",
            learner_id="LRN-ANOM2-001",
            content_id="CNT-ANOM2-001",
            attempt_number=1,
            started_at=now,
            completed_at=earlier,
            status="COMPLETED",
        )
        session.add(inverted_attempt)
        # Must commit successfully because the DB does not impose a timestamp-ordering check
        session.commit()

        persisted = session.get(Attempt, "ATT-ANOM2-INVERTED-001")
        assert persisted is not None
        assert persisted.completed_at < persisted.started_at