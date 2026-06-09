"""Real vibration dataset access guard.

Synthetic vibration generation is disabled. Import public or measured vibration
datasets into the database and data directory before using diagnosis endpoints.
"""


class RealVibrationDatasetRequired(RuntimeError):
    """Raised when code attempts to use generated vibration data."""


class VibrationLoader:
    """Compatibility wrapper that rejects synthetic waveform generation."""

    def generate_waveform(self, *args, **kwargs) -> dict:
        raise RealVibrationDatasetRequired(
            "Synthetic vibration waveform generation is disabled. "
            "Import a real vibration dataset first."
        )


vibration_loader = VibrationLoader()
