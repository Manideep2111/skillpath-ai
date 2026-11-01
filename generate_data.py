"""CLI entry point for deterministic synthetic data generation across configurable profiles.

Supports profiles:
- development: 100 learners, 50 skills, 100 content items, 2,000 attempts.
- integration: 500 learners, 200 skills, 500 content items, 20,000 attempts.
- full: 10,000 learners, 500 skills, 2,000 content items, 500,000 attempts.

Strict safety constraints:
- Refuses to write to baseline database 'skillpath.db' under ANY flag.
- Never defaults to overwriting 'skillpath.db'.
- Refuses to overwrite an existing database file unless --overwrite is explicitly passed.
- Enforces parent-before-child ordering and validates foreign keys and entity counts post-generation.
"""

import argparse
import os
from pathlib import Path
import sqlite3
import sys
import traceback
from typing import Dict, Optional

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from src.db.database import Base
import src.models  # Registers all 15 ORM entities with Base.metadata
from src.services.generator.synthetic_engine import (
    PROFILES,
    DEVELOPMENT_CONFIG,
    INTEGRATION_CONFIG,
    FULL_CONFIG,
    GeneratorConfig,
    SyntheticDataGenerator,
)

PROJECT_ROOT = Path(__file__).resolve().parent
PROTECTED_BASELINE_PATH = (PROJECT_ROOT / "skillpath.db").resolve()
DEFAULT_OUTPUT_DIR = (PROJECT_ROOT / "data" / "generated").resolve()


def apply_sqlite_pragmas(engine) -> None:
    """Attach connection listeners for foreign keys, WAL mode, and normal sync."""
    @event.listens_for(engine, "connect")
    def set_pragmas(dbapi_connection, connection_record):
        if isinstance(dbapi_connection, sqlite3.Connection):
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys = ON;")
                cursor.execute("PRAGMA journal_mode = WAL;")
                cursor.execute("PRAGMA synchronous = NORMAL;")
            finally:
                cursor.close()


def validate_target_safety(output_path: Path, overwrite: bool) -> None:
    """Enforce strict isolation rules preventing modification of baseline database.

    Args:
        output_path: Destination path for generated SQLite database.
        overwrite: Whether caller explicitly requested overwriting an existing file.

    Raises:
        ValueError: If output points to protected baseline or already exists without --overwrite.
    """
    resolved = output_path.resolve()

    # 1. Hard baseline protection check (case-normalized for Windows safety)
    if os.path.normcase(str(resolved)) == os.path.normcase(str(PROTECTED_BASELINE_PATH)):
        raise ValueError(
            "CRITICAL SAFETY VIOLATION: Refusing to generate synthetic data into "
            f"protected baseline database '{PROTECTED_BASELINE_PATH}'. "
            "The baseline database must never be overwritten, regenerated, or truncated. "
            "Specify a distinct output path (e.g. data/generated/skillpath_dev.db)."
        )

    # 2. Existing file overwrite protection
    if resolved.exists():
        if not overwrite:
            raise ValueError(
                f"Target database file '{resolved}' already exists. "
                "Refusing to overwrite without explicit confirmation. Pass --overwrite to proceed."
            )
        # Safely remove existing SQLite file and its journaling sidecars
        try:
            for suffix in ["", "-wal", "-shm"]:
                sidecar = Path(str(resolved) + suffix)
                if sidecar.exists():
                    sidecar.unlink()
        except OSError as exc:
            raise RuntimeError(f"Failed to remove existing database file '{resolved}': {exc}")


