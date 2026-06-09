import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from PIL import Image, UnidentifiedImageError

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
            payload["diagnosis"] = _vibration_diagnosis(payload)
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


def _dataset_id_from_path(image_path: str) -> str | None:
    parts = image_path.replace("\\", "/").split("/")
    if len(parts) >= 2 and parts[0] == "blade_images":
        return parts[1]
    if len(parts) >= 1:
        return parts[0]
    return None


def _raw_bbox(image: BladeImage) -> dict:
    return image.damage_bbox if isinstance(image.damage_bbox, dict) else {}


def _bbox_geometry(raw_bbox: dict) -> dict | None:
    if all(k in raw_bbox for k in ("x", "y", "w", "h")):
        return {
            "x": int(raw_bbox["x"]),
            "y": int(raw_bbox["y"]),
            "w": int(raw_bbox["w"]),
            "h": int(raw_bbox["h"]),
        }
    return None


def _image_file_info(image_path: str) -> dict:
    path = DATA_DIR / image_path
    if not path.exists():
        return {"file_exists": False, "resolution": None, "width": None, "height": None}
    try:
        with Image.open(path) as img:
            width, height = img.size
        return {
            "file_exists": True,
            "resolution": f"{width}x{height}",
            "width": width,
            "height": height,
        }
    except (OSError, UnidentifiedImageError):
        return {"file_exists": False, "resolution": None, "width": None, "height": None}


def _bbox_status(raw_bbox: dict, file_info: dict) -> str:
    geometry = _bbox_geometry(raw_bbox)
    if not geometry:
        return "not_available"
    if geometry["w"] <= 0 or geometry["h"] <= 0:
        return "invalid_geometry"
    width = file_info.get("width") or raw_bbox.get("image_width")
    height = file_info.get("height") or raw_bbox.get("image_height")
    if width and height:
        inside = (
            0 <= geometry["x"] < width
            and 0 <= geometry["y"] < height
            and geometry["x"] + geometry["w"] <= width
            and geometry["y"] + geometry["h"] <= height
        )
        return "valid" if inside else "out_of_bounds"
    return "unchecked_no_resolution"


def _damage_label(damage_type: str | None) -> str:
    return DAMAGE_LABELS.get(damage_type or "no_damage", damage_type or "未检出损伤")


def _damage_severity(damage_type: str | None, confidence: float | None) -> str:
    if not damage_type or damage_type == "no_damage":
        return "normal"
    if confidence is None:
        return "requires_review"
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
    raw_bbox = _raw_bbox(image)
    file_info = _image_file_info(image.image_path)
    bbox_status = _bbox_status(raw_bbox, file_info)
    if not file_info["file_exists"]:
        quality_grade = "missing_file"
        note = "数据库存在图像记录，但磁盘上的真实图片文件未找到，需重新导入数据集。"
    elif bbox_status in {"invalid_geometry", "out_of_bounds"}:
        quality_grade = "needs_review"
        note = "图像文件存在，但标注框几何校验未通过，需要回到原始数据集核对。"
    elif image.diagnosis_confidence is None:
        quality_grade = "usable_annotation"
        note = "图像文件和公开标注可用；该标注未提供模型置信度。"
    else:
        quality_grade = "usable_model_output"
        note = "图像文件、标注框和模型置信度字段均来自导入记录。"

    return {
        "quality_grade": quality_grade,
        "resolution": file_info["resolution"],
        "file_exists": file_info["file_exists"],
        "bbox_status": bbox_status,
        "bbox_validated": bbox_status == "valid" if _bbox_geometry(raw_bbox) else None,
        "label_source": raw_bbox.get("label_source", "not_recorded"),
        "source_dataset": raw_bbox.get("source_dataset") or _dataset_id_from_path(image.image_path),
        "source_file": raw_bbox.get("source_file") or image.image_path,
        "confidence_source": "model_or_dataset_score" if image.diagnosis_confidence is not None else "not_available_in_public_annotation",
        "data_quality_note": note,
    }


