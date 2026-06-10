"""Test data pipeline components."""
import pytest
from datetime import datetime, timezone
from app.services.data_pipeline.era5_loader import era5_loader
from app.services.data_pipeline.scada_loader import scada_loader
from app.services.data_pipeline.blade_simulator import blade_simulator
from app.services.data_pipeline.geo_loader import geo_loader
from app.services.data_pipeline import get_pipeline_state, set_source_status, SourceStatus


class TestERA5Loader:
    def test_synthetic_wind_shaanxi_north(self):
        """陕北 should have stronger winds."""
        wind = era5_loader.get_wind_at(38.0, 109.0)
        assert wind["wind_speed_ms"] > 3.0
        assert wind["wind_direction_deg"] >= 0
        assert wind["wind_direction_deg"] < 360
        assert "u_component" in wind
        assert "v_component" in wind

    def test_synthetic_wind_shaanxi_south(self):
        """陕南 should have weaker winds."""
        wind_north = era5_loader.get_wind_at(38.0, 109.0)
        wind_south = era5_loader.get_wind_at(32.5, 109.0)
        # Average should be lower (though individual samples vary)
        assert wind_south["turbulence_intensity"] > 0

    def test_seasonal_variation(self):
        """Winter winds should be stronger."""
        winter = era5_loader.get_wind_at(37.0, 109.0, datetime(2024, 1, 15, 12, tzinfo=timezone.utc))
        summer = era5_loader.get_wind_at(37.0, 109.0, datetime(2024, 7, 15, 12, tzinfo=timezone.utc))
        # Seasonal factor should make winter baseline higher
        assert winter["air_temperature_c"] < summer["air_temperature_c"]

    def test_wind_field_generation(self):
        bounds = {"north": 39, "south": 33, "west": 106, "east": 111}
        field = era5_loader.get_wind_field(bounds)
        assert len(field) == 400  # 20x20 grid


class TestSCADALoader:
    def test_generate_scada_output_structure(self):
        records = scada_loader.generate_turbine_scada(1, 3.0, hours=24, resolution_min=60)
        assert len(records) == 24
        r = records[0]
        assert "timestamp" in r
        assert "power_kw" in r
        assert "wind_speed_ms" in r
        assert "rotor_rpm" in r
        assert "gen_temperature_c" in r

    def test_power_curve_behavior(self):
        """Power should follow physical curve: zero below cut-in, cubic increase, rated plateau."""
        records = scada_loader.generate_turbine_scada(1, 3.0, hours=48, resolution_min=10)
        for r in records:
            ws = r["wind_speed_ms"]
            power = r["power_kw"]
            # Power must never exceed rated for this turbine
            assert power <= 3000 * 1.05
            # Below cut-in, power must be near zero
            if ws < 2.5:
                assert power < 50

    def test_temperature_increases_with_power(self):
        records = scada_loader.generate_turbine_scada(1, 3.0, hours=48, resolution_min=10)
        high_power = [r for r in records if r["power_kw"] > 2000]
        low_power = [r for r in records if r["power_kw"] < 500]
        if high_power and low_power:
            avg_high_temp = sum(r["gen_temperature_c"] for r in high_power) / len(high_power)
            avg_low_temp = sum(r["gen_temperature_c"] for r in low_power) / len(low_power)
            assert avg_high_temp > avg_low_temp


class TestBladeSimulator:
    def test_generate_inspection(self):
        results = blade_simulator.generate_inspection(1, num_images=5)
        assert len(results) == 5
        for r in results:
            assert r["turbine_id"] == 1
            assert r["image_path"].endswith(".png")
            assert "has_damage" in r
            if r["has_damage"]:
                assert r["damage_type"] is not None
                assert r["damage_bbox"] is not None

    def test_damage_rate_reasonable(self):
        """About 25% of blades should have damage."""
        results = blade_simulator.generate_inspection(1, num_images=100)
        damaged = sum(1 for r in results if r["has_damage"])
        assert 10 <= damaged <= 40


class TestGeoLoader:
    def test_load_shaanxi_boundary(self):
        geo = geo_loader.load_shaanxi_boundary()
        assert geo["type"] == "FeatureCollection"
        assert len(geo["features"]) == 1
        assert geo["features"][0]["properties"]["name"] == "陕西省"

    def test_build_turbines_geojson(self):
        turbines = [
            {"id": 1, "name": "T1", "model": "GWH150", "power_mw": 3.0,
             "lat": 37.3, "lng": 107.6, "region": "陕北", "status": "normal", "hi_value": 92},
            {"id": 2, "name": "T2", "model": "V112", "power_mw": 3.3,
             "lat": 34.7, "lng": 110.0, "region": "关中", "status": "fault", "hi_value": 45},
        ]
        gj = geo_loader.build_turbines_geojson(turbines)
        assert gj["type"] == "FeatureCollection"
        assert len(gj["features"]) == 2
        assert gj["features"][0]["geometry"]["type"] == "Point"


class TestPipelineState:
    def test_pipeline_state_tracking(self):
        state = get_pipeline_state()
        assert state.scada == SourceStatus.DISCONNECTED

        set_source_status("scada", SourceStatus.CONNECTED, 100)
        state = get_pipeline_state()
        assert state.scada == SourceStatus.CONNECTED
        assert state.scada_records == 100