def generate_database(
    profile_name: str,
    output_path: Path,
    overwrite: bool = False,
    batch_size: int = 5000,
) -> Dict[str, int]:
    """Materialize schema and generate synthetic data into target SQLite database.

    Args:
        profile_name: Name of profile ('development', 'integration', 'full').
        output_path: Destination SQLite file path.
        overwrite: Whether to overwrite existing file at output_path.
        batch_size: Bounded batch size for attempt generation.

    Returns:
        Dict[str, int]: Summary mapping entity names to row counts.
    """
    profile_key = profile_name.strip().lower()
    if profile_key not in PROFILES:
        raise ValueError(
            f"Unknown profile '{profile_name}'. Must be one of: {list(PROFILES.keys())}"
        )
    config = PROFILES[profile_key]

    validate_target_safety(output_path, overwrite)

    # Ensure target directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Target Database : {output_path.resolve()}")
    print(f"Selected Profile: {config.profile_name}")
    print(f"Target Learners : {config.num_learners}")
    print(f"Target Skills   : {config.num_skills}")
    print(f"Target Courses  : {config.num_courses}")
    print(f"Target Content  : {config.num_content_items}")
    print(f"Target Attempts : {config.num_attempts}")
    print(f"Batch Size      : {batch_size}")
    print("-" * 70)

    db_url = f"sqlite:///{output_path.resolve().as_posix()}"
    target_engine = create_engine(db_url, connect_args={"check_same_thread": False})
    apply_sqlite_pragmas(target_engine)

    # 1. Schema Materialization
    print("Creating ORM tables in target database...")
    Base.metadata.create_all(bind=target_engine)

    # 2. Transactional Generation
    SessionMaker = sessionmaker(bind=target_engine, autocommit=False, autoflush=False)
    print("Executing synthetic generation pipeline...")
    with SessionMaker() as session:
        generator = SyntheticDataGenerator(session=session, config=config, batch_size=batch_size)
        summary = generator.generate()

    # 3. Post-Generation Integrity Validation
    print("Running post-generation referential integrity and count validations...")
    with SessionMaker() as session:
        # a) Foreign key check
        fk_violations = session.execute(text("PRAGMA foreign_key_check;")).fetchall()
        if fk_violations:
            raise RuntimeError(
                f"Integrity check failed: {len(fk_violations)} foreign key violations detected!"
            )
        print("  [PASS] Zero foreign key violations.")

        # b) Count verification
        assert summary["learners"] == config.num_learners, "Learner count mismatch"
        assert summary["skills"] == config.num_skills, "Skill count mismatch"
        assert summary["courses"] == config.num_courses, "Course count mismatch"
        assert summary["content_items"] == config.num_content_items, "Content count mismatch"
        assert summary["attempts"] == config.num_attempts, "Attempt count mismatch"
        print("  [PASS] All entity counts match profile configuration.")

        # c) Compute logical dataset signature
        signature = generator.compute_dataset_signature()
        print(f"  [INFO] Logical Dataset SHA-256: {signature}")

    target_engine.dispose()
    return summary


def main() -> int:
    """CLI argument parsing and generation execution."""
    parser = argparse.ArgumentParser(
        description="SkillPath AI — Deterministic Synthetic Data Generator",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--profile",
        choices=["development", "integration", "full"],
        default="development",
        help="Synthetic generation scale profile",
    )
    parser.add_argument(
        "--output-db",
        type=Path,
        default=None,
        help="Destination SQLite database path (defaults to data/generated/skillpath_{profile}.db)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        default=False,
        help="Allow overwriting destination database file if it exists (never permits baseline)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=5000,
        help="Batch size for memory-bounded attempt inserts",
    )

    args = parser.parse_args()

    # Default output path if not provided
    if args.output_db is None:
        out_path = DEFAULT_OUTPUT_DIR / f"skillpath_{args.profile}.db"
    else:
        out_path = args.output_db

    print("=" * 70)
    print("SkillPath AI — Synthetic Data Generator")
    print("=" * 70)

    try:
        summary = generate_database(
            profile_name=args.profile,
            output_path=out_path,
            overwrite=args.overwrite,
            batch_size=args.batch_size,
        )
        print("-" * 70)
        print("SUCCESS: Dataset generated successfully!")
        print("Summary of Generated Entities:")
        for entity_name, count in summary.items():
            print(f"  - {entity_name:<24}: {count:>6} rows")
        print("=" * 70)
        return 0
    except ValueError as val_err:
        sys.stderr.write(f"\n[VALIDATION STOP] {val_err}\n")
        return 1
    except Exception as exc:
        sys.stderr.write(f"\n[GENERATION ERROR] Generation failed: {exc}\n")
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