def _blade_image_response(image: BladeImage) -> dict:
    damage_type = image.diagnosis_type or "no_damage"
    raw_bbox = _raw_bbox(image)
    bbox = _bbox_geometry(raw_bbox)
    confidence = image.diagnosis_confidence
    return {
        "id": image.id,
        "turbine_id": image.turbine_id,
        "image_path": image.image_path,
        "image_url": _image_url(image.image_path),
        "view": "叶片巡检",
        "timestamp": image.timestamp.isoformat(),
        "has_damage": damage_type not in {"no_damage", "unknown"},
        "damage_type": damage_type,
        "damage_label": _damage_label(damage_type),
        "confidence": confidence,
        "damage_bbox": bbox,
        "damage_severity": _damage_severity(damage_type, confidence),
        "recommended_action": _damage_recommendation(damage_type),
        "quality": _image_quality(image),
        "data_source": "real_dataset",
    }


def _blade_diagnosis_response(image: BladeImage) -> BladeDiagnosisResponse:
    item = _blade_image_response(image)
    evidence = [
        f"数据集={item['quality'].get('source_dataset') or '未记录'}",
        f"标注来源={item['quality'].get('label_source') or '未记录'}",
        f"图像质量状态={item['quality']['quality_grade']}",
    ]
    if item["quality"].get("resolution"):
        evidence.append(f"真实图像分辨率={item['quality']['resolution']}")
    if item["confidence"] is None:
        evidence.append("公开标注未提供模型置信度")
    else:
        evidence.append(f"置信度字段={item['confidence']:.1%}")
    if item["damage_bbox"]:
        evidence.append(
            f"检测区域 x={item['damage_bbox']['x']}, y={item['damage_bbox']['y']}, "
            f"w={item['damage_bbox']['w']}, h={item['damage_bbox']['h']}"
        )
        evidence.append(
            "检测框通过边界校验" if item["quality"]["bbox_validated"] else "检测框需人工复核"
        )
    else:
        evidence.append("该记录未提供检测框几何信息")

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


def _vibration_diagnosis(payload: dict) -> dict:
    fault_info = payload.get("fault_info") or {}
    quality = payload.get("quality") or {}
    peaks = payload.get("peak_frequencies") or []
    fault_detected = bool(payload.get("fault_detected"))
    label = fault_info.get("type") or quality.get("source_label")
    label_source = fault_info.get("label_source") or quality.get("label_source") or "not_recorded"

    evidence = [
        f"数据集={quality.get('source_dataset') or '未记录'}",
        f"源文件={quality.get('source_file') or '未记录'}",
        f"样本数={payload.get('sample_count', '未记录')}",
        f"采样率={payload.get('sample_rate_hz', '未记录')} Hz",
    ]
    if quality.get("source_channel"):
        evidence.append(f"通道={quality['source_channel']}")
    if quality.get("completeness_pct") is not None:
        evidence.append(f"完整率={quality['completeness_pct']}%")
    if payload.get("rms") is not None:
        evidence.append(f"RMS={payload['rms']}")
    if peaks:
        top = peaks[0]
        evidence.append(f"主峰频率={top.get('frequency_hz')} Hz，幅值={top.get('amplitude')}")
    if label:
        evidence.append(f"源数据标签={label}，标签来源={label_source}")
    else:
        evidence.append("源数据未提供明确故障标签")

    if fault_detected:
        status = "source_labeled_fault"
        summary = f"导入记录标记为故障样本：{label or '未命名故障'}。"
        action = "将该样本作为演示诊断证据使用；工程决策前需结合现场工况、传感器位置和人工复核。"
    else:
        status = "source_labeled_normal"
        summary = "导入记录标记为健康或正常样本。"
        action = "可作为健康基线样本展示；不应据此推断现场风机当前无故障。"

    return {
        "status": status,
        "summary": summary,
        "label": label,
        "label_source": label_source,
        "confidence": None,
        "evidence": evidence,
        "recommended_action": action,
    }
