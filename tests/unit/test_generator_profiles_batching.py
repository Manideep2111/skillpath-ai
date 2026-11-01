"""Unit and integration tests for synthetic generator profiles, memory-safe batching, and safety guards."""

from datetime import datetime
import os
from pathlib import Path
import sqlite3
import pytest
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from src.db.database import Base
from src.models.entities import Attempt, AssessmentResult, Learner, Skill, ContentItem
from src.services.generator.synthetic_engine import (
    PROFILES,
    DEVELOPMENT_CONFIG,
    INTEGRATION_CONFIG,
    FULL_CONFIG,
    GeneratorConfig,
    SyntheticDataGenerator,
)
from generate_data import validate_target_safety, PROTECTED_BASELINE_PATH


def _apply_pragmas(target_engine):
    @event.listens_for(target_engine, "connect")
    def set_pragmas(dbapi_conn, rec):
        if isinstance(dbapi_conn, sqlite3.Connection):
            c = dbapi_conn.cursor()
            c.execute("PRAGMA foreign_keys = ON;")
            c.close()


@pytest.fixture
def temp_db(tmp_path: Path):
    """Create isolated SQLite database with all 15 ORM tables."""
    db_file = tmp_path / "test_profiles.db"
    engine = create_engine(f"sqlite:///{db_file.as_posix()}", connect_args={"check_same_thread": False})
    _apply_pragmas(engine)
    Base.metadata.create_all(bind=engine)
    SessionMaker = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    yield db_file, engine, SessionMaker
    engine.dispose()


# ---------------------------------------------------------------------------
# Task A: Generator Profiles Tests
# ---------------------------------------------------------------------------

def test_profiles_dictionary_definitions():
    """Verify all 3 required profiles are registered and configured per specification."""
    assert "development" in PROFILES
    assert "integration" in PROFILES
    assert "full" in PROFILES

    dev = PROFILES["development"]
    assert dev.num_learners == 100
    assert dev.num_skills == 50
    assert dev.num_content_items == 100
    assert dev.num_attempts == 2000
    assert dev.seed == 20261022

    integ = PROFILES["integration"]
    assert integ.num_learners == 500
    assert integ.num_skills == 200
    assert integ.num_content_items == 500
    assert integ.num_attempts == 20000
    assert integ.num_courses == 50
    assert integ.num_learning_paths == 400
    assert integ.num_cold_start_learners == 50
    assert integ.seed == 20261022

    full = PROFILES["full"]
    assert full.num_learners == 10000
    assert full.num_skills == 500
    assert full.num_content_items == 2000
    assert full.num_attempts == 500000
    assert full.seed == 20261022


def test_baseline_target_safety_guard(tmp_path: Path):
    """Verify validate_target_safety strictly rejects the baseline database under any conditions."""
    # 1. Pointing directly to skillpath.db without overwrite
    with pytest.raises(ValueError, match="CRITICAL SAFETY VIOLATION"):
        validate_target_safety(PROTECTED_BASELINE_PATH, overwrite=False)

    # 2. Pointing to skillpath.db even WITH overwrite=True
    with pytest.raises(ValueError, match="CRITICAL SAFETY VIOLATION"):
        validate_target_safety(PROTECTED_BASELINE_PATH, overwrite=True)

    # 3. Case-insensitive normalization check
    lowercase_baseline = Path(str(PROTECTED_BASELINE_PATH).lower())
    with pytest.raises(ValueError, match="CRITICAL SAFETY VIOLATION"):
        validate_target_safety(lowercase_baseline, overwrite=True)


def test_existing_output_overwrite_protection(tmp_path: Path):
    """Verify existing output file is protected unless --overwrite is explicitly passed."""
    existing_file = tmp_path / "already_exists.db"
    existing_file.write_text("dummy content")

    # Should raise ValueError when overwrite=False
    with pytest.raises(ValueError, match="already exists"):
        validate_target_safety(existing_file, overwrite=False)

    # Should succeed when overwrite=True
    validate_target_safety(existing_file, overwrite=True)
    assert not existing_file.exists(), "Existing file should be unlinked when overwrite=True"


# ---------------------------------------------------------------------------
# Task B: Memory-Safe Batching Tests
# ---------------------------------------------------------------------------

def test_memory_safe_batching_multiple_batches(temp_db):
    """Verify batching works correctly across multiple small batches (batch_size=50)."""
    db_file, engine, SessionMaker = temp_db

    with SessionMaker() as session:
        # Run development generation with small batch size 50 to force 40 batches
        generator = SyntheticDataGenerator(session=session, config=DEVELOPMENT_CONFIG, batch_size=50)
        summary = generator.generate()

        assert summary["attempts"] == 2000
        assert summary["assessment_results"] == 705

        # Verify foreign keys across all batches
        violations = session.execute(text("PRAGMA foreign_key_check;")).fetchall()
        assert len(violations) == 0, f"Foreign key violations found: {violations}"

        # Verify exact database counts match
        db_attempts = session.scalar(select(func.count(Attempt.attempt_id)))
        db_results = session.scalar(select(func.count(AssessmentResult.result_id)))
        assert db_attempts == 2000
        assert db_results == 705


def test_batching_reproducibility_signature_match(temp_db):
    """Verify that batch_size does not alter deterministic output or logical signature."""
    db_file, engine, SessionMaker = temp_db

    with SessionMaker() as session:
        generator = SyntheticDataGenerator(session=session, config=DEVELOPMENT_CONFIG, batch_size=250)
        generator.generate()
        sig = generator.compute_dataset_signature()
        # Must match canonical baseline signature
        assert sig == "381cf8e130e9b58a31224dc946ce65b9db58f44c23407138368c906e4d683e04"


def test_batching_transactional_rollback_on_failure(temp_db):
    """Verify that if generation fails mid-stream, all flushed batches are completely rolled back."""
    db_file, engine, SessionMaker = temp_db

    class FailingGenerator(SyntheticDataGenerator):
        def _generate_attempts_and_assessments(self, learners, content_items):
            # Generate first batch then simulate sudden failure
            super()._generate_attempts_and_assessments(learners, content_items)
            raise RuntimeError("Simulated transient failure mid-generation")

    with SessionMaker() as session:
        gen = FailingGenerator(session=session, config=DEVELOPMENT_CONFIG, batch_size=100)
        with pytest.raises(RuntimeError, match="Simulated transient failure"):
            gen.generate()

    # Re-open session and verify database is completely empty (zero attempts, zero learners)
    with SessionMaker() as session:
        count_attempts = session.scalar(select(func.count(Attempt.attempt_id)))
        count_learners = session.scalar(select(func.count(Learner.learner_id)))
        assert count_attempts == 0
        assert count_learners == 0


def test_engine_target_safety_check_on_baseline():
    """Verify SyntheticDataGenerator._verify_target_safety blocks baseline database connection."""
    mock_engine = create_engine(f"sqlite:///{PROTECTED_BASELINE_PATH.as_posix()}")
    with Session(mock_engine) as session:
        gen = SyntheticDataGenerator(session=session, config=DEVELOPMENT_CONFIG)
        with pytest.raises(RuntimeError, match="CRITICAL SAFETY VIOLATION"):
            gen._verify_target_safety()
    mock_engine.dispose()
