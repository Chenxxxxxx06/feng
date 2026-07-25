"""SCADA dataset access guard.

SCADA fallback generation is disabled. Import CARE to Compare or measured SCADA
files before using operational data as evidence.
"""

from pathlib import Path


DATA_DIR = Path(__file__).parent.parent.parent.parent / "data"
SCADA_DIR = DATA_DIR / "scada"
CARE_DIR = SCADA_DIR / "care_to_compare"


class RealSCADADatasetRequired(RuntimeError):
    """Raised when code attempts to generate SCADA data."""


class SCADALoader:
    def is_real_data_available(self) -> bool:
        return any(SCADA_DIR.rglob("*.csv"))

    def generate_turbine_scada(self, *args, **kwargs) -> list[dict]:
        raise RealSCADADatasetRequired(
            "SCADA generation is disabled. Import real CARE or measured SCADA data first."
        )


scada_loader = SCADALoader()
