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
        """Gate image quality before processing.

        Checks: resolution (≥640×480), estimated blur, exposure.
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

        # Blur check (simulated — production uses Laplacian variance)
        check.blur_score = 0.85  # Simulated: 0-1, higher = sharper
        if check.blur_score < 0.3:
            issues.append(f"Image too blurry (score: {check.blur_score:.1f})")
            retake.append("Retake with better focus, stabilize camera")

        # Exposure check (simulated)
        check.exposure_ok = True

        # Angle check (simulated — production uses EXIF + template matching)
        check.angle_acceptable = True

        check.issues = issues
        check.retake_instructions = retake
        check.passed = len(issues) == 0
        return check

    def detect_defects(
        self,
        image_path: str,
        turbine_id: int,
    ) -> MultimodalEvidence:
        """Detect blade defects from inspection image.

        In production: calls blade_yolo_service.predict().
        Here: provides structured integration with evidence system.
        """
        # Simulated YOLO detection results
        # Production: blade_yolo_service.predict(image_path, turbine_id)
        defects = [
            {
                "type": "leading_edge_erosion",
                "bbox": [120, 80, 200, 150],
                "confidence": 0.82,
                "severity": "moderate",
                "area_mm2": 450,
            },
        ]

        confidence = 0.82 if defects else 0.0
        quality = EvidenceQuality.MEDIUM if confidence > 0.7 else EvidenceQuality.LOW

        return MultimodalEvidence(
            evidence_type=EvidenceType.OBSERVATION,
            source_type="yolo_inspection",
            label="Blade Inspection Result",
            description=(
                f"YOLO inspection on turbine {turbine_id}: "
                f"{len(defects)} defect(s) detected. "
                f"Primary: {defects[0]['type']} (conf={confidence:.2f})"
                if defects
                else f"No defects detected on turbine {turbine_id}"
            ),
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
