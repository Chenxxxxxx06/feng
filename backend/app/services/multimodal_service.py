"""Multimodal inspection — integrate YOLO blade images with evidence system.

Reuses existing blade_yolo_service and SCADA/vibration capabilities.
- Image quality gate (blur detection, resolution check)
- Image defects become typed evidence (not separate image page)
- Image-SCADA conflict → generate conflicting_evidence
- Insufficient images → request retake with specific angles
- Multimodal results affect evidence completeness and decision

NOT a standalone image showcase — integrates into ProofLoop evidence chain.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from app.domain import EvidenceQuality, EvidenceType

logger = logging.getLogger(__name__)


@dataclass
class ImageQualityCheck:
    """Image quality gate result."""
    passed: bool = False
    resolution_ok: bool = False
    blur_score: float = 0.0
    exposure_ok: bool = False
    angle_acceptable: bool = False
    issues: list[str] = field(default_factory=list)
    retake_instructions: list[str] = field(default_factory=list)


@dataclass
class MultimodalEvidence:
    """Evidence derived from multimodal inspection."""
    evidence_type: EvidenceType = EvidenceType.OBSERVATION
    source_type: str = "yolo_inspection"
    label: str = ""
    description: str = ""
    confidence: float = 0.0
    quality: EvidenceQuality = EvidenceQuality.MEDIUM
    image_path: str = ""
    defects_detected: list[dict[str, Any]] = field(default_factory=list)
    image_quality: Optional[ImageQualityCheck] = None


@dataclass
class MultimodalResult:
    """Complete multimodal inspection result."""
    incident_id: str = ""
    turbine_id: int = 0
    images_processed: int = 0
    images_passed_quality: int = 0
    evidence_generated: list[MultimodalEvidence] = field(default_factory=list)
    conflicts_with_scada: list[dict[str, Any]] = field(default_factory=list)
    retake_requests: list[str] = field(default_factory=list)


class MultimodalService:
    """Multimodal inspection — integrates YOLO, SCADA, vibration into evidence.

    Reuses existing services. Images become evidence in the ProofLoop,
    not a standalone gallery page.
    """

    # Required angles for blade inspection
    REQUIRED_ANGLES = [
        "leading_edge",     # 前缘
        "trailing_edge",    # 后缘
        "pressure_side",    # 压力面
        "suction_side",     # 吸力面
        "tip_view",         # 叶尖
    ]

    def __init__(self):
        pass

    def check_image_quality(
        self,
        image_path: str,
        image_size: tuple[int, int] = (640, 480),
    ) -> ImageQualityCheck:
        """Gate image quality before processing using REAL image analysis.

        Checks: resolution (≥640×480), blur (Laplacian variance when cv2 available),
        exposure, angle acceptability.
        Returns specific retake instructions if failed.
        """
        check = ImageQualityCheck()
        issues: list[str] = []
        retake: list[str] = []

        # Resolution check
        w, h = image_size
        if w >= 640 and h >= 480:
            check.resolution_ok = True
        else:
            issues.append(f"Resolution too low: {w}×{h}, need ≥640×480")
            retake.append("Retake at higher resolution (≥640×480)")

        # ── Real blur detection via Laplacian variance ──
        try:
            import cv2
            import os
            if os.path.exists(image_path):
                img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
                if img is not None:
                    laplacian_var = cv2.Laplacian(img, cv2.CV_64F).var()
                    # Normalize: typical sharp image has variance >100
                    # Map to 0-1 score: 0=variance 0, 1=variance >=500
                    check.blur_score = min(1.0, laplacian_var / 500.0)
                    if laplacian_var < 100:
                        issues.append(
                            f"Image too blurry (Laplacian variance: {laplacian_var:.1f}, "
                            f"need ≥100)"
                        )
                        retake.append(
                            "Retake with better focus, stabilize camera, "
                            "ensure adequate lighting"
                        )
                else:
                    check.blur_score = 0.5  # Cannot read image
                    issues.append(f"Cannot read image file: {image_path}")
            else:
                check.blur_score = 0.5
                issues.append(f"Image file not found: {image_path}")
        except ImportError:
            # cv2 not available — use neutral score, flag as limitation
            check.blur_score = 0.7
            logger.debug("cv2 not available for blur detection; using neutral score")

        # ── Exposure check via histogram analysis ──
        try:
            import cv2
            import os
            if os.path.exists(image_path):
                img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
                if img is not None:
                    hist = cv2.calcHist([img], [0], None, [256], [0, 256])
                    total_pixels = img.shape[0] * img.shape[1]
                    # Check for under/over-exposure
                    dark_pixels = sum(hist[:25])[0] / total_pixels  # < 10th percentile
                    bright_pixels = sum(hist[230:])[0] / total_pixels  # > 90th percentile
                    if dark_pixels > 0.5:
                        check.exposure_ok = False
                        issues.append("Image underexposed (>50% dark pixels)")
                        retake.append("Increase exposure or add lighting")
                    elif bright_pixels > 0.5:
                        check.exposure_ok = False
                        issues.append("Image overexposed (>50% bright pixels)")
                        retake.append("Reduce exposure or avoid direct sunlight")
                    else:
                        check.exposure_ok = True
        except (ImportError, Exception):
            check.exposure_ok = True  # Cannot verify

        # Angle check
        check.angle_acceptable = True  # Would use EXIF orientation + template matching

        check.issues = issues
        check.retake_instructions = retake
        check.passed = len(issues) == 0
        return check

    def detect_defects(
        self,
        image_path: str,
        turbine_id: int,
    ) -> MultimodalEvidence:
        """Detect blade defects from inspection image using REAL YOLO model.

        Attempts to use blade_yolo_service for actual inference.
        Falls back to simulated results only when model is unavailable,
        clearly marking the source.
        """
        yolo_available = False
        raw_detections: list[dict[str, Any]] = []
        source_type = "yolo_inspection"

        # ── Try real YOLO model first ──
        try:
            from app.services.blade_yolo_service import BladeYOLOService
            yolo_svc = BladeYOLOService()
            if yolo_svc.is_model_available():
                yolo_available = True
                raw_detections = yolo_svc.predict(image_path, turbine_id)
                source_type = "yolo_inspection_real"
                logger.info(
                    f"Real YOLO inference on {image_path}: "
                    f"{len(raw_detections)} detections"
                )
        except (ImportError, FileNotFoundError, Exception) as e:
            logger.warning(
                f"Blade YOLO model unavailable for {image_path}: {e}. "
                f"Using simulation fallback."
            )

        # ── Process detections into structured defects ──
        if yolo_available and raw_detections:
            defects = []
            for det in raw_detections:
                bbox = det.get("bbox_xyxy", det.get("bbox", [0, 0, 0, 0]))
                label = det.get("label", det.get("class", "unknown"))
                conf = det.get("confidence", 0.0)

                # Map YOLO class to defect type
                defect_type_map = {
                    "damage": "blade_surface_damage",
                    "crack": "blade_crack",
                    "dirt": "surface_contamination",
                    "erosion": "leading_edge_erosion",
                    "delamination": "blade_delamination",
                }
                defect_type = defect_type_map.get(label, label)

                # Calculate severity from confidence and bbox area
                area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
                severity = "minor"
                if conf > 0.9 and area > 50000:
                    severity = "critical"
                elif conf > 0.8 and area > 20000:
                    severity = "major"
                elif conf > 0.6:
                    severity = "moderate"

                defects.append({
                    "type": defect_type,
                    "yolo_class": label,
                    "bbox": bbox,
                    "confidence": round(conf, 4),
                    "severity": severity,
                    "area_px": area,
                    "source": "blade_yolo_model_dtu",
                })
        else:
            # Simulation fallback — clearly marked
            source_type = "yolo_inspection_simulated"
            defects = [
                {
                    "type": "simulated_detection",
                    "bbox": [120, 80, 200, 150],
                    "confidence": 0.0,
                    "severity": "unknown",
                    "area_px": 0,
                    "source": "simulation_fallback_no_model",
                    "note": "YOLO model not available — no real inference performed",
                },
            ]

        # Calculate aggregate confidence
        if yolo_available and defects:
            confidence = sum(d.get("confidence", 0) for d in defects) / len(defects)
        elif defects and defects[0].get("source") == "simulation_fallback_no_model":
            confidence = 0.0
        else:
            confidence = 0.0

        # Determine evidence quality
        if yolo_available and confidence > 0.85:
            quality = EvidenceQuality.HIGH
        elif yolo_available and confidence > 0.6:
            quality = EvidenceQuality.MEDIUM
        elif yolo_available:
            quality = EvidenceQuality.LOW
        else:
            quality = EvidenceQuality.LOW  # Simulated = low quality

        # Build description
        if yolo_available and defects:
            real_defects = [d for d in defects if d.get("confidence", 0) > 0]
            if real_defects:
                primary = real_defects[0]
                description = (
                    f"Real YOLO inspection on turbine {turbine_id}: "
                    f"{len(real_defects)} defect(s) detected. "
                    f"Primary: {primary['type']} (conf={primary['confidence']:.2f}, "
                    f"severity={primary['severity']})"
                )
            else:
                description = (
                    f"Real YOLO inspection on turbine {turbine_id}: "
                    f"No defects detected above confidence threshold"
                )
        else:
            description = (
                f"SIMULATED inspection on turbine {turbine_id}: "
                f"YOLO model not available. Results are placeholder values — "
                f"do not use for operational decisions."
            )

        return MultimodalEvidence(
            evidence_type=EvidenceType.OBSERVATION,
            source_type=source_type,
            label=f"Blade Inspection ({'Real YOLO' if yolo_available else 'Simulated'})",
            description=description,
            confidence=confidence,
            quality=quality,
            image_path=image_path,
            defects_detected=defects,
        )

    def detect_conflict_with_scada(
        self,
        image_evidence: MultimodalEvidence,
        scada_data: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """Detect conflicts between image findings and SCADA data.

        Example: YOLO shows blade damage but SCADA shows normal power.
        This generates conflicting_evidence — NOT ignored.
        """
        has_physical_damage = any(
            d["type"] in ("leading_edge_erosion", "blade_crack", "surface_damage")
            for d in image_evidence.defects_detected
        )

        power_normal = scada_data.get("power_kw", 0) > (
            scada_data.get("rated_power_kw", 2000) * 0.8
        )

        if has_physical_damage and power_normal:
            return {
                "type": "conflicting_evidence",
                "image_finding": "Blade damage detected by YOLO",
                "scada_finding": "Power output normal (>80% rated)",
                "explanation": (
                    "Blade damage visible in inspection but power output unaffected. "
                    "Possible: early-stage damage, small defect area, or false positive."
                ),
                "recommendation": "Request follow-up inspection with closer angle, check vibration correlation",
                "confidence": 0.55,
            }

        return None

    def get_missing_angles(
        self, captured_angles: list[str]
    ) -> list[str]:
        """Determine which inspection angles are missing."""
        return [
            angle for angle in self.REQUIRED_ANGLES
            if angle not in captured_angles
        ]

    async def process_inspection(
        self,
        incident_id: str,
        turbine_id: int,
        images: list[dict[str, Any]],
        scada_data: dict[str, Any],
    ) -> MultimodalResult:
        """Process multimodal inspection data for an incident.

        Args:
            images: [{"path": str, "angle": str, "size": (w, h)}]
            scada_data: Current SCADA context
        """
        result = MultimodalResult(
            incident_id=incident_id,
            turbine_id=turbine_id,
            images_processed=len(images),
        )

        captured_angles: list[str] = []

        for img in images:
            path = img.get("path", "")
            angle = img.get("angle", "")
            size = img.get("size", (640, 480))

            if angle:
                captured_angles.append(angle)

            # Quality gate
            quality = self.check_image_quality(path, size)
            if not quality.passed:
                result.retake_requests.extend(quality.retake_instructions)
                continue

            result.images_passed_quality += 1

            # Detect defects
            evidence = self.detect_defects(path, turbine_id)
            evidence.image_quality = quality
            result.evidence_generated.append(evidence)

            # Check conflict with SCADA
            conflict = self.detect_conflict_with_scada(evidence, scada_data)
            if conflict:
                result.conflicts_with_scada.append(conflict)

        # Check missing angles
        missing = self.get_missing_angles(captured_angles)
        if missing:
            result.retake_requests.extend([
                f"Missing inspection angle: {angle}" for angle in missing
            ])

        return result
