"""Vibration data loader with physics-based waveform generation.

Generates realistic vibration waveforms for wind turbine components
(gearbox, bearings, generator) with configurable fault signatures.
"""

from datetime import datetime, timedelta, timezone
import math
import random


class VibrationLoader:
    """Generate realistic vibration waveforms for wind turbine components."""

    COMPONENTS = ["gearbox_high_speed", "gearbox_intermediate", "generator_bearing_de",
                  "generator_bearing_nde", "main_bearing"]

    FAULT_SIGNATURES = {
        "bearing_inner_race": {"freq_factor": 5.43, "amplitude_boost": 3.0},
        "bearing_outer_race": {"freq_factor": 3.57, "amplitude_boost": 2.8},
        "bearing_ball": {"freq_factor": 2.38, "amplitude_boost": 2.2},
        "gearbox_tooth_wear": {"freq_factor": 1.0, "amplitude_boost": 1.8, "sideband_spacing": 2},
        "imbalance": {"freq_factor": 1.0, "amplitude_boost": 2.5},
        "misalignment": {"freq_factor": 2.0, "amplitude_boost": 2.0},
    }

    def __init__(self):
        pass

    def generate_waveform(
        self,
        turbine_id: int,
        component: str = "gearbox_high_speed",
        duration_seconds: float = 2.0,
        sample_rate_hz: int = 10240,
        fault_type: str | None = None,
    ) -> dict:
        """Generate a synthetic vibration waveform with optional fault signature.

        Returns time-domain waveform data, RMS, peak frequency, and FFT spectrum.
        """
        num_samples = int(duration_seconds * sample_rate_hz)
        t = [i / sample_rate_hz for i in range(num_samples)]

        # Base vibration: rotating frequency + harmonics + noise
        base_freq = 25.0 + random.uniform(-2, 2)  # ~25 Hz fundamental
        signal = [0.0] * num_samples

        # Fundamental + harmonics
        for h in range(1, 6):
            amp = 1.0 / (h ** 1.5) * random.uniform(0.8, 1.2)
            freq = base_freq * h
            for i in range(num_samples):
                signal[i] += amp * math.sin(2 * math.pi * freq * t[i])

        # Add fault signature if present
        fault_info = None
        if fault_type and fault_type in self.FAULT_SIGNATURES:
            sig = self.FAULT_SIGNATURES[fault_type]
            fault_freq = base_freq * sig["freq_factor"]
            for i in range(num_samples):
                signal[i] += sig["amplitude_boost"] * math.sin(2 * math.pi * fault_freq * t[i])

            if "sideband_spacing" in sig:
                for sb in range(1, sig["sideband_spacing"] + 1):
                    for i in range(num_samples):
                        signal[i] += 0.5 * math.sin(2 * math.pi * (fault_freq + sb * base_freq) * t[i])
                        signal[i] += 0.5 * math.sin(2 * math.pi * (fault_freq - sb * base_freq) * t[i])

            fault_info = {
                "type": fault_type,
                "characteristic_frequency_hz": round(fault_freq, 1),
                "severity": random.choice(["early", "moderate", "severe"]),
            }

        # Add noise
        for i in range(num_samples):
            signal[i] += random.gauss(0, 0.15)

        # Compute RMS
        rms = math.sqrt(sum(s ** 2 for s in signal) / num_samples)

        # Compute FFT (simplified: return peak frequencies)
        # Downsample for FFT spectrum display
        downsample = sample_rate_hz // 1000  # ~1000 points for spectrum
        spectrum = self._compute_spectrum(signal[::downsample], sample_rate_hz // downsample)

        # Peak frequencies from spectrum
        peak_indices = sorted(range(len(spectrum)), key=lambda i: spectrum[i], reverse=True)[:5]
        peak_freqs = [
            {"frequency_hz": round(idx * (sample_rate_hz / downsample) / len(spectrum), 1),
             "amplitude": round(spectrum[idx], 2)}
            for idx in peak_indices
        ]

        # Downsample waveform for display (too many points for browser)
        display_samples = min(num_samples, 2048)
        step = num_samples // display_samples
        waveform_display = [round(signal[i], 4) for i in range(0, num_samples, step)]

        return {
            "turbine_id": turbine_id,
            "component": component,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": duration_seconds,
            "sample_rate_hz": sample_rate_hz,
            "rms": round(rms, 3),
            "peak_amplitude": round(max(abs(s) for s in signal), 3),
            "waveform": waveform_display,
            "spectrum": [round(s, 3) for s in spectrum],
            "peak_frequencies": peak_freqs,
            "fault_detected": fault_info is not None,
            "fault_info": fault_info,
            "data_source": "physics_simulation",
        }

    @staticmethod
    def _compute_spectrum(signal: list[float], sample_rate: int) -> list[float]:
        """Simple DFT-based amplitude spectrum."""
        n = len(signal)
        spectrum = []
        for k in range(n // 2):
            real = sum(signal[i] * math.cos(2 * math.pi * k * i / n) for i in range(n))
            imag = sum(signal[i] * math.sin(2 * math.pi * k * i / n) for i in range(n))
            spectrum.append(math.sqrt(real ** 2 + imag ** 2) / n * 2)
        return spectrum[:n // 4]  # Only low-frequency portion is relevant


vibration_loader = VibrationLoader()
