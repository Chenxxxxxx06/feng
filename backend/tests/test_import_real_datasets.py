"""Tests for real dataset import preflight helpers."""

import argparse
import json

from scripts.import_real_datasets import preview_scada_csv


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
