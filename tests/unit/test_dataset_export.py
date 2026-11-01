"""Unit tests for export_dataset.py.

Verifies read-only extraction, CSV and JSON serialization, manifest generation,
empty table handling, and column preservation.
"""

import csv
import json
from pathlib import Path
import sqlite3
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.db.database import Base
from src.models.entities import Skill, Learner, Course
from export_dataset import export_dataset, serialize_value_csv, serialize_value_json


@pytest.fixture
def sample_source_db(tmp_path: Path):
    """Create a populated temporary SQLite database for export testing."""
    db_file = tmp_path / "source_export.db"
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    # Create skills table
    cursor.execute("""
        CREATE TABLE skills (
            skill_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            domain TEXT NOT NULL,
            difficulty_level REAL NOT NULL,
            description TEXT,
            is_active BOOLEAN NOT NULL,
            created_at TIMESTAMP NOT NULL,
            updated_at TIMESTAMP NOT NULL
        );
    """)

    # Create empty table
    cursor.execute("""
        CREATE TABLE data_issues (
            issue_id TEXT PRIMARY KEY,
            anomaly_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            description TEXT
        );
    """)

    cursor.execute("""
        INSERT INTO skills VALUES (
            'SKL-000001',
            'Python Programming',
            'Web Development',
            0.5500,
            'Core Python language concepts',
            1,
            '2026-01-01 00:00:00',
            '2026-01-01 00:00:00'
        );
    """)
    cursor.execute("""
        INSERT INTO skills VALUES (
            'SKL-000002',
            'Relational Databases',
            'Data Science',
            0.7000,
            NULL,
            0,
            '2026-02-01 10:30:00',
            '2026-02-01 10:30:00'
        );
    """)

    conn.commit()
    conn.close()
    return db_file


def test_export_dataset_manifest_and_files(sample_source_db: Path, tmp_path: Path):
    """Verify export_dataset creates manifest.json, CSVs, and JSONs with correct schemas."""
    output_dir = tmp_path / "export_output"
    manifest = export_dataset(sample_source_db, output_dir)

    assert manifest["source_database"] == "source_export.db"
    assert manifest["total_tables"] == 2
    assert manifest["total_rows"] == 2
    assert "skills" in manifest["tables"]
    assert "data_issues" in manifest["tables"]

    manifest_file = output_dir / "manifest.json"
    assert manifest_file.exists()
    loaded_manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert loaded_manifest["total_tables"] == 2

    # Check skills.csv
    skills_csv = output_dir / "skills.csv"
    assert skills_csv.exists()
    with open(skills_csv, newline="", encoding="utf-8") as f:
        reader = list(csv.reader(f))
        headers = reader[0]
        assert "skill_id" in headers
        assert "name" in headers
        assert "difficulty_level" in headers
        assert len(reader) == 3  # Header + 2 data rows
        # Check null serialization
        row2 = reader[2]
        desc_idx = headers.index("description")
        assert row2[desc_idx] == ""  # NULL should be empty string in CSV

    # Check skills.json
    skills_json = output_dir / "skills.json"
    assert skills_json.exists()
    records = json.loads(skills_json.read_text(encoding="utf-8"))
    assert len(records) == 2
    assert records[0]["skill_id"] == "SKL-000001"
    assert records[0]["is_active"] is True
    assert records[1]["description"] is None  # NULL should be null in JSON
    assert records[1]["is_active"] is False

    # Check empty table handling (data_issues)
    issues_csv = output_dir / "data_issues.csv"
    assert issues_csv.exists()
    with open(issues_csv, newline="", encoding="utf-8") as f:
        reader = list(csv.reader(f))
        assert len(reader) == 1  # Only header
        assert reader[0] == ["issue_id", "anomaly_type", "severity", "description"]

    issues_json = output_dir / "data_issues.json"
    assert issues_json.exists()
    issues_records = json.loads(issues_json.read_text(encoding="utf-8"))
    assert issues_records == []


def test_export_dataset_nonexistent_database(tmp_path: Path):
    """Verify FileNotFoundError is raised when database does not exist."""
    missing_db = tmp_path / "nonexistent.db"
    with pytest.raises(FileNotFoundError):
        export_dataset(missing_db, tmp_path / "out")


def test_export_table_filter(sample_source_db: Path, tmp_path: Path):
    """Verify specific table filtering via tables argument."""
    output_dir = tmp_path / "filter_output"
    manifest = export_dataset(sample_source_db, output_dir, tables=["skills"])

    assert manifest["total_tables"] == 1
    assert "skills" in manifest["tables"]
    assert "data_issues" not in manifest["tables"]
    assert (output_dir / "skills.csv").exists()
    assert not (output_dir / "data_issues.csv").exists()
