"""Drone inspection API — mission persistence, image capture, evidence linking.

P0-1: Inspection tasks and evidence assets must be persisted.
P0-2: Drone results enter the incident center.
P0-3: Image quality gate triggers retake requests.
"""

import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    BladeImage,
    EvidenceNode,
    Incident,
    InspectionMission,
    Turbine,
    User,
)
from app.api.auth import get_current_user, require_role

router = APIRouter(dependencies=[Depends(get_current_user)])
logger = logging.getLogger(__name__)

# ── Config ──
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
IMAGE_DIR = DATA_DIR / "drone_inspection"
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff"}
MAX_FILE_SIZE_MB = 50


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _next_mission_id() -> str:
    seq = uuid.uuid4().hex[:6]
    return f"MIS-{_utc_now().strftime('%Y%m%d')}-{seq}"


# ── Schemas ──

class WaypointSchema(BaseModel):
    lat: float
    lng: float
    alt: float
    angle: str = "leading_edge"
    part: str = "blade"
    seq: int = 0


class MissionCreateRequest(BaseModel):
    turbine_id: int
    component: str = "blade"
    waypoints: list[WaypointSchema] = []
    drone_id: Optional[str] = None
    pilot: Optional[str] = None


class ImageCaptureRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    mission_id: str
    turbine_id: int
    component: str = "blade"
    angle: str = "leading_edge"
    waypoint_index: int = 0
    gps_lat: Optional[float] = None
    gps_lng: Optional[float] = None
    altitude_m: Optional[float] = None
    shoot_distance_m: Optional[float] = None
    algorithm_mode: str = "demo_fixture"
    model_version: Optional[str] = None
    data_source: Optional[str] = None
    data_license: Optional[str] = None


class ImageQualityResult(BaseModel):
    image_id: int
    passed: bool
    blur_score: Optional[float] = None
    exposure_ok: Optional[bool] = None
    issues: list[str] = []
    retake_reason: Optional[str] = None


class DefectDetectionResult(BaseModel):
    image_id: int
    diagnosis_type: Optional[str] = None
    diagnosis_confidence: Optional[float] = None
    defects_detected: Optional[list[dict]] = None
    bbox: Optional[list[float]] = None
    algorithm_mode: str = "demo_fixture"


# ═══════════════════════════════════════════════════════════════════
# Mission CRUD
# ═══════════════════════════════════════════════════════════════════


@router.post("/missions", status_code=201)
async def create_mission(
    body: MissionCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("operator")),
):
    """Create a drone inspection mission with waypoints."""
    turbine = await db.get(Turbine, body.turbine_id)
    if not turbine:
        raise HTTPException(status_code=404, detail="Turbine not found")

    mission = InspectionMission(
        mission_id=_next_mission_id(),
        turbine_id=body.turbine_id,
        component=body.component,
        status="planned",
        waypoints=[w.model_dump() for w in body.waypoints],
        drone_id=body.drone_id,
        pilot=body.pilot or user.username,
    )
    db.add(mission)
    await db.commit()
    await db.refresh(mission)

    return {
        "id": mission.id,
        "mission_id": mission.mission_id,
        "turbine_id": mission.turbine_id,
        "turbine_name": turbine.name,
        "component": mission.component,
        "status": mission.status,
        "waypoints": mission.waypoints,
        "created_at": mission.created_at.isoformat(),
    }


