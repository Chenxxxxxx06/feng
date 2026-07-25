"""Test data pipeline components."""
import pytest
from app.services.data_pipeline.era5_loader import RealWeatherDatasetRequired, era5_loader
from app.services.data_pipeline.scada_loader import RealSCADADatasetRequired, scada_loader
from app.services.data_pipeline.blade_simulator import RealBladeImageDatasetRequired, blade_simulator
from app.services.data_pipeline.vibration_loader import RealVibrationDatasetRequired, vibration_loader
from app.services.data_pipeline.geo_loader import geo_loader
from app.services.data_pipeline import get_pipeline_state, set_source_status, SourceStatus


class TestERA5Loader:
    def test_weather_generation_disabled(self):
        """Weather values must come from imported real datasets."""
        with pytest.raises(RealWeatherDatasetRequired):
            era5_loader.get_wind_at(38.0, 109.0)

    def test_wind_field_generation(self):
        with pytest.raises(RealWeatherDatasetRequired):
            era5_loader.get_wind_field({"north": 39, "south": 33, "west": 106, "east": 111})


class TestSCADALoader:
    def test_scada_generation_disabled(self):
        """SCADA values must come from imported real datasets or database records."""
        with pytest.raises(RealSCADADatasetRequired):
            scada_loader.generate_turbine_scada(1, 3.0, hours=24, resolution_min=60)


class TestBladeSimulator:
    def test_synthetic_blade_generation_disabled(self):
        """Blade diagnosis must use imported real image datasets."""
        with pytest.raises(RealBladeImageDatasetRequired):
            blade_simulator.generate_inspection(1, num_images=5)


class TestVibrationLoader:
    def test_synthetic_vibration_generation_disabled(self):
        """Vibration diagnosis must use imported real vibration datasets."""
        with pytest.raises(RealVibrationDatasetRequired):
            vibration_loader.generate_waveform(1)


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
            {"id": 3, "name": "CARE-Wind-Farm-A-0", "model": None, "power_mw": None,
             "lat": None, "lng": None, "region": "Wind Farm A", "status": "normal", "hi_value": 100},
        ]
        gj = geo_loader.build_turbines_geojson(turbines)
        assert gj["type"] == "FeatureCollection"
        assert len(gj["features"]) == 2
        assert gj["features"][0]["geometry"]["type"] == "Point"


class TestPipelineState:
    def test_pipeline_state_tracking(self):
        from app.services.data_pipeline import reset_pipeline_state
        reset_pipeline_state()
        state = get_pipeline_state()
        assert state.scada == SourceStatus.DISCONNECTED

        set_source_status("scada", SourceStatus.CONNECTED, 100)
        state = get_pipeline_state()
        assert state.scada == SourceStatus.CONNECTED
        assert state.scada_records == 100
