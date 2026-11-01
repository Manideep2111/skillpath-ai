"""Dataset export utility for SkillPath AI relational databases.

Exports SQLite tables to CSV and JSON formats with an export manifest.
Enforces read-only database connections (PRAGMA query_only = ON) and
preserves column names and deterministic serialization.
"""

import argparse
import csv
from datetime import datetime, timezone
from decimal import Decimal
import json
import logging
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("export_dataset")

# Standard parent-before-child table order
CANONICAL_TABLE_ORDER = [
    "skills",
    "skill_prerequisites",
    "courses",
    "content_items",
    "content_skills",
    "learners",
    "learning_paths",
    "learning_path_items",
    "attempts",
    "assessment_results",
    "mastery_snapshots",
    "recommendations",
    "recommendation_outcomes",
    "audit_events",
    "data_issues",
]


def serialize_value_csv(val: Any) -> str:
    """Format Python values consistently for CSV export."""
    if val is None:
        return ""
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, datetime):
        return val.isoformat()
    if isinstance(val, (Decimal, float)):
        return f"{float(val):.4f}"
    return str(val)


def serialize_value_json(val: Any) -> Any:
    """Format Python values consistently for JSON serialization."""
    if val is None:
        return None
    if isinstance(val, bool):
        return bool(val)
    if isinstance(val, datetime):
        return val.isoformat()
    if isinstance(val, Decimal):
        return float(val)
    if isinstance(val, float):
        return round(val, 6)
    return val


def get_sqlite_tables(conn: sqlite3.Connection) -> List[str]:
    """Retrieve list of user tables in predictable canonical order."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;"
    )
    existing = [row[0] for row in cursor.fetchall()]
    cursor.close()

    # Sort existing tables according to canonical order, followed by any additional tables alphabetically
    ordered = [t for t in CANONICAL_TABLE_ORDER if t in existing]
    remaining = sorted([t for t in existing if t not in ordered])
    return ordered + remaining


def export_table(
    conn: sqlite3.Connection,
    table_name: str,
    output_dir: Path,
) -> Dict[str, Any]:
    """Export a single SQLite table to CSV and JSON files safely.

    Args:
        conn: Read-only SQLite connection.
        table_name: Name of table to export.
        output_dir: Directory where CSV and JSON files will be written.

    Returns:
        Dict[str, Any]: Metadata dictionary for the export manifest.
    """
    cursor = conn.cursor()

    # Query columns and metadata
    cursor.execute(f"PRAGMA table_info({table_name});")
    col_info = cursor.fetchall()
    columns = [col[1] for col in col_info]
    col_types = [col[2].upper() if col[2] else "" for col in col_info]

    cursor.execute(f"SELECT * FROM {table_name};")
    raw_rows = cursor.fetchall()
    cursor.close()

    # Normalize SQLite types (e.g. integer 1/0 for BOOLEAN columns)
    rows = []
    for r in raw_rows:
        row_vals = []
        for i, val in enumerate(r):
            if val is not None and ("BOOL" in col_types[i]):
                row_vals.append(bool(val))
            else:
                row_vals.append(val)
        rows.append(row_vals)

    row_count = len(rows)

    # 1. Export CSV
    csv_filename = f"{table_name}.csv"
    csv_path = output_dir / csv_filename
    with open(csv_path, "w", newline="", encoding="utf-8") as f_csv:
        writer = csv.writer(f_csv)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([serialize_value_csv(v) for v in row])

    # 2. Export JSON
    json_filename = f"{table_name}.json"
    json_path = output_dir / json_filename
    json_records = []
    for row in rows:
        record = {
            col: serialize_value_json(val)
            for col, val in zip(columns, row)
        }
        json_records.append(record)

    with open(json_path, "w", encoding="utf-8") as f_json:
        json.dump(json_records, f_json, indent=2, ensure_ascii=False)

    return {
        "table_name": table_name,
        "row_count": row_count,
        "columns": columns,
        "csv_file": csv_filename,
        "json_file": json_filename,
        "csv_size_bytes": csv_path.stat().st_size,
        "json_size_bytes": json_path.stat().st_size,
    }


def export_dataset(
    db_path: Path,
    output_dir: Path,
    tables: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Export all or selected tables from a source SQLite database.

    Enforces strict read-only operation and produces manifest.json.

    Args:
        db_path: Path to source SQLite database.
        output_dir: Path to directory where export files are written.
        tables: Optional subset of tables to export (defaults to all tables).

    Returns:
        Dict[str, Any]: Full manifest payload.
    """
    resolved_db = Path(db_path).resolve()
    if not resolved_db.exists():
        raise FileNotFoundError(f"Source database file not found at '{resolved_db}'.")

    resolved_out = Path(output_dir).resolve()
    resolved_out.mkdir(parents=True, exist_ok=True)

    # Open SQLite in URI read-only mode with query_only pragma
    uri = f"file:{resolved_db.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.execute("PRAGMA query_only = ON;")

    try:
        available_tables = get_sqlite_tables(conn)
        target_tables = [t for t in tables if t in available_tables] if tables else available_tables

        if not target_tables:
            logger.warning("No matching tables found to export from '%s'.", resolved_db)

        manifest_tables: Dict[str, Any] = {}
        total_rows = 0

        for tbl in target_tables:
            logger.info("Exporting table '%s'...", tbl)
            meta = export_table(conn, tbl, resolved_out)
            manifest_tables[tbl] = meta
            total_rows += meta["row_count"]

        now_utc = datetime.now(timezone.utc).isoformat()
        manifest = {
            "source_database": resolved_db.name,
            "source_path": str(resolved_db),
            "exported_at": now_utc,
            "total_tables": len(manifest_tables),
            "total_rows": total_rows,
            "formats": ["csv", "json"],
            "tables": manifest_tables,
        }

        manifest_path = resolved_out / "manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f_man:
            json.dump(manifest, f_man, indent=2)

        logger.info(
            "Export complete: %d tables, %d rows exported to '%s'.",
            len(manifest_tables),
            total_rows,
            resolved_out,
        )
        return manifest
    finally:
        conn.close()


def main() -> int:
    """CLI argument parsing and dataset export execution."""
    parser = argparse.ArgumentParser(
        description="SkillPath AI — Read-Only Relational Dataset Exporter (CSV & JSON)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        required=True,
        help="Path to source SQLite database file",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/exports"),
        help="Output directory for exported CSV, JSON, and manifest files",
    )
    parser.add_argument(
        "--tables",
        nargs="+",
        help="Optional list of specific table names to export",
    )

    args = parser.parse_args()

    try:
        manifest = export_dataset(
            db_path=args.db_path,
            output_dir=args.output_dir,
            tables=args.tables,
        )
        print("=" * 70)
        print(f"Export Manifest Summary ({manifest['source_database']}):")
        print(f"  Export Directory: {args.output_dir.resolve()}")
        print(f"  Total Tables    : {manifest['total_tables']}")
        print(f"  Total Rows      : {manifest['total_rows']}")
        print(f"  Manifest File   : {args.output_dir.resolve() / 'manifest.json'}")
        print("=" * 70)
        return 0
    except Exception as exc:
        sys.stderr.write(f"\n[EXPORT ERROR] Export failed: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
