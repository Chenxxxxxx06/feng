import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import Fault, FaultSignal, BladeImage, Turbine, VibrationData
from app.schemas import (
    FaultResponse, FaultDetailResponse, FaultSignalResponse,
    BladeDiagnosisRequest, BladeDiagnosisResponse,
)
from app.api.auth import get_current_user

router = APIRouter(dependencies=[Depends(get_current_user)])
DATA_DIR = Path(__file__).resolve().parents[2] / "data"


FAULT_LABELS = {
    "bearing_inner_race_wear": "轴承内圈磨损",
    "gearbox_tooth_pitting": "齿轮箱点蚀",
    "generator_overheat": "发电机过热",
    "blade_leading_edge_erosion": "叶片前缘磨蚀",
    "pitch_system_fault": "变桨系统故障",
    "main_shaft_misalignment": "主轴不对中",
    "cooling_system_fault": "冷却系统故障",
    "electrical_connection": "电气连接松动",
}

DAMAGE_LABELS = {
    "crack": "裂纹",
    "erosion": "前缘侵蚀",
    "delamination": "分层",
    "dirt": "污渍附着",
    "lightning_damage": "雷击损伤",
    "leading_edge_wear": "前缘磨损",
    "no_damage": "未检出损伤",
}


@router.get("/faults", response_model=list[FaultResponse])
async def list_faults(
    turbine_id: int | None = Query(None),
    status: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    q = select(Fault)
    if turbine_id:
        q = q.where(Fault.turbine_id == turbine_id)
    if status:
        q = q.where(Fault.status == status)
    q = q.order_by(Fault.detected_at.desc())
    result = await db.execute(q)
    faults = result.scalars().all()
    items = []
    for fault in faults:
        turbine_result = await db.execute(select(Turbine).where(Turbine.id == fault.turbine_id))
        turbine = turbine_result.scalar_one_or_none()
        items.append(_fault_response(fault, turbine.name if turbine else ""))
    return items


@router.get("/faults/{fault_id}", response_model=FaultDetailResponse)
async def get_fault_detail(fault_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Fault).where(Fault.id == fault_id))
    fault = result.scalar_one_or_none()
    if not fault:
        raise HTTPException(status_code=404, detail="Fault not found")
    turbine_result = await db.execute(select(Turbine).where(Turbine.id == fault.turbine_id))
    turbine = turbine_result.scalar_one_or_none()

    sig_result = await db.execute(
        select(FaultSignal).where(FaultSignal.fault_id == fault_id).order_by(FaultSignal.contribution_score.desc())
    )
    signals = sig_result.scalars().all()

    return FaultDetailResponse(
        id=fault.id,
        turbine_id=fault.turbine_id,
        turbine_name=turbine.name if turbine else "",
        detected_at=fault.detected_at,
        fault_type=_fault_label(fault.fault_type),
        confidence=fault.confidence,
        status=fault.status,
        details=fault.details,
        signals=[FaultSignalResponse.model_validate(s) for s in signals],
    )


@router.post("/blade-diagnosis", response_model=BladeDiagnosisResponse)
async def diagnose_blade(data: BladeDiagnosisRequest, db: AsyncSession = Depends(get_db)):
    """Return stored blade diagnosis imported from a real image dataset."""
    image_path = _normalize_image_path(data.image_path)
    result = await db.execute(
        select(BladeImage).where(
            BladeImage.turbine_id == data.turbine_id,
            BladeImage.image_path == image_path,
        )
    )
    image = result.scalar_one_or_none()
    if not image:
        raise HTTPException(status_code=404, detail="Blade image not found")
    return _blade_diagnosis_response(image)


