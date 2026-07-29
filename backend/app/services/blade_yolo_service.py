"""YOLO blade inspection model integration.

Uses the DTU-trained weight imported from:
D:/MyCollege/软著归档-归档/WindBlade_System/core/best.pt
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import cv2


DATA_DIR = Path(__file__).resolve().parents[2] / "data"
MODEL_PATH = DATA_DIR / "models" / "windblade_dtu_yolo_best.pt"
OUTPUT_DIR = DATA_DIR / "model_outputs" / "blade_yolo"


CLASS_LABELS = {
    "damage": "叶片损伤",
    "dirt": "表面污垢",
}

# 权重文件里的类别名与系统内部规范名不完全一致（如权重用 Dirty/Damage，
# 内部规范名是 dirt/damage）。历史实现直接做 `== "dirt"` 精确匹配，
# 导致 Dirty 类别的检测结果被静默丢弃。这里用别名表做归一，
# 新增权重时只需在此登记，不必改判定逻辑。
CLASS_ALIASES = {
    "damage": "damage",
    "damaged": "damage",
    "defect": "damage",
    "crack": "damage",
    "erosion": "damage",
    "dirt": "dirt",
    "dirty": "dirt",
    "dust": "dirt",
    "soil": "dirt",
    "contamination": "dirt",
}


def _canonical_class(model_name: str) -> str:
    """把权重中的类别名归一为系统规范名；无法识别时返回空串。"""
    if not model_name:
        return ""
    name = model_name.strip().lower()
    if name in CLASS_ALIASES:
        return CLASS_ALIASES[name]
    # 兜底：按词根前缀匹配（覆盖 damage_area / dirty_surface 这类复合命名）
    for alias, canonical in CLASS_ALIASES.items():
        if name.startswith(alias):
            return canonical
    return ""


class BladeModelUnavailable(RuntimeError):
    """Raised when the local model cannot run in the current environment."""


def _iou(box1: list[int], box2: list[int]) -> float:
    x1, y1, x2, y2 = box1
    x3, y3, x4, y4 = box2
    inter_x1 = max(x1, x3)
    inter_y1 = max(y1, y3)
    inter_x2 = min(x2, x4)
    inter_y2 = min(y2, y4)
    inter_area = max(0, inter_x2 - inter_x1) * max(0, inter_y2 - inter_y1)
    area1 = max(0, x2 - x1) * max(0, y2 - y1)
    area2 = max(0, x4 - x3) * max(0, y4 - y3)
    union = area1 + area2 - inter_area
    return inter_area / union if union else 0.0


def _connected(a: dict[str, Any], b: dict[str, Any], iou_threshold: float = 0.01) -> bool:
    return _iou(a["bbox"], b["bbox"]) > iou_threshold


def _merge_detections(detections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(detections) <= 1:
        return [
            {
                "label": item["class"],
                "label_cn": CLASS_LABELS.get(item["class"], item["class"]),
                "confidence": item["confidence"],
                "bbox_xyxy": item["bbox_xyxy"],
            }
            for item in detections
        ]

    neighbors = {index: [] for index in range(len(detections))}
    for left in range(len(detections)):
        for right in range(left + 1, len(detections)):
            if _connected(detections[left], detections[right]):
                neighbors[left].append(right)
                neighbors[right].append(left)

    visited = [False] * len(detections)
    merged: list[dict[str, Any]] = []
    for start in range(len(detections)):
        if visited[start]:
            continue
        queue = [start]
        visited[start] = True
        cluster: list[int] = []
        while queue:
            current = queue.pop(0)
            cluster.append(current)
            for node in neighbors[current]:
                if not visited[node]:
                    visited[node] = True
                    queue.append(node)

        boxes = [detections[index] for index in cluster]
        class_name = Counter(box["class"] for box in boxes).most_common(1)[0][0]
        merged.append(
            {
                "label": class_name,
                "label_cn": CLASS_LABELS.get(class_name, class_name),
                "confidence": max(float(box["confidence"]) for box in boxes),
                "bbox_xyxy": [
                    min(box["bbox_xyxy"][0] for box in boxes),
                    min(box["bbox_xyxy"][1] for box in boxes),
                    max(box["bbox_xyxy"][2] for box in boxes),
                    max(box["bbox_xyxy"][3] for box in boxes),
                ],
            }
        )
    return merged


def _xyxy_to_xywh(box: list[int]) -> dict[str, int]:
    x1, y1, x2, y2 = box
    return {"x": x1, "y": y1, "w": max(0, x2 - x1), "h": max(0, y2 - y1)}


class BladeYoloService:
    def __init__(self, model_path: Path = MODEL_PATH):
        self.model_path = model_path
        self._model = None

    def is_model_available(self) -> bool:
        """Check if YOLO model weights and ultralytics are available.

        Used by multimodal_service and other callers to decide between
        real_inference and demo_fixture mode.
        """
        try:
            self._load_model()
            return True
        except BladeModelUnavailable:
            return False

    def _load_model(self):
        if self._model is not None:
            return self._model
        if not self.model_path.exists():
            raise BladeModelUnavailable(f"Blade YOLO weight not found: {self.model_path}")
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise BladeModelUnavailable("ultralytics/torch is not installed in backend venv.") from exc
        self._model = YOLO(str(self.model_path))
        return self._model

    def predict(self, image_path: Path, turbine_id: int, conf: float = 0.10) -> dict[str, Any]:
        if not image_path.exists():
            raise FileNotFoundError(str(image_path))

        model = self._load_model()
        results = model(str(image_path), conf=conf, iou=0.5, verbose=False)
        result = results[0]
        names = result.names

        raw: list[dict[str, Any]] = []
        unmapped: set[str] = set()
        for box in result.boxes:
            class_id = int(box.cls[0])
            model_name = str(names.get(class_id, "")).lower()
            label = _canonical_class(model_name)
            if not label:
                if model_name:
                    unmapped.add(model_name)
                continue
            xyxy = [int(value) for value in box.xyxy[0].tolist()]
            raw.append(
                {
                    "class": label,
                    "confidence": round(float(box.conf[0]), 4),
                    "bbox": xyxy,
                    "bbox_xyxy": xyxy,
                }
            )

        detections = _merge_detections(raw)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_path = OUTPUT_DIR / f"res_{image_path.name}"
        self._save_overlay(image_path, output_path, detections)

        main = max(detections, key=lambda item: item["confidence"], default=None)
        damage_type = main["label"] if main else "no_damage"
        confidence = round(float(main["confidence"]), 4) if main else 0.0
        bbox = _xyxy_to_xywh(main["bbox_xyxy"]) if main else None

        return {
            "turbine_id": turbine_id,
            "damage_type": damage_type,
            "confidence": confidence,
            "damage_bbox": bbox,
            "image_path": image_path.relative_to(DATA_DIR).as_posix() if image_path.is_relative_to(DATA_DIR) else str(image_path),
            "image_url": f"/data/{output_path.relative_to(DATA_DIR).as_posix()}",
            "severity": "warning" if damage_type == "dirt" else "fault" if damage_type == "damage" else "normal",
            "recommended_action": self._recommended_action(damage_type),
            "evidence": [
                f"{item['label_cn']} {item['confidence']:.2f}"
                for item in detections
            ],
            "quality": {
                "source_model": "WindBlade_System/core/best.pt",
                "source_dataset": "dtu_drone_inspection",
                "model_file": self.model_path.name,
                "raw_detection_count": len(raw),
                "merged_detection_count": len(detections),
                "model_class_names": sorted({str(v) for v in names.values()}) if names else [],
                "unmapped_classes": sorted(unmapped),
            },
            "algorithm_status": "windblade_dtu_yolo_inference",
            "message": "结果由本地 DTU 叶片巡检 YOLO 模型推理生成。",
            "damage_regions": [
                {
                    "label": item["label_cn"],
                    "bbox": _xyxy_to_xywh(item["bbox_xyxy"]),
                    "confidence": round(float(item["confidence"]), 4),
                }
                for item in detections
            ],
        }

    def _save_overlay(self, image_path: Path, output_path: Path, detections: list[dict[str, Any]]) -> None:
        image = cv2.imread(str(image_path))
        if image is None:
            return
        for det in detections:
            x1, y1, x2, y2 = det["bbox_xyxy"]
            color = (51, 51, 255) if det["label"] == "damage" else (51, 255, 255)
            cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
            cv2.putText(
                image,
                f"{det['label']} {det['confidence']:.2f}",
                (x1, max(14, y1 - 6)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                color,
                1,
                cv2.LINE_AA,
            )
        cv2.imwrite(str(output_path), image)

    @staticmethod
    def _recommended_action(damage_type: str) -> str:
        if damage_type == "damage":
            return "安排人工复核叶片损伤区域，并结合巡检记录确认维修优先级。"
        if damage_type == "dirt":
            return "记录表面污垢区域，结合发电效率和下次巡检计划决定是否清洗。"
        return "未检出模型支持的损伤或污垢目标。"


blade_yolo_service = BladeYoloService()
