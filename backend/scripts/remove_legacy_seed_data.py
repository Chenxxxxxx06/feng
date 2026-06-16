"""Remove deprecated seed-demo turbines from the local SQLite database.

The active monitoring dataset is CARE (`source_dataset='care_to_compare_v6'`).
Older Shaanxi demo assets were inserted by seed_data.py with source_dataset
left NULL. They should not appear in the production-like monitoring views.
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "backend" / "fengdiao_phm.db"


DIRECT_TURBINE_TABLES = [
    "blade_images",
    "rul_predictions",
    "scada_records",
    "vibration_data",
    "work_orders",
]


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _count(con: sqlite3.Connection, sql: str) -> int:
    return int(con.execute(sql).fetchone()[0])


def summarize(con: sqlite3.Connection) -> dict[str, int]:
    summary = {
        "turbines": _count(con, "SELECT COUNT(*) FROM turbines WHERE source_dataset IS NULL"),
    }
    for table in DIRECT_TURBINE_TABLES:
        if _table_exists(con, table):
            summary[table] = _count(
                con,
                f"""
                SELECT COUNT(*)
                FROM {table}
                WHERE turbine_id IN (
                    SELECT id FROM turbines WHERE source_dataset IS NULL
                )
                """,
            )
    if _table_exists(con, "fault_signals") and _table_exists(con, "faults"):
        summary["fault_signals"] = _count(
            con,
            """
            SELECT COUNT(*)
            FROM fault_signals
            WHERE fault_id IN (
                SELECT id
                FROM faults
                WHERE turbine_id IN (
                    SELECT id FROM turbines WHERE source_dataset IS NULL
                )
            )
            """,
        )
    if _table_exists(con, "faults"):
        summary["faults"] = _count(
            con,
            """
            SELECT COUNT(*)
            FROM faults
            WHERE turbine_id IN (
                SELECT id FROM turbines WHERE source_dataset IS NULL
            )
            """,
        )
    return summary


def remove_legacy_seed_data(db_path: Path, dry_run: bool = False) -> dict[str, int]:
    con = sqlite3.connect(db_path)
    try:
        con.execute("PRAGMA foreign_keys = OFF")
        before = summarize(con)
        if dry_run or before["turbines"] == 0:
            return before

        with con:
            if _table_exists(con, "fault_signals") and _table_exists(con, "faults"):
                con.execute(
                    """
                    DELETE FROM fault_signals
                    WHERE fault_id IN (
                        SELECT id
                        FROM faults
                        WHERE turbine_id IN (
                            SELECT id FROM turbines WHERE source_dataset IS NULL
                        )
                    )
                    """,
                )
            if _table_exists(con, "faults"):
                con.execute(
                    """
                    DELETE FROM faults
                    WHERE turbine_id IN (
                        SELECT id FROM turbines WHERE source_dataset IS NULL
                    )
                    """,
                )
            for table in DIRECT_TURBINE_TABLES:
                if _table_exists(con, table):
                    con.execute(
                        f"""
                        DELETE FROM {table}
                        WHERE turbine_id IN (
                            SELECT id FROM turbines WHERE source_dataset IS NULL
                        )
                        """,
                    )
            con.execute("DELETE FROM turbines WHERE source_dataset IS NULL")
        return before
    finally:
        con.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Remove deprecated seed demo assets")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    summary = remove_legacy_seed_data(args.db, args.dry_run)
    action = "Would remove" if args.dry_run else "Removed"
    print(f"{action} legacy seed data from {args.db}:")
    for key, value in sorted(summary.items()):
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