@router.get("/missions")
async def list_missions(
    turbine_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """List inspection missions with optional filtering."""
    q = select(InspectionMission).order_by(InspectionMission.created_at.desc())
    if turbine_id:
        q = q.where(InspectionMission.turbine_id == turbine_id)
    if status:
        q = q.where(InspectionMission.status == status)
    result = await db.execute(q)
    missions = result.scalars().all()
    return [
        {
            "id": m.id,
            "mission_id": m.mission_id,
            "turbine_id": m.turbine_id,
            "component": m.component,
            "status": m.status,
            "total_shots": m.total_shots,
            "passed_shots": m.passed_shots,
            "failed_shots": m.failed_shots,
            "created_at": m.created_at.isoformat(),
        }
        for m in missions
    ]


@router.get("/missions/{mission_id}")
async def get_mission(
    mission_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get mission detail with all captured images."""
    result = await db.execute(
        select(InspectionMission).where(InspectionMission.mission_id == mission_id)
    )
    mission = result.scalar_one_or_none()
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")

    # Get images
    img_result = await db.execute(
        select(BladeImage)
        .where(BladeImage.mission_id == mission.id)
        .order_by(BladeImage.captured_at.asc())
    )
    images = img_result.scalars().all()

    turbine = await db.get(Turbine, mission.turbine_id)

    return {
        "mission_id": mission.mission_id,
        "turbine_id": mission.turbine_id,
        "turbine_name": turbine.name if turbine else "",
        "component": mission.component,
        "status": mission.status,
        "waypoints": mission.waypoints,
        "total_shots": mission.total_shots,
        "passed_shots": mission.passed_shots,
        "failed_shots": mission.failed_shots,
        "incident_id": mission.incident_id,
        "images": [
            {
                "id": img.id,
                "component": img.component,
                "angle": img.inspection_angle,
                "waypoint_index": img.waypoint_index,
                "gps_lat": img.gps_lat,
                "gps_lng": img.gps_lng,
                "image_path": img.image_path,
                "quality_passed": img.quality_passed,
                "retake_requested": img.retake_requested,
                "retake_reason": img.retake_reason,
                "algorithm_mode": img.algorithm_mode,
                "diagnosis_type": img.diagnosis_type,
                "diagnosis_confidence": img.diagnosis_confidence,
                "evidence_id": img.evidence_id,
                "captured_at": img.captured_at.isoformat() if img.captured_at else None,
            }
            for img in images
        ],
    }


@router.put("/missions/{mission_id}/status")
async def update_mission_status(
    mission_id: str,
    status: str = Query(..., description="in_flight/completed/aborted"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("operator")),
):
    """Update mission status."""
    result = await db.execute(
        select(InspectionMission).where(InspectionMission.mission_id == mission_id)
    )
    mission = result.scalar_one_or_none()
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")

    mission.status = status
    if status in ("completed", "aborted"):
        mission.completed_at = _utc_now()
    elif status == "in_flight":
        mission.started_at = _utc_now()

    await db.commit()
    return {"mission_id": mission.mission_id, "status": mission.status}


# ═══════════════════════════════════════════════════════════════════
# Image Capture & Upload
# ═══════════════════════════════════════════════════════════════════


@router.post("/missions/{mission_id}/capture", status_code=201)
async def capture_image(
    mission_id: str,
    image: UploadFile = File(...),
    body: ImageCaptureRequest = Depends(),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("operator")),
):
    """Upload a captured inspection image for a mission.

    Security: validates file type, size, and stores in controlled directory.
    Path is never derived from client input.
    """
    # ── Validate mission ──
    result = await db.execute(
        select(InspectionMission).where(InspectionMission.mission_id == mission_id)
    )
    mission = result.scalar_one_or_none()
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")

    # ── Security: validate file ──
    if not image.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    ext = os.path.splitext(image.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{ext}' not allowed. Accepted: {ALLOWED_EXTENSIONS}",
        )

    content = await image.read()
    if len(content) > MAX_FILE_SIZE_MB * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail=f"File too large (max {MAX_FILE_SIZE_MB}MB)",
        )

    # ── Store in controlled directory ──
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    ts = _utc_now().strftime("%Y%m%d_%H%M%S")
    safe_name = f"{mission_id}_{body.angle}_{body.waypoint_index}_{ts}{ext}"
    file_path = IMAGE_DIR / safe_name
    file_path.write_bytes(content)

    # ── Persist record ──
    relative_path = f"drone_inspection/{safe_name}"
    record = BladeImage(
        mission_id=mission.id,
        turbine_id=body.turbine_id,
        component=body.component,
        inspection_angle=body.angle,
        waypoint_index=body.waypoint_index,
        gps_lat=body.gps_lat,
        gps_lng=body.gps_lng,
        altitude_m=body.altitude_m,
        shoot_distance_m=body.shoot_distance_m,
        timestamp=_utc_now(),
        image_path=relative_path,
        algorithm_mode=body.algorithm_mode,
        model_version=body.model_version,
        data_source=body.data_source or "demo_fixture",
        data_license=body.data_license,
        captured_at=_utc_now(),
    )
    db.add(record)

    # Update mission counters
    mission.total_shots = (mission.total_shots or 0) + 1

    await db.commit()
    await db.refresh(record)

    return {
        "id": record.id,
        "mission_id": mission.mission_id,
        "image_path": record.image_path,
        "angle": record.inspection_angle,
        "waypoint_index": record.waypoint_index,
        "captured_at": record.captured_at.isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════
# Image Quality Gate (P0-3)
# ═══════════════════════════════════════════════════════════════════


@router.post("/images/{image_id}/quality-check")
async def check_image_quality(
    image_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("operator")),
):
    """Run image quality gate on a captured image.

    Checks: resolution, blur (Laplacian variance), exposure (histogram).
    Failed images get retake_reason set — they cannot proceed to diagnosis.
    """
    record = await db.get(BladeImage, image_id)
    if not record:
        raise HTTPException(status_code=404, detail="Image not found")

    full_path = DATA_DIR / record.image_path
    # Idempotency: re-running quality check must not re-increment mission counters
    first_check = record.quality_passed is None
    issues: list[str] = []
    blur_score: float = 0.5
    exposure_ok = True
    passed = True

    if full_path.exists():
        try:
            import cv2
            img = cv2.imread(str(full_path), cv2.IMREAD_GRAYSCALE)
            if img is not None:
                h, w = img.shape
                record.image_width = w
                record.image_height = h

                # Resolution check
                if w < 640 or h < 480:
                    issues.append(f"分辨率过低: {w}x{h} (需要≥640x480)")
                    passed = False

                # Blur check
                laplacian_var = cv2.Laplacian(img, cv2.CV_64F).var()
                blur_score = round(min(1.0, laplacian_var / 500.0), 4)
                if laplacian_var < 100:
                    issues.append(f"图像模糊 (Laplacian方差: {laplacian_var:.1f})")
                    passed = False

                # Exposure check
                hist = cv2.calcHist([img], [0], None, [256], [0, 256])
                total = img.shape[0] * img.shape[1]
                dark_pct = sum(hist[:25])[0] / total
                bright_pct = sum(hist[230:])[0] / total
                if dark_pct > 0.5:
                    exposure_ok = False
                    issues.append("曝光不足 (过暗)")
                    passed = False
                elif bright_pct > 0.5:
                    exposure_ok = False
                    issues.append("过曝 (过亮)")
                    passed = False
        except ImportError:
            issues.append("cv2不可用，使用默认质量值")
        except Exception as e:
            issues.append(f"质量检查异常: {e}")
            passed = False
    else:
        issues.append(f"图像文件不存在: {record.image_path}")
        passed = False

    # Update record
    record.quality_passed = passed
    record.quality_blur_score = blur_score
    record.quality_exposure_ok = exposure_ok
    record.quality_issues = issues
    if not passed:
        record.retake_requested = True
        record.retake_reason = "; ".join(issues)

    # Update mission counters (only on first quality check for this image)
    if record.mission_id and first_check:
        mission = await db.get(InspectionMission, record.mission_id)
        if mission:
            if passed:
                mission.passed_shots = (mission.passed_shots or 0) + 1
            else:
                mission.failed_shots = (mission.failed_shots or 0) + 1

    await db.commit()
    await db.refresh(record)

    return {
        "image_id": record.id,
        "passed": passed,
        "blur_score": blur_score,
        "exposure_ok": exposure_ok,
        "issues": issues,
        "retake_reason": record.retake_reason,
        "retake_requested": record.retake_requested,
    }


# ═══════════════════════════════════════════════════════════════════
# Defect Detection & Evidence Linking (P0-2)
# ═══════════════════════════════════════════════════════════════════


@router.post("/images/{image_id}/detect")
async def detect_defects(
    image_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("engineer")),
):
    """Run defect detection on a quality-passed image.

    Attempts real YOLO inference if available, otherwise uses demo_fixture.
    Mode is recorded on the image record for transparency.
    """
    record = await db.get(BladeImage, image_id)
    if not record:
        raise HTTPException(status_code=404, detail="Image not found")

    if not record.quality_passed:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot detect on quality-failed image. Retake reason: {record.retake_reason}",
        )

    full_path = DATA_DIR / record.image_path
    defects: list[dict] = []
    diagnosis_type = "no_damage"
    confidence = 0.0
    algorithm_mode = "model_unavailable"
    model_version = None
    bbox = None
    real_inference_ran = False

    # ── Try real YOLO inference ──
    try:
        from app.services.blade_yolo_service import blade_yolo_service
        if blade_yolo_service.is_model_available() and full_path.exists():
            result = blade_yolo_service.predict(full_path, record.turbine_id)
            algorithm_mode = "real_inference"
            real_inference_ran = True
            model_version = result.get("quality", {}).get("model_file", "unknown")
            diagnosis_type = result.get("damage_type", "no_damage")
            confidence = result.get("confidence", 0.0)
            bbox_data = result.get("damage_bbox")
            if bbox_data:
                bbox = [bbox_data.get(k, 0) for k in ("x", "y", "w", "h")]
            # Convert YOLO regions to defect list
            for region in result.get("damage_regions", []):
                defects.append({
                    "type": region.get("label", "unknown"),
                    "confidence": region.get("confidence", 0.0),
                    "bbox": list(region.get("bbox", {}).values()) if region.get("bbox") else [],
                    "severity": "moderate" if region.get("confidence", 0) > 0.7 else "minor",
                    "source": "blade_yolo_model_dtu",
                })
    except Exception as e:
        logger.warning("Real YOLO inference failed (model unavailable): %s", e)

    # 模型不可用时不臆造缺陷：如实返回 model_unavailable，由调用方决定是否补齐权重后重试。
    # （历史实现曾对特定风机注入固定的示例缺陷，会让演示数据与真实推理结果混淆，已移除。）
    if not real_inference_ran:
        diagnosis_type = "model_unavailable"
        confidence = 0.0
        defects = []
        bbox = None

    # ── Update record ──
    record.algorithm_mode = algorithm_mode
    record.model_version = model_version
    record.diagnosis_type = diagnosis_type
    record.diagnosis_confidence = confidence
    record.damage_bbox = bbox
    record.defects_detected = defects
    await db.commit()
    await db.refresh(record)

    payload = {
        "image_id": record.id,
        "algorithm_mode": algorithm_mode,
        "model_version": model_version,
        "diagnosis_type": diagnosis_type,
        "diagnosis_confidence": confidence,
        "damage_bbox": bbox,
        "defects_detected": defects,
        "data_source": record.data_source,
    }
    if not real_inference_ran:
        payload["message"] = "叶片检测模型不可用，本次未产生检测结论（不提供模拟结果）。请确认已放置 YOLO 权重后重试。"
    return payload


# ═══════════════════════════════════════════════════════════════════
# Evidence & Incident Linking (P0-2)
# ═══════════════════════════════════════════════════════════════════


@router.post("/images/{image_id}/link-evidence")
async def link_to_evidence(
    image_id: int,
    incident_id: Optional[int] = Query(None, description="Link to existing incident"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("engineer")),
):
    """Convert a defect-detected image into a typed EvidenceNode.

    Idempotent: if image already linked to evidence, returns existing node.
    If incident_id provided, links evidence to that incident.
    If defects found on >=2 images for same turbine, auto-creates incident.
    """
    record = await db.get(BladeImage, image_id)
    if not record:
        raise HTTPException(status_code=404, detail="Image not found")

    # Idempotency check
    if record.evidence_id:
        existing = await db.get(EvidenceNode, record.evidence_id)
        if existing:
            return {
                "evidence_id": existing.id,
                "label": existing.label,
                "image_id": image_id,
                "already_linked": True,
            }

    if record.diagnosis_type is None or record.diagnosis_confidence is None:
        raise HTTPException(status_code=400, detail="该图片尚未执行缺陷检测，请先执行缺陷检测后再关联证据")

    has_defect = record.diagnosis_type and record.diagnosis_type != "no_damage" and record.diagnosis_confidence > 0
    defects = record.defects_detected or []

    # Build evidence node
    evidence = EvidenceNode(
        incident_id=incident_id,  # May be None, will be linked later
        node_type="observation" if has_defect else "check",
        label=f"无人机巡检: {record.component or '叶片'} {record.inspection_angle or ''}",
        description=(
            f"算法模式: {record.algorithm_mode}\n"
            f"检测结果: {record.diagnosis_type} (置信度: {record.diagnosis_confidence:.2f})\n"
            f"缺陷数: {len(defects)}\n"
            f"数据来源: {record.data_source}\n"
            f"许可证: {record.data_license or '未标注'}"
        ),
        source="drone_inspection",
        confidence=record.diagnosis_confidence or 0.0,
        props={
            "image_id": record.id,
            "image_path": record.image_path,
            "algorithm_mode": record.algorithm_mode,
            "model_version": record.model_version,
            "defects": defects,
            "quality_passed": record.quality_passed,
            "data_source": record.data_source,
            "turbine_id": record.turbine_id,
            "component": record.component,
            "inspection_angle": record.inspection_angle,
        },
    )
    db.add(evidence)
    await db.flush()

    record.evidence_id = evidence.id
    await db.commit()
    await db.refresh(evidence)

    return {
        "evidence_id": evidence.id,
        "node_type": evidence.node_type,
        "label": evidence.label,
        "confidence": evidence.confidence,
        "image_id": image_id,
        "already_linked": False,
    }


@router.post("/missions/{mission_id}/create-incident")
async def create_incident_from_mission(
    mission_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("engineer")),
):
    """Create or link an Incident from a completed mission's evidence.

    Idempotent: if mission already has incident_id, returns existing.
    Links all unlinked evidence from this mission to the incident.
    """
    result = await db.execute(
        select(InspectionMission).where(InspectionMission.mission_id == mission_id)
    )
    mission = result.scalar_one_or_none()
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")

    # Idempotency
    if mission.incident_id:
        existing = await db.get(Incident, mission.incident_id)
        if existing:
            return {
                "incident_id": existing.incident_id,
                "mission_id": mission.mission_id,
                "already_exists": True,
            }

    # Get all evidence from this mission
    img_result = await db.execute(
        select(BladeImage).where(
            BladeImage.mission_id == mission.id,
            BladeImage.evidence_id.isnot(None),
        )
    )
    images_with_evidence = img_result.scalars().all()

    if not images_with_evidence:
        raise HTTPException(status_code=400, detail="No evidence images found — run quality check and defect detection first")

    # Check if any defect found
    has_defect = any(
        img.diagnosis_type and img.diagnosis_type != "no_damage"
        for img in images_with_evidence
    )

    turbine = await db.get(Turbine, mission.turbine_id)

    # Create incident
    inc_id = f"INC-{_utc_now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:4]}"
    incident = Incident(
        incident_id=inc_id,
        turbine_id=mission.turbine_id,
        title=f"无人机巡检发现: {turbine.name if turbine else ''} {mission.component}",
        severity="high" if has_defect else "medium",
        stage="detected",
        status="open",
        owner_id=user.id,
        summary=f"巡检任务 {mission.mission_id} 完成，{len(images_with_evidence)} 张照片经质量检查，"
                f"{'发现' if has_defect else '未发现'}缺陷。",
        opened_at=_utc_now(),
    )
    db.add(incident)
    await db.flush()

    # Link all evidence to incident
    for img in images_with_evidence:
        if img.evidence_id:
            ev = await db.get(EvidenceNode, img.evidence_id)
            if ev and ev.incident_id is None:
                ev.incident_id = incident.id

    mission.incident_id = incident.id
    await db.commit()
    await db.refresh(incident)

    return {
        "incident_id": incident.incident_id,
        "mission_id": mission.mission_id,
        "turbine_name": turbine.name if turbine else "",
        "has_defect": has_defect,
        "evidence_linked": len(images_with_evidence),
        "next_action": "前往事件指挥中心查看详情" if has_defect else "检查未发现缺陷，关闭或标记为检查通过",
    }


# ═══════════════════════════════════════════════════════════════════
# Missing angles / retake (P0-3)
# ═══════════════════════════════════════════════════════════════════

REQUIRED_ANGLES = ["leading_edge", "trailing_edge", "pressure_side", "suction_side", "tip_view"]


@router.get("/missions/{mission_id}/missing-angles")
async def get_missing_angles(
    mission_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Check which required inspection angles are missing for a mission."""
    result = await db.execute(
        select(InspectionMission).where(InspectionMission.mission_id == mission_id)
    )
    mission = result.scalar_one_or_none()
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")

    img_result = await db.execute(
        select(BladeImage.inspection_angle)
        .where(BladeImage.mission_id == mission.id)
        .distinct()
    )
    captured_angles = set(
        r[0] for r in img_result.fetchall() if r[0] is not None
    )

    missing = [a for a in REQUIRED_ANGLES if a not in captured_angles]
    retakes_needed = await db.execute(
        select(func.count(BladeImage.id)).where(
            BladeImage.mission_id == mission.id,
            BladeImage.retake_requested == True,
        )
    )
    retake_count = retakes_needed.scalar() or 0

    return {
        "mission_id": mission_id,
        "required_angles": REQUIRED_ANGLES,
        "captured_angles": sorted(captured_angles),
        "missing_angles": missing,
        "retakes_needed": retake_count,
        "evidence_complete": len(missing) == 0 and retake_count == 0,
        "recommendation": (
            "证据完整，可进行诊断"
            if len(missing) == 0 and retake_count == 0
            else f"缺失角度: {missing}，需补拍的角度: {len(missing)}"
        ),
    }
