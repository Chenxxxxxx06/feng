"""Refresh CARE monitoring status from imported SCADA records.

This computes a lightweight dashboard health snapshot for each CARE asset using
the latest structured SCADA rows. It does not create or alter SCADA evidence.
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "backend" / "fengdiao_phm.db"
DATASET_ID = "care_to_compare_v6"
WINDOW_ROWS = 144


def _score(rows: list[sqlite3.Row]) -> tuple[float, str]:
    if not rows:
        return 80.0, "normal"

    issue_points = 0.0
    observations = 0
    for row in rows:
        observations += 1
        wind = row["wind_speed_ms"] or 0
        power = row["power_kw"] or 0
        gen_temp = row["gen_temperature_c"]
        gearbox_temp = row["gearbox_temperature_c"]
        rotor_rpm = row["rotor_rpm"]

        # CARE power is imported as normalized power. Penalize poor production
        # only when there is enough wind for meaningful output.
        if wind >= 8 and power < 0.25:
            issue_points += 1.8
        elif wind >= 6 and power < 0.10:
            issue_points += 0.9

        if gen_temp is not None and gen_temp > 92:
            issue_points += 1.0
        if gearbox_temp is not None and gearbox_temp > 85:
            issue_points += 1.0
        if wind >= 7 and rotor_rpm is not None and rotor_rpm <= 0:
            issue_points += 0.8

    issue_ratio = issue_points / max(observations * 4.6, 1)
    hi = max(35.0, min(99.0, 96.0 - issue_ratio * 70.0))
    hi = round(hi, 1)
    if hi >= 80:
        status = "normal"
    elif hi >= 60:
        status = "warning"
    else:
        status = "fault"
    return hi, status


def refresh(db_path: Path, dry_run: bool = False) -> int:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    turbines = con.execute(
        "SELECT id, name FROM turbines WHERE source_dataset = ? ORDER BY id",
        (DATASET_ID,),
    ).fetchall()
    updates = []
    for turbine in turbines:
        rows = con.execute(
            """
            SELECT power_kw, wind_speed_ms, rotor_rpm, gen_temperature_c, gearbox_temperature_c
            FROM scada_records
            WHERE turbine_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (turbine["id"], WINDOW_ROWS),
        ).fetchall()
        hi, status = _score(rows)
        updates.append({"id": turbine["id"], "hi_value": hi, "status": status, "name": turbine["name"]})

    if dry_run:
        for item in updates:
            print(item)
        return len(updates)

    with con:
        con.executemany(
            "UPDATE turbines SET hi_value = :hi_value, status = :status WHERE id = :id",
            updates,
        )
    return len(updates)


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh CARE dashboard health snapshot")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    count = refresh(args.db, args.dry_run)
    action = "Would refresh" if args.dry_run else "Refreshed"
    print(f"{action} {count} CARE monitoring snapshots in {args.db}")


if __name__ == "__main__":
    main()
