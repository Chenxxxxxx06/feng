"""Geographic data loader for Shaanxi province."""

from pathlib import Path
import json


DATA_DIR = Path(__file__).parent.parent.parent.parent / "data"
GEOJSON_DIR = DATA_DIR / "geojson"


class GeoLoader:
    """Load geographic data for Shaanxi wind farm visualization."""

    def __init__(self):
        self._shaanxi_geojson: dict | None = None
        self._turbines_geojson: dict | None = None

    def load_shaanxi_boundary(self) -> dict:
        """Load Shaanxi province boundary as GeoJSON."""
        if self._shaanxi_geojson:
            return self._shaanxi_geojson

        shaanxi_file = GEOJSON_DIR / "shaanxi.json"
        if shaanxi_file.exists():
            with open(shaanxi_file, encoding="utf-8") as f:
                self._shaanxi_geojson = json.load(f)
        else:
            self._shaanxi_geojson = self._generate_fallback()
        return self._shaanxi_geojson

    def build_turbines_geojson(self, turbines: list[dict]) -> dict:
        """Convert turbine list to GeoJSON FeatureCollection."""
        features = []
        for t in turbines:
            color = {
                "normal": "#3fb950",
                "warning": "#d29922",
                "fault": "#f85149",
            }.get(t.get("status", "normal"), "#8b949e")

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [t["lng"], t["lat"]],
                },
                "properties": {
                    "id": t.get("id"),
                    "name": t.get("name", ""),
                    "model": t.get("model", ""),
                    "power_mw": t.get("power_mw", 0),
                    "region": t.get("region", ""),
                    "status": t.get("status", "normal"),
                    "hi_value": t.get("hi_value", 100),
                    "color": color,
                },
            })

        self._turbines_geojson = {
            "type": "FeatureCollection",
            "features": features,
        }
        return self._turbines_geojson

    def get_shaanxi_center(self) -> tuple[float, float]:
        """Get Shaanxi geographic center."""
        return 36.0, 109.0

    def get_shaanxi_bounds(self) -> dict:
        """Get Shaanxi bounding box."""
        return {
            "north": 39.58,
            "south": 31.70,
            "west": 105.48,
            "east": 111.25,
        }

    @staticmethod
    def _generate_fallback() -> dict:
        """Minimal fallback GeoJSON."""
        return {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"name": "陕西省", "name_en": "Shaanxi"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [105.48, 31.70], [111.25, 31.70], [111.25, 39.58],
                        [105.48, 39.58], [105.48, 31.70],
                    ]],
                },
            }],
        }


geo_loader = GeoLoader()
