"""Tests for CARE normalized batch import utilities."""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3

from scripts.import_care_normalized_batch import SCADA_FIELDS, import_batch
from scripts.upgrade_sqlite_for_anonymous_assets import upgrade_database


def _create_new_schema_db(path):
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE turbines (
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
        );
        CREATE TABLE scada_records (
            id INTEGER NOT NULL PRIMARY KEY,
            turbine_id INTEGER NOT NULL,
            timestamp DATETIME NOT NULL,
            power_kw FLOAT,
            wind_speed_ms FLOAT,
            rotor_rpm FLOAT,
            gen_temperature_c FLOAT,
            gearbox_temperature_c FLOAT,
            bearing_temperature_c FLOAT,
            pitch_angle_deg FLOAT,
            nacelle_direction_deg FLOAT,
            grid_frequency_hz FLOAT,
            ambient_temp_c FLOAT,
            extra JSON,
            FOREIGN KEY(turbine_id) REFERENCES turbines (id)
        );
        CREATE TABLE data_sources (
            id INTEGER NOT NULL PRIMARY KEY,
            source_type VARCHAR(32) NOT NULL,
            name VARCHAR(64) NOT NULL,
            connection_params JSON,
            status VARCHAR(16),
            last_connected_at DATETIME,
            last_data_at DATETIME
        );
        """
    )
    con.commit()
    con.close()


def test_upgrade_old_sqlite_schema_preserves_existing_rows(tmp_path, monkeypatch):
    db_path = tmp_path / "old.db"
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(
        """
        CREATE TABLE turbines (
            id INTEGER NOT NULL PRIMARY KEY,
            name VARCHAR(64) NOT NULL,
            model VARCHAR(64) NOT NULL,
            power_mw FLOAT NOT NULL,
            lat FLOAT NOT NULL,
            lng FLOAT NOT NULL,
            region VARCHAR(32) NOT NULL,
            status VARCHAR(16),
            hi_value FLOAT,
            last_maintenance DATETIME,
            commissioned_at DATETIME
        );
        CREATE TABLE scada_records (
            id INTEGER NOT NULL PRIMARY KEY,
            turbine_id INTEGER NOT NULL,
            timestamp DATETIME NOT NULL,
            extra JSON,
            FOREIGN KEY(turbine_id) REFERENCES turbines (id)
        );
        INSERT INTO turbines (id, name, model, power_mw, lat, lng, region, status, hi_value)
        VALUES (1, 'T1', 'Model-A', 3.0, 35.0, 109.0, 'Region-A', 'normal', 90.0);
        INSERT INTO scada_records (id, turbine_id, timestamp, extra)
        VALUES (1, 1, '2024-01-01T00:00:00+00:00', '{}');
        """
    )
    con.commit()
    con.close()
    monkeypatch.setattr("scripts.upgrade_sqlite_for_anonymous_assets.REPORTS", tmp_path / "reports")

    report = upgrade_database(db_path)

    assert report["status"] == "upgraded"
    con = sqlite3.connect(db_path)
    columns = {row[1]: row for row in con.execute("PRAGMA table_info(turbines)").fetchall()}
    assert columns["source_dataset"][3] == 0
    assert columns["lat"][3] == 0
    row = con.execute(
        "SELECT id, name, source_dataset, source_asset_id, asset_scope, geo_scope FROM turbines"
    ).fetchone()
    assert row == (1, "T1", None, None, "field_asset", "known")
    assert con.execute("PRAGMA foreign_key_check").fetchall() == []
    con.close()


def test_care_batch_import_creates_anonymous_assets_and_reports(tmp_path, monkeypatch):
    db_path = tmp_path / "care.db"
    _create_new_schema_db(db_path)
    data_dir = tmp_path / "normalized"
    data_dir.mkdir()
    csv_path = data_dir / "event_0.csv"
    headers = [
        "timestamp",
        "source_turbine_id",
        "event_id",
        "wind_farm",
        "event_label",
        "event_component_category",
        "event_start",
        "event_end",
        "train_test",
        "status_type_id",
        "source_row_id",
        *SCADA_FIELDS,
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=headers)
        writer.writeheader()
        writer.writerow({
            "timestamp": "2024-01-01T00:00:00",
            "source_turbine_id": "0",
            "event_id": "0",
            "wind_farm": "Wind Farm A",
            "event_label": "anomaly",
            "event_component_category": "gearbox",
            "event_start": "2024-01-01 00:00:00",
            "event_end": "2024-01-03 00:00:00",
            "train_test": "train",
            "status_type_id": "0",
            "source_row_id": "10",
            "power_kw": "1200",
            "wind_speed_ms": "7.2",
        })
        writer.writerow({
            "timestamp": "bad-time",
            "source_turbine_id": "0",
            "event_id": "0",
            "wind_farm": "Wind Farm A",
            "event_label": "anomaly",
        })

    manifest_path = tmp_path / "manifest.csv"
    with manifest_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "dataset_id",
                "wind_farm",
                "event_id",
                "event_label",
                "event_component_category",
                "source_asset_id",
                "source_file",
                "normalized_file",
                "row_count",
            ],
        )
        writer.writeheader()
        writer.writerow({
            "dataset_id": "care_to_compare_v6",
            "wind_farm": "Wind Farm A",
            "event_id": "0",
            "event_label": "anomaly",
            "event_component_category": "gearbox",
            "source_asset_id": "0",
            "source_file": str(tmp_path / "raw.csv"),
            "normalized_file": str(csv_path),
            "row_count": "2",
        })
    monkeypatch.setattr("scripts.import_care_normalized_batch.REPORTS", tmp_path / "reports")

    args = argparse.Namespace(
        db_path=str(db_path),
        manifest=str(manifest_path),
        dataset_id="care_to_compare_v6",
        field_mapping_version="care_standard_field_mapping.csv",
        max_files=None,
        max_rows_per_file=None,
        commit_rows=1,
        asset_name_prefix="CARE",
        replace_dataset=True,
        dry_run=False,
    )
    summary = import_batch(args)

    assert summary["rows_imported"] == 1
    assert summary["rows_skipped"] == 1
    assert summary["anonymous_assets"] == 1
    con = sqlite3.connect(db_path)
    turbine = con.execute(
        "SELECT name, model, power_mw, lat, lng, source_dataset, source_asset_id, asset_scope, geo_scope FROM turbines"
    ).fetchone()
    assert turbine == (
        "CARE-Wind Farm A-0",
        None,
        None,
        None,
        None,
        "care_to_compare_v6",
        "Wind Farm A:0",
        "anonymous_public_dataset",
        "anonymous_unlocated",
    )
    extra = json.loads(con.execute("SELECT extra FROM scada_records").fetchone()[0])
    assert extra["source_asset_key"] == "Wind Farm A:0"
    assert extra["event_component_category"] == "gearbox"
    assert extra["field_mapping_version"] == "care_standard_field_mapping.csv"
    assert con.execute("SELECT status FROM data_sources WHERE name = 'care_to_compare_v6'").fetchone()[0] == "connected"
    con.close()
    assert (tmp_path / "reports" / "care_scada_import_batch_summary.json").exists()
