"""Align CARE anonymous SCADA assets with a display asset registry.

CARE to Compare v6 provides real SCADA timelines but anonymizes physical asset
metadata such as coordinates, models, and rated power. This script preserves the
real SCADA records and only adds a reproducible display registry for the 36
anonymous CARE assets so the monitoring page can use every imported turbine.
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "backend" / "fengdiao_phm.db"
DATASET_ID = "care_to_compare_v6"


FARM_META = {
    "Wind Farm A": {
        "display": "榆林靖边风场A区",
        "prefix": "YJ-A",
        "center": (37.61, 108.52),
        "model": "Goldwind GW155-3.3MW",
        "power_mw": 3.3,
        "bearing": 0.010,
    },
    "Wind Farm B": {
        "display": "榆林定边风场B区",
        "prefix": "YD-B",
        "center": (37.86, 107.73),
        "model": "Envision EN-156/3.3",
        "power_mw": 3.3,
        "bearing": 0.011,
    },
    "Wind Farm C": {
        "display": "榆林横山风场C区",
        "prefix": "YH-C",
        "center": (37.95, 109.22),
        "model": "Mingyang MySE3.2-156",
        "power_mw": 3.2,
        "bearing": 0.010,
    },
}


def _slot(source_asset_id: str) -> tuple[str, int]:
    farm, raw_asset = source_asset_id.split(":", 1)
    return farm, int(raw_asset)


def _display_coordinates(farm: str, asset_no: int, order_index: int) -> tuple[float, float]:
    meta = FARM_META[farm]
    lat0, lng0 = meta["center"]
    row = order_index // 6
    col = order_index % 6
    asset_offset = (asset_no % 5) * 0.0015
    lat = lat0 + (row - 2) * meta["bearing"] + asset_offset
    lng = lng0 + (col - 2.5) * meta["bearing"] * 1.35 - asset_offset
    return round(lat, 6), round(lng, 6)


def _display_name(farm: str, asset_no: int) -> str:
    prefix = FARM_META[farm]["prefix"]
    return f"{prefix}-{asset_no:03d}"


def align(db_path: Path, dry_run: bool = False) -> int:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT id, source_asset_id
        FROM turbines
        WHERE source_dataset = ?
        ORDER BY region, CAST(substr(source_asset_id, instr(source_asset_id, ':') + 1) AS INTEGER)
        """,
        (DATASET_ID,),
    ).fetchall()

    if not rows:
        raise RuntimeError(f"No CARE assets found in {db_path}")

    order_by_farm: dict[str, int] = {}
    updates = []
    for row in rows:
        farm, asset_no = _slot(row["source_asset_id"])
        if farm not in FARM_META:
            raise RuntimeError(f"Unexpected CARE farm name: {farm}")
        order_index = order_by_farm.get(farm, 0)
        order_by_farm[farm] = order_index + 1
        lat, lng = _display_coordinates(farm, asset_no, order_index)
        meta = FARM_META[farm]
        updates.append(
            {
                "id": row["id"],
                "name": _display_name(farm, asset_no),
                "model": meta["model"],
                "power_mw": meta["power_mw"],
                "lat": lat,
                "lng": lng,
                "region": meta["display"],
                "geo_scope": "display_registry",
            }
        )

    if dry_run:
        for item in updates:
            print(item)
        return len(updates)

    with con:
        con.executemany(
            """
            UPDATE turbines
            SET name = :name,
                model = :model,
                power_mw = :power_mw,
                lat = :lat,
                lng = :lng,
                region = :region,
                geo_scope = :geo_scope
            WHERE id = :id
            """,
            updates,
        )
    return len(updates)


def main() -> None:
    parser = argparse.ArgumentParser(description="Align CARE assets with display registry metadata")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    count = align(args.db, args.dry_run)
    action = "Would update" if args.dry_run else "Updated"
    print(f"{action} {count} CARE assets in {args.db}")


if __name__ == "__main__":
    main()
