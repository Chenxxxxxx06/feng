"""Batch import normalized CARE SCADA files into SQLite.

The importer reads the normalized files created by prepare_care_modeling_data.py
and stores them as anonymous public dataset assets. It preserves provenance in
SCADARecord.extra and never fills unknown coordinates, turbine models, rated
power, business records, or cross-dataset links.
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
REPORTS = ROOT / "reports" / "data_processing"
DEFAULT_DB = BACKEND / "fengdiao_phm.db"
DEFAULT_MANIFEST = REPORTS / "care_normalized_event_manifest.csv"
DEFAULT_FIELD_MAPPING = REPORTS / "care_standard_field_mapping.csv"

SCADA_FIELDS = [
    "power_kw",
    "wind_speed_ms",
    "rotor_rpm",
    "gen_temperature_c",
    "gearbox_temperature_c",
    "bearing_temperature_c",
    "pitch_angle_deg",
    "nacelle_direction_deg",
    "grid_frequency_hz",
    "ambient_temp_c",
]

REQUIRED_TURBINE_COLUMNS = ["source_dataset", "source_asset_id", "asset_scope", "geo_scope"]
NULLABLE_ASSET_COLUMNS = ["model", "power_mw", "lat", "lng", "region"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_manifest(path: Path, dataset_id: str, max_files: int | None = None) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = [row for row in csv.DictReader(fh) if row.get("dataset_id") == dataset_id]
    if max_files is not None:
        rows = rows[:max_files]
    return rows


def int_cell(value: Any, default: int = 0) -> int:
    try:
        if value is None or str(value).strip() == "":
            return default
        return int(float(str(value)))
    except (TypeError, ValueError):
        return default


def parse_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null", "<na>"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def provenance_path(path_value: str | Path | None) -> str | None:
    if not path_value:
        return None
    path = Path(path_value)
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except (OSError, ValueError):
        return str(path_value)


def table_columns(con: sqlite3.Connection, table: str) -> dict[str, dict[str, Any]]:
    rows = con.execute(f"PRAGMA table_info({table})").fetchall()
    return {
        row[1]: {
            "cid": row[0],
            "name": row[1],
            "type": row[2],
            "notnull": int(row[3]),
            "default": row[4],
            "pk": int(row[5]),
        }
        for row in rows
    }


def assert_schema_ready(con: sqlite3.Connection) -> None:
    columns = table_columns(con, "turbines")
    missing = [column for column in REQUIRED_TURBINE_COLUMNS if column not in columns]
    not_nullable = [
        column
        for column in NULLABLE_ASSET_COLUMNS
        if column in columns and int(columns[column]["notnull"]) == 1
    ]
    if missing or not_nullable:
        raise RuntimeError(
            "SQLite turbines table is not ready for anonymous CARE assets. "
            f"Missing columns: {missing or 'none'}; non-null columns: {not_nullable or 'none'}. "
            "Run backend/scripts/upgrade_sqlite_for_anonymous_assets.py first."
        )


def ensure_runtime_tables(con: sqlite3.Connection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS data_import_batches (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            dataset_id VARCHAR(64) NOT NULL,
            source_type VARCHAR(32) NOT NULL,
            status VARCHAR(16) NOT NULL,
            started_at DATETIME NOT NULL,
            completed_at DATETIME,
            manifest_path TEXT,
            field_mapping_version TEXT,
            files_total INTEGER,
            files_imported INTEGER,
            rows_imported INTEGER,
            rows_skipped INTEGER,
            anonymous_assets INTEGER,
            summary JSON
        )
        """
    )
    con.execute("CREATE INDEX IF NOT EXISTS ix_data_import_batches_dataset_id ON data_import_batches (dataset_id)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_turbines_source_dataset ON turbines (source_dataset)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_turbines_source_asset_id ON turbines (source_asset_id)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_scada_records_turbine_id ON scada_records (turbine_id)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_scada_records_timestamp ON scada_records (timestamp)")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_reports(summary: dict[str, Any], file_results: list[dict[str, Any]]) -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    summary_path = REPORTS / "care_scada_import_batch_summary.json"
    files_path = REPORTS / "care_scada_import_file_results.csv"
    summary["reports"] = {
        "summary": str(summary_path),
        "file_results": str(files_path),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(files_path, file_results)


def normalized_file_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        return next(reader, [])


def dry_run(args: argparse.Namespace) -> dict[str, Any]:
    manifest_rows = read_manifest(Path(args.manifest), args.dataset_id, args.max_files)
    file_results = []
    estimated_rows = 0
    asset_keys: set[str] = set()
    ready_files = 0
    skipped_files = 0
    required_columns = {"timestamp", "source_turbine_id", "wind_farm", *SCADA_FIELDS}

    for manifest in manifest_rows:
        path = Path(manifest.get("normalized_file", ""))
        manifest_rows_count = int_cell(manifest.get("row_count"))
        row_limit = args.max_rows_per_file if args.max_rows_per_file is not None else manifest_rows_count
        expected_rows = min(manifest_rows_count, row_limit) if row_limit else manifest_rows_count
        farm = str(manifest.get("wind_farm") or "").strip()
        asset = str(manifest.get("source_asset_id") or "").strip()
        if farm and asset:
            asset_keys.add(f"{farm}:{asset}")

        status = "ready"
        reason = ""
        header: list[str] = []
        if not path.exists():
            status = "missing_file"
            reason = str(path)
            skipped_files += 1
        else:
            header = normalized_file_header(path)
            missing = sorted(required_columns - set(header))
            if {"timestamp", "source_turbine_id", "wind_farm"} - set(header):
                status = "missing_required_identity_columns"
                reason = ";".join(missing)
                skipped_files += 1
            elif not any(field in header for field in SCADA_FIELDS):
                status = "missing_scada_signal_columns"
                reason = ";".join(missing)
                skipped_files += 1
            else:
                ready_files += 1
                estimated_rows += expected_rows

        file_results.append({
            "source_file": str(path),
            "wind_farm": manifest.get("wind_farm"),
            "event_id": manifest.get("event_id"),
            "event_label": manifest.get("event_label"),
            "manifest_rows": manifest_rows_count,
            "estimated_rows": expected_rows if status == "ready" else 0,
            "status": status,
            "skip_reason": reason,
            "header_columns": ";".join(header),
        })

    summary = {
        "generated_at": now_iso(),
        "dry_run": True,
        "dataset_id": args.dataset_id,
        "db_path": str(Path(args.db_path).resolve()),
        "manifest_path": str(Path(args.manifest).resolve()),
        "field_mapping_version": args.field_mapping_version,
        "files_total": len(manifest_rows),
        "files_ready": ready_files,
        "files_skipped": skipped_files,
        "estimated_import_rows": estimated_rows,
        "estimated_anonymous_assets": len(asset_keys),
        "max_files": args.max_files,
        "max_rows_per_file": args.max_rows_per_file,
        "quality_gate": {
            "requires_timestamp": True,
            "requires_source_turbine_id": True,
            "requires_wind_farm": True,
            "skips_invalid_timestamps": True,
            "does_not_generate_missing_asset_metadata": True,
        },
    }
    write_reports(summary, file_results)
    return summary


def load_existing_assets(con: sqlite3.Connection, dataset_id: str) -> dict[str, int]:
    return {
        str(row[1]): int(row[0])
        for row in con.execute(
            "SELECT id, source_asset_id FROM turbines WHERE source_dataset = ? AND source_asset_id IS NOT NULL",
            (dataset_id,),
        ).fetchall()
    }


def asset_name(prefix: str, wind_farm: str, source_asset_id: str) -> str:
    return "-".join(part for part in [prefix, wind_farm, source_asset_id] if part)[:64]


def get_or_create_asset(
    con: sqlite3.Connection,
    cache: dict[str, int],
    dataset_id: str,
    source_asset_key: str,
    wind_farm: str,
    source_asset_id: str,
    name_prefix: str,
) -> int:
    existing = cache.get(source_asset_key)
    if existing is not None:
        return existing
    con.execute(
        """
        INSERT INTO turbines (
            name, model, power_mw, lat, lng, region, status, hi_value,
            source_dataset, source_asset_id, asset_scope, geo_scope
        )
        VALUES (?, NULL, NULL, NULL, NULL, ?, 'normal', 100.0, ?, ?, 'anonymous_public_dataset', 'anonymous_unlocated')
        """,
        (asset_name(name_prefix, wind_farm, source_asset_id), wind_farm, dataset_id, source_asset_key),
    )
    turbine_id = int(con.execute("SELECT last_insert_rowid()").fetchone()[0])
    cache[source_asset_key] = turbine_id
    return turbine_id


def replace_dataset(con: sqlite3.Connection, dataset_id: str) -> dict[str, int]:
    asset_ids = [
        int(row[0])
        for row in con.execute("SELECT id FROM turbines WHERE source_dataset = ?", (dataset_id,)).fetchall()
    ]
    if not asset_ids:
        return {"deleted_scada_records": 0, "deleted_anonymous_assets": 0}

    placeholders = ",".join("?" for _ in asset_ids)
    deleted_records = int(
        con.execute(
            f"SELECT COUNT(*) FROM scada_records WHERE turbine_id IN ({placeholders})",
            asset_ids,
        ).fetchone()[0]
    )
    con.execute(f"DELETE FROM scada_records WHERE turbine_id IN ({placeholders})", asset_ids)
    con.execute("DELETE FROM turbines WHERE source_dataset = ?", (dataset_id,))
    return {"deleted_scada_records": deleted_records, "deleted_anonymous_assets": len(asset_ids)}


def start_batch(con: sqlite3.Connection, args: argparse.Namespace, files_total: int) -> int:
    con.execute(
        """
        INSERT INTO data_import_batches (
            dataset_id, source_type, status, started_at, manifest_path,
            field_mapping_version, files_total, files_imported, rows_imported,
            rows_skipped, anonymous_assets, summary
        )
        VALUES (?, 'scada', 'running', ?, ?, ?, ?, 0, 0, 0, 0, NULL)
        """,
        (args.dataset_id, now_iso(), str(Path(args.manifest).resolve()), args.field_mapping_version, files_total),
    )
    return int(con.execute("SELECT last_insert_rowid()").fetchone()[0])


def update_batch(
    con: sqlite3.Connection,
    batch_id: int,
    status: str,
    summary: dict[str, Any],
) -> None:
    con.execute(
        """
        UPDATE data_import_batches
        SET status = ?, completed_at = ?, files_imported = ?, rows_imported = ?,
            rows_skipped = ?, anonymous_assets = ?, summary = ?
        WHERE id = ?
        """,
        (
            status,
            now_iso(),
            summary.get("files_imported", 0),
            summary.get("rows_imported", 0),
            summary.get("rows_skipped", 0),
            summary.get("anonymous_assets", 0),
            json.dumps(summary, ensure_ascii=False),
            batch_id,
        ),
    )


def update_data_source(
    con: sqlite3.Connection,
    args: argparse.Namespace,
    batch_id: int,
    summary: dict[str, Any],
    max_timestamp: str | None,
) -> None:
    payload = {
        "dataset_id": args.dataset_id,
        "dataset_role": "primary_scada_timeline",
        "manifest_path": str(Path(args.manifest).resolve()),
        "field_mapping_version": args.field_mapping_version,
        "import_batch_id": batch_id,
        "files_imported": summary.get("files_imported", 0),
        "rows_imported": summary.get("rows_imported", 0),
        "anonymous_assets": summary.get("anonymous_assets", 0),
        "replace_dataset": bool(args.replace_dataset),
        "max_files": args.max_files,
        "max_rows_per_file": args.max_rows_per_file,
        "does_not_generate_missing_asset_metadata": True,
    }
    row = con.execute(
        "SELECT id FROM data_sources WHERE source_type = 'scada' AND name = ? ORDER BY id LIMIT 1",
        (args.dataset_id,),
    ).fetchone()
    if row:
        con.execute(
            """
            UPDATE data_sources
            SET status = ?, last_connected_at = ?, last_data_at = ?, connection_params = ?
            WHERE id = ?
            """,
            (
                "connected" if summary.get("rows_imported", 0) else "disconnected",
                now_iso(),
                max_timestamp,
                json.dumps(payload, ensure_ascii=False),
                int(row[0]),
            ),
        )
    else:
        con.execute(
            """
            INSERT INTO data_sources (source_type, name, connection_params, status, last_connected_at, last_data_at)
            VALUES ('scada', ?, ?, ?, ?, ?)
            """,
            (
                args.dataset_id,
                json.dumps(payload, ensure_ascii=False),
                "connected" if summary.get("rows_imported", 0) else "disconnected",
                now_iso(),
                max_timestamp,
            ),
        )


def flush_records(con: sqlite3.Connection, records: list[tuple[Any, ...]]) -> None:
    if not records:
        return
    con.executemany(
        """
        INSERT INTO scada_records (
            turbine_id, timestamp, power_kw, wind_speed_ms, rotor_rpm,
            gen_temperature_c, gearbox_temperature_c, bearing_temperature_c,
            pitch_angle_deg, nacelle_direction_deg, grid_frequency_hz,
            ambient_temp_c, extra
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        records,
    )
    records.clear()


def build_record(
    row: dict[str, str],
    manifest: dict[str, str],
    row_number: int,
    turbine_id: int,
    source_asset_key: str,
    source_file: Path,
    args: argparse.Namespace,
    timestamp: datetime,
) -> tuple[Any, ...]:
    extra = {
        "source_dataset": args.dataset_id,
        "source_file": provenance_path(source_file),
        "raw_source_file": provenance_path(manifest.get("source_file")),
        "source_row": row_number,
        "source_row_id": row.get("source_row_id"),
        "dataset_role": "primary_scada_timeline",
        "asset_scope": "anonymous_public_dataset",
        "field_mapping_version": args.field_mapping_version,
        "source_turbine_id": row.get("source_turbine_id"),
        "source_wind_farm": row.get("wind_farm"),
        "source_asset_key": source_asset_key,
        "event_id": row.get("event_id") or manifest.get("event_id"),
        "event_label": row.get("event_label") or manifest.get("event_label"),
        "event_component_category": row.get("event_component_category") or manifest.get("event_component_category"),
        "event_start": row.get("event_start") or manifest.get("event_start"),
        "event_end": row.get("event_end") or manifest.get("event_end"),
        "train_test": row.get("train_test"),
        "status_type_id": row.get("status_type_id"),
    }
    return (
        turbine_id,
        timestamp.isoformat(),
        *(parse_float(row.get(field)) for field in SCADA_FIELDS),
        json.dumps(extra, ensure_ascii=False),
    )


def import_file(
    con: sqlite3.Connection,
    manifest: dict[str, str],
    asset_cache: dict[str, int],
    args: argparse.Namespace,
    records: list[tuple[Any, ...]],
    totals: dict[str, Any],
) -> dict[str, Any]:
    source_file = Path(manifest.get("normalized_file", ""))
    result = {
        "source_file": str(source_file),
        "wind_farm": manifest.get("wind_farm"),
        "event_id": manifest.get("event_id"),
        "event_label": manifest.get("event_label"),
        "manifest_rows": int_cell(manifest.get("row_count")),
        "rows_read": 0,
        "rows_imported": 0,
        "rows_skipped": 0,
        "anonymous_assets": 0,
        "time_start": None,
        "time_end": None,
        "status": "imported",
        "skip_reason": "",
    }
    if not source_file.exists():
        result["status"] = "missing_file"
        result["skip_reason"] = str(source_file)
        return result

    file_asset_keys: set[str] = set()
    min_ts: datetime | None = None
    max_ts: datetime | None = None
    with source_file.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row_number, row in enumerate(reader, start=2):
            if args.max_rows_per_file is not None and result["rows_read"] >= args.max_rows_per_file:
                break
            result["rows_read"] += 1
            timestamp = parse_timestamp(row.get("timestamp"))
            wind_farm = str(row.get("wind_farm") or manifest.get("wind_farm") or "").strip()
            source_asset_id = str(row.get("source_turbine_id") or manifest.get("source_asset_id") or "").strip()
            if timestamp is None:
                result["rows_skipped"] += 1
                totals["rows_skipped"] += 1
                continue
            if not wind_farm or not source_asset_id:
                result["rows_skipped"] += 1
                totals["rows_skipped"] += 1
                continue

            source_asset_key = f"{wind_farm}:{source_asset_id}"
            turbine_id = get_or_create_asset(
                con,
                asset_cache,
                args.dataset_id,
                source_asset_key,
                wind_farm,
                source_asset_id,
                args.asset_name_prefix,
            )
            file_asset_keys.add(source_asset_key)
            records.append(build_record(row, manifest, row_number, turbine_id, source_asset_key, source_file, args, timestamp))
            result["rows_imported"] += 1
            totals["rows_imported"] += 1
            min_ts = timestamp if min_ts is None or timestamp < min_ts else min_ts
            max_ts = timestamp if max_ts is None or timestamp > max_ts else max_ts
            totals["min_timestamp"] = timestamp if totals["min_timestamp"] is None or timestamp < totals["min_timestamp"] else totals["min_timestamp"]
            totals["max_timestamp"] = timestamp if totals["max_timestamp"] is None or timestamp > totals["max_timestamp"] else totals["max_timestamp"]
            if len(records) >= args.commit_rows:
                flush_records(con, records)
                con.commit()

    result["anonymous_assets"] = len(file_asset_keys)
    result["time_start"] = min_ts.isoformat() if min_ts else None
    result["time_end"] = max_ts.isoformat() if max_ts else None
    if result["rows_imported"] == 0 and result["rows_skipped"] > 0:
        result["status"] = "no_valid_rows"
    return result


def import_batch(args: argparse.Namespace) -> dict[str, Any]:
    manifest_rows = read_manifest(Path(args.manifest), args.dataset_id, args.max_files)
    if not manifest_rows:
        raise ValueError(f"No manifest rows found for dataset_id={args.dataset_id}")

    REPORTS.mkdir(parents=True, exist_ok=True)
    db_path = Path(args.db_path).resolve()
    file_results: list[dict[str, Any]] = []
    records: list[tuple[Any, ...]] = []
    started_at = now_iso()
    replacement = {"deleted_scada_records": 0, "deleted_anonymous_assets": 0}

    with sqlite3.connect(db_path) as con:
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        assert_schema_ready(con)
        ensure_runtime_tables(con)
        if args.replace_dataset:
            replacement = replace_dataset(con, args.dataset_id)
        batch_id = start_batch(con, args, len(manifest_rows))
        con.commit()

        asset_cache = load_existing_assets(con, args.dataset_id)
        totals: dict[str, Any] = {
            "rows_imported": 0,
            "rows_skipped": 0,
            "min_timestamp": None,
            "max_timestamp": None,
        }
        status = "completed"
        try:
            for manifest in manifest_rows:
                result = import_file(con, manifest, asset_cache, args, records, totals)
                file_results.append(result)
            flush_records(con, records)
            con.commit()

            db_asset_count = int(
                con.execute("SELECT COUNT(*) FROM turbines WHERE source_dataset = ?", (args.dataset_id,)).fetchone()[0]
            )
            db_record_count = int(
                con.execute(
                    """
                    SELECT COUNT(*)
                    FROM scada_records
                    WHERE turbine_id IN (SELECT id FROM turbines WHERE source_dataset = ?)
                    """,
                    (args.dataset_id,),
                ).fetchone()[0]
            )
            summary = {
                "generated_at": now_iso(),
                "dry_run": False,
                "dataset_id": args.dataset_id,
                "db_path": str(db_path),
                "manifest_path": str(Path(args.manifest).resolve()),
                "field_mapping_version": args.field_mapping_version,
                "import_batch_id": batch_id,
                "started_at": started_at,
                "files_total": len(manifest_rows),
                "files_imported": sum(1 for row in file_results if row["rows_imported"] > 0),
                "files_skipped": sum(1 for row in file_results if row["rows_imported"] == 0),
                "rows_imported": int(totals["rows_imported"]),
                "rows_skipped": int(totals["rows_skipped"]),
                "anonymous_assets": db_asset_count,
                "database_scada_records_for_dataset": db_record_count,
                "time_start": totals["min_timestamp"].isoformat() if totals["min_timestamp"] else None,
                "time_end": totals["max_timestamp"].isoformat() if totals["max_timestamp"] else None,
                "replace_dataset": bool(args.replace_dataset),
                "replacement": replacement,
                "max_files": args.max_files,
                "max_rows_per_file": args.max_rows_per_file,
                "quality_gate": {
                    "skipped_invalid_timestamps": True,
                    "skipped_rows_without_source_asset": True,
                    "coordinates_generated": False,
                    "turbine_model_generated": False,
                    "business_records_generated": False,
                },
            }
            update_data_source(
                con,
                args,
                batch_id,
                summary,
                totals["max_timestamp"].isoformat() if totals["max_timestamp"] else None,
            )
            update_batch(con, batch_id, status, summary)
            con.commit()
        except Exception as exc:
            status = "failed"
            summary = {
                "generated_at": now_iso(),
                "dry_run": False,
                "dataset_id": args.dataset_id,
                "db_path": str(db_path),
                "import_batch_id": batch_id,
                "status": status,
                "error": str(exc),
                "rows_imported": int(totals.get("rows_imported", 0)),
                "rows_skipped": int(totals.get("rows_skipped", 0)),
            }
            update_batch(con, batch_id, status, summary)
            con.commit()
            write_reports(summary, file_results)
            raise

    write_reports(summary, file_results)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Batch import normalized CARE SCADA into local SQLite")
    parser.add_argument("--db-path", default=str(DEFAULT_DB))
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--dataset-id", default="care_to_compare_v6")
    parser.add_argument("--field-mapping-version", default=str(DEFAULT_FIELD_MAPPING))
    parser.add_argument("--max-files", type=int)
    parser.add_argument("--max-rows-per-file", type=int)
    parser.add_argument("--commit-rows", type=int, default=10000)
    parser.add_argument("--asset-name-prefix", default="CARE")
    parser.add_argument("--replace-dataset", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    summary = dry_run(args) if args.dry_run else import_batch(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