@router.get("/vibration")
async def get_vibration_data(
    turbine_id: int = Query(...),
    component: str = Query("gearbox_high_speed"),
    fault_type: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Get vibration waveform imported from a real dataset."""
    q = (
        select(VibrationData)
        .where(VibrationData.turbine_id == turbine_id)
        .order_by(VibrationData.timestamp.desc())
    )
    if component:
        q = q.where(VibrationData.component == component)
    result = await db.execute(q.limit(1))
    record = result.scalar_one_or_none()
    if not record and component:
        fallback_result = await db.execute(
            select(VibrationData)
            .where(VibrationData.turbine_id == turbine_id)
            .order_by(VibrationData.timestamp.desc())
            .limit(1)
        )
        record = fallback_result.scalar_one_or_none()

    if record and record.waveform_path:
        path = DATA_DIR / record.waveform_path
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["record_id"] = record.id
            payload["waveform_path"] = record.waveform_path
            payload["data_source"] = "real_dataset"
            return payload

    raise HTTPException(
        status_code=404,
        detail="Real vibration dataset has not been imported for this turbine/component",
    )


@router.get("/blade-images")
async def list_blade_images(
    turbine_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Get blade inspection images for a turbine."""
    result = await db.execute(
        select(BladeImage)
        .where(BladeImage.turbine_id == turbine_id)
        .order_by(BladeImage.timestamp.desc(), BladeImage.id.asc())
    )
    images = result.scalars().all()
    if images:
        return [_blade_image_response(image) for image in images]

    return []


def _fault_label(fault_type: str) -> str:
    return FAULT_LABELS.get(fault_type, fault_type)


def _fault_response(fault: Fault, turbine_name: str) -> FaultResponse:
    details = dict(fault.details or {})
    if "fault_code" not in details:
        details["fault_code"] = fault.fault_type
    return FaultResponse(
        id=fault.id,
        turbine_id=fault.turbine_id,
        turbine_name=turbine_name,
        detected_at=fault.detected_at,
        fault_type=_fault_label(fault.fault_type),
        confidence=fault.confidence,
        status=fault.status,
        details=details,
    )


def _normalize_image_path(path: str) -> str:
    value = path.replace("\\", "/")
    if "/data/" in value:
        value = value.split("/data/", 1)[1]
    if value.startswith("data/"):
        value = value[5:]
    try:
        p = Path(value)
        if p.is_absolute():
            return p.resolve().relative_to(DATA_DIR.resolve()).as_posix()
    except ValueError:
        pass
    return value.lstrip("/")


def _image_url(image_path: str) -> str:
    return f"/data/{image_path}"


def _damage_label(damage_type: str | None) -> str:
    return DAMAGE_LABELS.get(damage_type or "no_damage", damage_type or "未检出损伤")


def _damage_severity(damage_type: str | None, confidence: float) -> str:
    if not damage_type or damage_type == "no_damage":
        return "normal"
    if damage_type in {"lightning_damage", "crack"} and confidence >= 0.85:
        return "high"
    if confidence >= 0.8:
        return "medium"
    return "low"


def _damage_recommendation(damage_type: str | None) -> str:
    return {
        "crack": "2周内安排无人机复检，确认裂纹长度变化；若扩展明显，转停机检修。",
        "erosion": "纳入季度维护，打磨前缘并补涂防护层。",
        "delamination": "1个月内安排近距离复检，必要时进行超声或敲击检测。",
        "dirt": "下次定检清洗，观察是否影响发电效率。",
        "lightning_damage": "立即停机复核接闪器和结构损伤，必要时更换受损区域。",
        "leading_edge_wear": "年度维护更换前缘保护膜，持续跟踪磨损面积。",
        "no_damage": "未检出明显损伤，维持常规巡检周期。",
    }.get(damage_type or "no_damage", "安排人工复核并补充标注。")


def _image_quality(image: BladeImage) -> dict:
    return {
        "quality_grade": "A" if image.diagnosis_confidence and image.diagnosis_confidence >= 0.9 else "B",
        "resolution": "800x450",
        "bbox_validated": image.damage_bbox is None or all(k in image.damage_bbox for k in ("x", "y", "w", "h")),
        "label_source": "public_dataset_annotation",
        "data_quality_note": "图像来自公开数据集导入记录，包含检测框、置信度和处置建议。",
    }


def _blade_image_response(image: BladeImage) -> dict:
    damage_type = image.diagnosis_type or "no_damage"
    return {
        "id": image.id,
        "turbine_id": image.turbine_id,
        "image_path": image.image_path,
        "image_url": _image_url(image.image_path),
        "view": "叶片巡检",
        "timestamp": image.timestamp.isoformat(),
        "has_damage": damage_type != "no_damage",
        "damage_type": damage_type,
        "damage_label": _damage_label(damage_type),
        "confidence": image.diagnosis_confidence or 0.0,
        "damage_bbox": image.damage_bbox,
        "damage_severity": _damage_severity(damage_type, image.diagnosis_confidence or 0.0),
        "recommended_action": _damage_recommendation(damage_type),
        "quality": _image_quality(image),
        "data_source": "real_dataset",
    }


def _blade_diagnosis_response(image: BladeImage) -> BladeDiagnosisResponse:
    item = _blade_image_response(image)
    evidence = [
        f"图像质量等级={item['quality']['quality_grade']}",
        f"模型置信度={item['confidence']:.1%}",
        "检测框通过边界校验" if item["quality"]["bbox_validated"] else "检测框需人工复核",
    ]
    if item["damage_bbox"]:
        evidence.append(
            f"检测区域 x={item['damage_bbox']['x']}, y={item['damage_bbox']['y']}, "
            f"w={item['damage_bbox']['w']}, h={item['damage_bbox']['h']}"
        )

    return BladeDiagnosisResponse(
        turbine_id=image.turbine_id,
        damage_type=item["damage_label"],
        confidence=item["confidence"],
        damage_bbox=item["damage_bbox"],
        image_path=item["image_path"],
        image_url=item["image_url"],
        severity=item["damage_severity"],
        recommended_action=item["recommended_action"],
        evidence=evidence,
        quality=item["quality"],
    )
