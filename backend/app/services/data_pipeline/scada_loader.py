"""SCADA data loader for CARE to Compare dataset.

CARE dataset: 36 wind turbines, 89 years total, 44 labeled faults.
Dataset source: https://zenodo.org/records/14006163

When real dataset is not yet downloaded, generates industry-realistic
SCADA data with correct statistical properties for Shaanxi wind farms.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
import math
import random


DATA_DIR = Path(__file__).parent.parent.parent.parent / "data"
SCADA_DIR = DATA_DIR / "scada"
CARE_DIR = SCADA_DIR / "care_to_compare"


class SCADALoader:
    """Load and serve SCADA operational data."""

    def __init__(self):
        self._cache: dict[int, list[dict]] = {}
        self._ready = False

    def is_real_data_available(self) -> bool:
        return (CARE_DIR / "wind_farm_A.csv").exists() or \
               any(CARE_DIR.glob("*.csv"))

    def generate_turbine_scada(
        self, turbine_id: int, turbine_mw: float,
        hours: int = 24, resolution_min: int = 10,
    ) -> list[dict]:
        """Generate realistic SCADA data for a turbine.

        Creates data with correct physical relationships:
        - Power curve: P ∝ v³ (cubic relationship with wind speed, cut-in/rated/cut-out)
        - Temperature: correlates with power output
        - RPM: proportional to wind speed
        - Pitch angle: adjusts to regulate power above rated wind speed
        """
        rated_power_kw = turbine_mw * 1000
        rated_wind_speed = 12.0
        cut_in_speed = 3.0
        cut_out_speed = 25.0

        now = datetime.now(timezone.utc)
        records = []
        seed = turbine_id * 1000

        for i in range(0, hours * 60, resolution_min):
            ts = now - timedelta(minutes=i)
            # Use deterministic seed with timestamp for reproducibility
            random.seed(seed + i)

            # Generate wind speed with Weibull-like distribution
            shape = 2.2
            scale = 7.5
            wind = random.weibullvariate(scale, shape)
            wind = max(0.5, min(wind, 30.0))

            # Power curve
            if wind < cut_in_speed:
                power = 0.0
            elif wind < rated_wind_speed:
                power = rated_power_kw * (wind / rated_wind_speed) ** 3
            elif wind < cut_out_speed:
                power = rated_power_kw
                # Add slight variation at rated power
                power *= random.uniform(0.97, 1.0)
            else:
                power = 0.0

            # Rotor RPM (proportional to wind speed up to rated)
            if wind < rated_wind_speed:
                rpm = 5.0 + (wind - cut_in_speed) / (rated_wind_speed - cut_in_speed) * 12.0
            else:
                rpm = 17.0 + random.uniform(-0.3, 0.3)

            # Temperatures — rise with power output
            power_ratio = power / rated_power_kw if rated_power_kw > 0 else 0
            ambient = 20 + 10 * math.sin((ts.month - 3) * math.pi / 6) + random.uniform(-3, 3)
            gen_temp = ambient + 30 + power_ratio * 45 + random.uniform(-2, 2)
            gearbox_temp = ambient + 20 + power_ratio * 40 + random.uniform(-1.5, 1.5)
            bearing_temp = ambient + 15 + power_ratio * 35 + random.uniform(-1, 1)

            # Pitch angle — near 0 below rated, increases above
            if wind < rated_wind_speed:
                pitch = random.uniform(-1, 3)
            else:
                pitch = (wind - rated_wind_speed) * 2.5 + random.uniform(-1, 1)
                pitch = max(0, min(pitch, 25))

            records.append({
                "timestamp": ts.isoformat(),
                "power_kw": round(power, 1),
                "wind_speed_ms": round(wind, 1),
                "rotor_rpm": round(rpm, 1),
                "gen_temperature_c": round(gen_temp, 1),
                "gearbox_temperature_c": round(gearbox_temp, 1),
                "bearing_temperature_c": round(bearing_temp, 1),
                "pitch_angle_deg": round(pitch, 1),
                "nacelle_direction_deg": round(random.uniform(0, 360), 0),
                "grid_frequency_hz": round(50.0 + random.uniform(-0.1, 0.1), 2),
                "ambient_temp_c": round(ambient, 1),
                "data_source": "physics_simulation",
                "note": "CARE数据集待接入，当前使用物理仿真模型",
            })

        random.seed()
        return sorted(records, key=lambda r: r["timestamp"])


scada_loader = SCADALoader()
