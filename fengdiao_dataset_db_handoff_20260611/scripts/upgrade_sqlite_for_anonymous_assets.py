"""Upgrade a local SQLite database for anonymous public dataset assets.

The application model now allows turbines that come from anonymous public
datasets: model, rated power, coordinates, and real region can stay null while
source_dataset/source_asset_id keep provenance. This script upgrades an older
local SQLite demo database without fabricating missing asset metadata.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
REPORTS = ROOT / "reports" / "data_processing"
DEFAULT_DB = BACKEND / "fengdiao_phm.db"

TARGET_COLUMNS = [
    "id",
    "name",
    "model",
    "power_mw",
    "lat",
    "lng",
    "region",
    "status",
    "hi_value",
    "last_maintenance",
    "commissioned_at",
    "source_dataset",
    "source_asset_id",
    "asset_scope",
    "geo_scope",
]
SOURCE_COLUMNS = ["source_dataset", "source_asset_id", "asset_scope", "geo_scope"]
NULLABLE_ASSET_COLUMNS = ["model", "power_mw", "lat", "lng", "region"]


CREATE_TURBINES_SQL = """
CREATE TABLE turbines_new (
    id INTEGER NOT NULL PRIMARY KEY,
    name VARCHAR(64) NOT NULL,
    model VARCHAR(64),
    power_mw FLOAT,
    lat FLOAT,
    lng FLOAT,
    region VARCHAR(32),
    status VARCHAR(16),
    hi_value FLOAT,
    last_maintenance DATETIME,
    commissioned_at DATETIME,
    source_dataset VARCHAR(64),
    source_asset_id VARCHAR(128),
    asset_scope VARCHAR(32),
    geo_scope VARCHAR(32),
    CONSTRAINT uq_turbine_source_asset UNIQUE (source_dataset, source_asset_id)
)
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def table_info(con: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    rows = con.execute(f"PRAGMA table_info({table})").fetchall()
    return [
        {
            "cid": row[0],
            "name": row[1],
            "type": row[2],
            "notnull": int(row[3]),
            "default": row[4],
            "pk": int(row[5]),
        }
        for row in rows
    ]


def compatibility(columns: list[dict[str, Any]]) -> dict[str, Any]:
    by_name = {column["name"]: column for column in columns}
    missing = [column for column in SOURCE_COLUMNS if column not in by_name]
    not_nullable = [
        column
        for column in NULLABLE_ASSET_COLUMNS
        if column in by_name and int(by_name[column]["notnull"]) == 1
    ]
    return {
        "compatible": not missing and not not_nullable,
        "missing_columns": missing,
        "non_nullable_columns": not_nullable,
    }


def create_indexes(con: sqlite3.Connection) -> None:
    con.execute("CREATE INDEX IF NOT EXISTS ix_turbines_id ON turbines (id)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_turbines_name ON turbines (name)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_turbines_source_dataset ON turbines (source_dataset)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_turbines_source_asset_id ON turbines (source_asset_id)")


def backup_database(db_path: Path) -> Path:
    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_path = backup_dir / f"{db_path.stem}.before_anonymous_assets.{stamp}{db_path.suffix}"
    shutil.copy2(db_path, backup_path)
    return backup_path


def rebuild_turbines_table(con: sqlite3.Connection, before_columns: list[dict[str, Any]]) -> None:
    existing = {column["name"] for column in before_columns}
    target_exprs = []
    for column in TARGET_COLUMNS:
        if column in existing:
            target_exprs.append(column)
        elif column == "asset_scope":
            target_exprs.append("'field_asset'")
        elif column == "geo_scope":
            target_exprs.append("'known'")
        else:
            target_exprs.append("NULL")

    con.execute("PRAGMA foreign_keys=OFF")
    con.execute("BEGIN")
    try:
        con.execute(CREATE_TURBINES_SQL)
        if before_columns:
            con.execute(
                f"INSERT INTO turbines_new ({', '.join(TARGET_COLUMNS)}) "
                f"SELECT {', '.join(target_exprs)} FROM turbines"
            )
            con.execute("DROP TABLE turbines")
        con.execute("ALTER TABLE turbines_new RENAME TO turbines")
        create_indexes(con)
        foreign_key_issues = con.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_issues:
            raise RuntimeError(f"foreign_key_check failed: {foreign_key_issues}")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.execute("PRAGMA foreign_keys=ON")


def upgrade_database(db_path: Path) -> dict[str, Any]:
    db_path = db_path.resolve()
    if not db_path.exists():
        raise FileNotFoundError(db_path)

    REPORTS.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as con:
        before = table_info(con, "turbines")
        before_check = compatibility(before)
        if before_check["compatible"]:
            create_indexes(con)
            con.commit()
            after = table_info(con, "turbines")
            report = {
                "generated_at": now_iso(),
                "db_path": str(db_path),
                "status": "already_compatible",
                "backup_path": None,
                "before": before_check,
                "after": compatibility(after),
                "columns_after": after,
            }
        else:
            backup_path = backup_database(db_path)
            rebuild_turbines_table(con, before)
            after = table_info(con, "turbines")
            report = {
                "generated_at": now_iso(),
                "db_path": str(db_path),
                "status": "upgraded",
                "backup_path": str(backup_path),
                "before": before_check,
                "after": compatibility(after),
                "columns_before": before,
                "columns_after": after,
            }

    report_path = REPORTS / "sqlite_schema_upgrade_anonymous_assets.json"
    report["report_path"] = str(report_path)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Upgrade local SQLite schema for anonymous dataset assets")
    parser.add_argument("--db-path", default=str(DEFAULT_DB))
    return parser


def main() -> None:
    args = build_parser().parse_args()
    report = upgrade_database(Path(args.db_path))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
