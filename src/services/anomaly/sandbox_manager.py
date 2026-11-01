"""Sandbox manager for SkillPath AI.

Safely clones the clean baseline database to an isolated sandbox file using
SQLite's Online Backup API. Enforces strict path safety checks and guards
against accidental modification or overwriting of skillpath.db.
"""

from pathlib import Path
import os
import sqlite3

BASELINE_DB_PATH = Path("D:/SkillPathAI/skillpath.db").resolve()
DEFAULT_SANDBOX_PATH = Path("D:/SkillPathAI/data/anomalies/skillpath_anomaly_sandbox.db").resolve()


class SandboxPathSecurityError(RuntimeError):
    """Raised when a path check fails or a dangerous destination is specified."""
    pass


class SandboxOverwriteError(FileExistsError):
    """Raised when destination sandbox already exists and force_recreate is False."""
    pass


class SandboxManager:
    """Manages the creation and lifecycle of isolated anomaly sandbox databases."""

    @staticmethod
    def assert_safe_destination(destination_path: Path | str) -> Path:
        """Verify that destination is non-empty and does NOT resolve to the baseline database."""
        dest = Path(destination_path).resolve()
        baseline = BASELINE_DB_PATH.resolve()

        if os.path.normcase(str(dest)) == os.path.normcase(str(baseline)):
            raise SandboxPathSecurityError(
                f"CRITICAL SAFETY VIOLATION: Refusing to use baseline database '{baseline}' as a sandbox target!"
            )
        return dest

    @classmethod
    def clone_baseline(
        cls,
        source_path: Path | str = BASELINE_DB_PATH,
        destination_path: Path | str = DEFAULT_SANDBOX_PATH,
        force_recreate: bool = False,
    ) -> Path:
        """Clone clean baseline database to destination sandbox using SQLite Online Backup API.

        Args:
            source_path: Absolute path to the source database (defaults to skillpath.db).
            destination_path: Absolute path to target sandbox.
            force_recreate: If True, allows replacing an existing sandbox. If False, raises SandboxOverwriteError.

        Returns:
            Path: Absolute resolved path to the created sandbox database.

        Raises:
            SandboxPathSecurityError: If destination resolves to baseline database.
            SandboxOverwriteError: If destination exists and force_recreate is False.
            FileNotFoundError: If source does not exist.
        """
        src = Path(source_path).resolve()
        dest = cls.assert_safe_destination(destination_path)

        if not src.exists():
            raise FileNotFoundError(f"Source database '{src}' does not exist.")

        if dest.exists() and not force_recreate:
            raise SandboxOverwriteError(
                f"Sandbox database already exists at '{dest}'. "
                "Explicit authorization required: pass force_recreate=True to replace it."
            )

        # Ensure parent directory exists
        dest.parent.mkdir(parents=True, exist_ok=True)

        # If dest exists and force_recreate is True, remove it cleanly before backup
        if dest.exists() and force_recreate:
            dest.unlink()

        # Connect to source in read-only mode with PRAGMA query_only = ON
        src_uri = f"file:{src.as_posix()}?mode=ro"
        src_conn = sqlite3.connect(src_uri, uri=True)
        try:
            src_conn.execute("PRAGMA query_only = ON;")
            dest_conn = sqlite3.connect(dest.as_posix())
            try:
                src_conn.backup(dest_conn)
            finally:
                dest_conn.close()
        finally:
            src_conn.close()

        # Validate that the destination contains tables
        verify_conn = sqlite3.connect(dest.as_posix())
        try:
            cursor = verify_conn.cursor()
            cursor.execute("SELECT count(*) FROM sqlite_master WHERE type='table';")
            table_count = cursor.fetchone()[0]
            if table_count < 15:
                raise RuntimeError(
                    f"Sandbox clone verification failed: Expected at least 15 tables, found {table_count}."
                )
        finally:
            verify_conn.close()

        return dest
