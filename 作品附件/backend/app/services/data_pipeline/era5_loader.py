"""ERA5 weather dataset access guard.

Weather fallback simulation is disabled. Import real ERA5/meteorological files
before exposing turbine weather values.
"""

from pathlib import Path


DATA_DIR = Path(__file__).parent.parent.parent.parent / "data"
ERA5_DIR = DATA_DIR / "era5"
ERA5_FILE = ERA5_DIR / "era5_wind_shaanxi_2024.nc"


class RealWeatherDatasetRequired(RuntimeError):
    """Raised when weather data is requested without an imported dataset."""


class ERA5WindLoader:
    def is_real_data_available(self) -> bool:
        return ERA5_FILE.exists()

    def load_turbine_locations(self, turbines: list[dict]):
        return None

    def get_wind_at(self, lat: float, lng: float, timestamp=None) -> dict:
        raise RealWeatherDatasetRequired(
            "Weather simulation is disabled. Import real ERA5 or measured weather data first."
        )

    def get_wind_field(self, bounds: dict) -> list[dict]:
        raise RealWeatherDatasetRequired(
            "Weather simulation is disabled. Import real ERA5 or measured weather data first."
        )


era5_loader = ERA5WindLoader()
