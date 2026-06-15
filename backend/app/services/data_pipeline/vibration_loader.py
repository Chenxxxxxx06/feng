"""Vibration dataset loader — multi-format import.

Supports:
  - MATLAB .mat files (NREL GRC gearbox, Mendeley blade vibration)
  - Semicolon-delimited CSV (Mendeley blade vibration dataset)
  - XLSX Excel files (Mendeley blade vibration dataset)
  - JSON waveform files (CARE reference)

Usage:
    from app.services.data_pipeline.vibration_loader import import_vibration_file
    result = await import_vibration_file(db, path, turbine_id, component)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import VibrationData

logger = logging.getLogger(__name__)

MIN_SAMPLES = 50       # Reject series shorter than this
DEFAULT_SAMPLE_RATE = 1000  # Hz, from Mendeley dataset documentation


class RealVibrationDatasetRequired(RuntimeError):
    """Raised when code attempts to use generated vibration data."""


class VibrationImportError(ValueError):
    """Failed to parse a vibration file."""


def _compute_rms(waveform: list[float]) -> float:
    arr = np.array(waveform, dtype=np.float64)
    return float(np.sqrt(np.mean(arr ** 2)))


def _compute_spectrum(waveform: list[float], sample_rate: float) -> list[float]:
    """Compute single-sided amplitude spectrum from waveform."""
    n = len(waveform)
    if n < 2:
        return []
    fft = np.fft.rfft(np.array(waveform, dtype=np.float64))
    magnitude = np.abs(fft) / n
    magnitude[1:-1] *= 2  # double except DC and Nyquist
    return magnitude.tolist()


def _compute_peak_frequencies(
    waveform: list[float], sample_rate: float, top_n: int = 5
) -> list[dict]:
    """Find top-N peak frequencies in spectrum."""
    n = len(waveform)
    if n < 4:
        return []
    magnitude = np.abs(np.fft.rfft(np.array(waveform, dtype=np.float64)))
    freqs = np.fft.rfftfreq(n, d=1.0 / sample_rate)
    # Find peaks (simple local maxima)
    peaks = []
    for i in range(1, len(magnitude) - 1):
        if magnitude[i] > magnitude[i - 1] and magnitude[i] > magnitude[i + 1]:
            peaks.append((float(freqs[i]), float(magnitude[i])))
    peaks.sort(key=lambda x: x[1], reverse=True)
    return [
        {"frequency_hz": round(f, 2), "amplitude": round(a, 6)}
        for f, a in peaks[:top_n]
    ]


def _try_load_mat(path: Path) -> dict | None:
    """Try to load a MATLAB .mat file. Returns waveform dict or None."""
    try:
        from scipy.io import loadmat
    except ImportError:
        logger.warning("scipy not installed — cannot read .mat files")
        return None

    try:
        mat = loadmat(str(path))
    except Exception as exc:
        raise VibrationImportError(f"Cannot read .mat file: {exc}") from exc

    # Find vibration channels (AN3-AN10 are typical accelerometer channels)
    channel_names = [k for k in mat.keys() if not k.startswith("__")]
    signal_channels = [
        k for k in channel_names
        if k.startswith("AN") or "vib" in k.lower() or "accel" in k.lower()
    ]

    if not signal_channels:
        # Try any 1-D array as a fallback
        for k in channel_names:
            arr = mat[k]
            if hasattr(arr, "shape") and len(arr.shape) == 1 and arr.shape[0] >= MIN_SAMPLES:
                signal_channels = [k]
                break

    if not signal_channels:
        return None

    # Use first available signal channel
    channel = signal_channels[0]
    raw = mat[channel]
    waveform = raw.flatten().tolist() if hasattr(raw, "flatten") else list(raw)

    if len(waveform) < MIN_SAMPLES:
        raise VibrationImportError(
            f"Vibration series too short ({len(waveform)} samples) in {path.name}"
        )

    sample_rate = DEFAULT_SAMPLE_RATE
    # Try to read sample rate from file (Speed variable is RPM in NREL dataset)
    if "Speed" in mat:
        rpm = float(np.mean(mat["Speed"])) if hasattr(mat["Speed"], "mean") else 30.0
        # Sample rate is approximately RPM-dependent for gearbox datasets
        sample_rate = max(1000, int(rpm * 60))

    rms = _compute_rms(waveform)
    spectrum = _compute_spectrum(waveform, sample_rate)
    peak_freqs = _compute_peak_frequencies(waveform, sample_rate)

    return {
        "sample_rate_hz": sample_rate,
        "sample_count": len(waveform),
        "duration_seconds": len(waveform) / sample_rate,
        "rms": round(rms, 6),
        "waveform": waveform,
        "spectrum": spectrum,
        "peak_frequencies": peak_freqs,
        "fault_detected": "damaged" in str(path).lower() or "fault" in str(path).lower(),
        "source_channel": channel,
    }


def _try_load_csv(path: Path) -> dict | None:
    """Try to load a semicolon-delimited or comma-delimited vibration CSV."""
    import csv

    # Detect delimiter
    with path.open("r", encoding="utf-8-sig") as fh:
        first_line = fh.readline()
    delimiter = ";" if ";" in first_line else ","

    try:
        with path.open("r", encoding="utf-8-sig") as fh:
            reader = csv.reader(fh, delimiter=delimiter)
            rows = list(reader)
    except Exception as exc:
        raise VibrationImportError(f"Cannot read CSV: {exc}") from exc

    if len(rows) < MIN_SAMPLES:
        return None

    # Try to convert to floats — use the column with the most numeric values
    num_rows = len(rows)
    best_col: list[float] = []
    for col_idx in range(len(rows[0]) if rows else 0):
        try:
            col = [float(rows[i][col_idx]) for i in range(num_rows) if rows[i][col_idx].strip()]
        except (ValueError, IndexError):
            continue
        if len(col) > len(best_col):
            best_col = col

    if len(best_col) < MIN_SAMPLES:
        return None

    waveform = best_col[:5000]  # Limit to 5000 samples for performance
    sample_rate = DEFAULT_SAMPLE_RATE
    rms = _compute_rms(waveform)
    spectrum = _compute_spectrum(waveform, sample_rate)
    peak_freqs = _compute_peak_frequencies(waveform, sample_rate)

    return {
        "sample_rate_hz": sample_rate,
        "sample_count": len(waveform),
        "duration_seconds": len(waveform) / sample_rate,
        "rms": round(rms, 6),
        "waveform": waveform,
        "spectrum": spectrum,
        "peak_frequencies": peak_freqs,
        "fault_detected": False,
        "source_channel": "csv_auto_detect",
    }


async def import_vibration_file(
    db: AsyncSession,
    path: Path,
    turbine_id: int,
    component: str = "blade",
) -> dict:
    """Import a single vibration file into the database.

    Args:
        db: Database session
        path: Path to .mat, .csv, .xlsx, or .json file
        turbine_id: Target turbine ID
        component: Component name (blade, gearbox_high_speed, etc.)

    Returns:
        Dict with import result metadata.
    """
    suffix = path.suffix.lower()

    if suffix == ".mat":
        payload = _try_load_mat(path)
        source = "matlab_mat"
    elif suffix == ".csv":
        payload = _try_load_csv(path)
        source = "csv"
    elif suffix in (".xlsx", ".xls"):
        # XLSX support requires openpyxl — read via pandas if available
        try:
            import pandas as pd
            df = pd.read_excel(str(path))
            numeric_cols = df.select_dtypes(include=[np.number])
            if numeric_cols.empty:
                raise VibrationImportError("No numeric columns in XLSX")
            waveform = numeric_cols.iloc[:, 0].dropna().tolist()[:5000]
            if len(waveform) < MIN_SAMPLES:
                raise VibrationImportError(f"XLSX series too short ({len(waveform)} samples)")
            rms = _compute_rms(waveform)
            spectrum = _compute_spectrum(waveform, DEFAULT_SAMPLE_RATE)
            peak_freqs = _compute_peak_frequencies(waveform, DEFAULT_SAMPLE_RATE)
            payload = {
                "sample_rate_hz": DEFAULT_SAMPLE_RATE,
                "sample_count": len(waveform),
                "duration_seconds": len(waveform) / DEFAULT_SAMPLE_RATE,
                "rms": round(rms, 6),
                "waveform": waveform,
                "spectrum": spectrum,
                "peak_frequencies": peak_freqs,
                "fault_detected": False,
                "source_channel": "xlsx_auto_detect",
            }
            source = "xlsx"
        except ImportError:
            raise VibrationImportError("pandas/openpyxl required for XLSX import")
    elif suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        source = "json"
    else:
        raise VibrationImportError(f"Unsupported file type: {suffix}")

    if payload is None:
        raise VibrationImportError(f"No valid vibration data found in {path.name}")

    # Save waveform to data directory
    from datetime import datetime, timezone
    from app.database import DATA_DIR as _dd
    waveform_dir = Path(__file__).resolve().parents[2] / "data" / "vibration" / "imported"
    waveform_dir.mkdir(parents=True, exist_ok=True)
    waveform_path = waveform_dir / f"turbine_{turbine_id}_{path.stem}.json"
    waveform_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    rel_path = waveform_path.relative_to(Path(__file__).resolve().parents[2] / "data").as_posix()

    # Create DB record
    record = VibrationData(
        turbine_id=turbine_id,
        timestamp=datetime.now(timezone.utc),
        component=component,
        rms=payload["rms"],
        peak_freq_hz=payload["peak_frequencies"][0]["frequency_hz"] if payload.get("peak_frequencies") else None,
        waveform_path=rel_path,
    )
    db.add(record)
    await db.commit()

    return {
        "turbine_id": turbine_id,
        "component": component,
        "source": source,
        "source_file": str(path),
        "samples": payload["sample_count"],
        "rms": payload["rms"],
        "waveform_path": rel_path,
    }


class VibrationLoader:
    """Compatibility wrapper — rejects synthetic generation."""

    def generate_waveform(self, *args, **kwargs) -> dict:
        raise RealVibrationDatasetRequired(
            "Synthetic vibration waveform generation is disabled. "
            "Import a real vibration dataset first using import_vibration_file()."
        )


vibration_loader = VibrationLoader()
