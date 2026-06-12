"""Tests for real dataset import preflight helpers."""

import argparse
import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.database import Base
from app.models import DataSource, SCADARecord, Turbine
from scripts.import_real_datasets import import_scada_csv, preview_scada_csv


def _scada_args(path: str, **overrides) -> argparse.Namespace:
    values = {
        "path": path,
        "dataset_id": "care_to_compare_v6",
        "source_doi": None,
        "source_url": None,
        "source_license": None,
        "timestamp_column": None,
        "power_column": None,
        "wind_speed_column": None,
        "rotor_rpm_column": None,
        "gen_temperature_column": None,
        "gearbox_temperature_column": None,
        "bearing_temperature_column": None,
        "pitch_angle_column": None,
        "nacelle_direction_column": None,
        "grid_frequency_column": None,
        "ambient_temperature_column": None,
        "source_turbine_column": None,
        "source_wind_farm_column": None,
        "allow_anonymous_assets": False,
        "anonymous_region": "anonymous_public_dataset",
        "asset_name_prefix": "CARE",
        "field_mapping_version": None,
        "max_rows": None,
        "batch_size": 1000,
        "dry_run": True,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_scada_dry_run_reports_mapping_and_quality(tmp_path, capsys):
    csv_path = tmp_path / "scada.csv"
    csv_path.write_text(
        "timestamp,active_power,wind_speed\n"
        "2024-01-01T00:00:00Z,1200,7.2\n"
        "bad-time,900,6.8\n",
        encoding="utf-8",
    )

    preview_scada_csv(_scada_args(str(csv_path)))
    report = json.loads(capsys.readouterr().out)

    assert report["dry_run"] is True
    assert report["files_ready"] == 1
    assert report["estimated_importable_rows"] == 1
    assert report["valid_timestamp_pct"] == 50.0
    file_report = report["reports"][0]
    assert file_report["field_mapping"]["timestamp"] == "timestamp"
    assert file_report["field_mapping"]["power_kw"] == "active_power"
    assert file_report["field_mapping"]["wind_speed_ms"] == "wind_speed"
    assert file_report["ready_for_import"] is True


def test_scada_dry_run_rejects_timestamp_only_file(tmp_path, capsys):
    csv_path = tmp_path / "timestamp_only.csv"
    csv_path.write_text(
        "timestamp\n"
        "2024-01-01T00:00:00Z\n",
        encoding="utf-8",
    )

    preview_scada_csv(_scada_args(str(csv_path)))
    report = json.loads(capsys.readouterr().out)

    assert report["files_ready"] == 0
    assert report["ready_for_import"] is False
    assert report["reports"][0]["ready_for_import"] is False
    assert report["reports"][0]["mapped_signal_fields"] == []


@pytest.mark.asyncio
async def test_scada_import_creates_anonymous_care_assets(tmp_path, monkeypatch, capsys):
    csv_path = tmp_path / "care_event.csv"
    csv_path.write_text(
        "timestamp,source_turbine_id,wind_farm,power_kw,wind_speed_ms\n"
        "2023-01-01T00:00:00,0,Wind Farm A,1200,7.2\n"
        "2023-01-01T00:10:00,0,Wind Farm A,1180,7.0\n",
        encoding="utf-8",
    )
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr("scripts.import_real_datasets.async_session", session_factory)
    monkeypatch.setattr("scripts.import_real_datasets.set_source_status", lambda *args, **kwargs: None)

    args = _scada_args(
        str(csv_path),
        dry_run=False,
        turbine_id=None,
        source_turbine_column="source_turbine_id",
        source_wind_farm_column="wind_farm",
        allow_anonymous_assets=True,
        field_mapping_version="care_standard_field_mapping.csv",
        batch_size=1,
    )
    await import_scada_csv(args)
    result = json.loads(capsys.readouterr().out)

    assert result["imported"] == 2
    assert result["anonymous_asset_count"] == 1

    async with session_factory() as db:
        turbine = (await db.execute(select(Turbine))).scalar_one()
        assert turbine.name == "CARE-Wind Farm A-0"
        assert turbine.source_dataset == "care_to_compare_v6"
        assert turbine.source_asset_id == "Wind Farm A:0"
        assert turbine.asset_scope == "anonymous_public_dataset"
        assert turbine.geo_scope == "anonymous_unlocated"
        assert turbine.lat is None
        assert turbine.lng is None
        assert turbine.model is None
        assert turbine.power_mw is None

        records = (await db.execute(select(SCADARecord).order_by(SCADARecord.timestamp))).scalars().all()
        assert len(records) == 2
        assert {record.turbine_id for record in records} == {turbine.id}
        assert records[0].extra["source_asset_key"] == "Wind Farm A:0"
        assert records[0].extra["field_mapping_version"] == "care_standard_field_mapping.csv"

        source = (await db.execute(select(DataSource).where(DataSource.source_type == "scada"))).scalar_one()
        assert source.status == "connected"
        assert source.connection_params["allow_anonymous_assets"] is True
        assert source.connection_params["anonymous_asset_count"] == 1

    await engine.dispose()
