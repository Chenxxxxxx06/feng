"""Real blade image dataset access guard.

Synthetic blade image generation is disabled. Import a public or measured blade
inspection image dataset before using blade diagnosis endpoints.
"""


class RealBladeImageDatasetRequired(RuntimeError):
    """Raised when code attempts to use generated blade images."""


class BladeImageSimulator:
    """Compatibility wrapper that rejects synthetic image generation."""

    def generate_inspection(self, *args, **kwargs) -> list[dict]:
        raise RealBladeImageDatasetRequired(
            "Synthetic blade image generation is disabled. "
            "Import a real blade image dataset first."
        )


blade_simulator = BladeImageSimulator()
