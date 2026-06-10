"""Blade image simulator.

Generates synthetic wind turbine blade inspection imagery with labeled defects
(cracks, erosion, delamination, dirt/contamination).

In production, this would be replaced by a YOLOv8 model trained on real blade images.
"""

from datetime import datetime, timezone
from pathlib import Path
import random


DATA_DIR = Path(__file__).parent.parent.parent.parent / "data"
BLADE_DIR = DATA_DIR / "blade_images"

DAMAGE_TYPES = ["crack", "erosion", "delamination", "dirt", "lightning_damage", "leading_edge_wear"]


class BladeImageSimulator:
    """Generate synthetic blade inspection data for testing and demo."""

    def __init__(self):
        BLADE_DIR.mkdir(parents=True, exist_ok=True)
        self._image_index = 0

    def generate_inspection(
        self, turbine_id: int, num_images: int = 3
    ) -> list[dict]:
        """Generate simulated blade inspection results."""
        results = []
        now = datetime.now(timezone.utc)
        views = ["前缘", "迎风面", "背风面", "叶根", "叶尖"]

        for i in range(num_images):
            has_damage = random.random() < 0.25
            dmg_type = random.choice(DAMAGE_TYPES) if has_damage else None
            confidence = random.uniform(0.82, 0.96) if has_damage else random.uniform(0.90, 0.99)

            self._image_index += 1
            image_name = f"turbine_{turbine_id:03d}_blade_{self._image_index:04d}.png"

            result = {
                "id": self._image_index,
                "turbine_id": turbine_id,
                "image_path": str(BLADE_DIR / image_name),
                "view": random.choice(views),
                "timestamp": now.isoformat(),
                "has_damage": has_damage,
                "damage_type": dmg_type,
                "confidence": round(confidence, 3),
                "damage_bbox": {
                    "x": random.randint(20, 1800),
                    "y": random.randint(30, 1400),
                    "w": random.randint(24, 128),
                    "h": random.randint(16, 96),
                } if has_damage else None,
                "damage_severity": random.choice(["minor", "moderate", "severe"]) if has_damage else None,
                "recommended_action": self._get_recommendation(dmg_type) if has_damage else "无需处理",
                "data_source": "simulated",
                "note": "叶片图像为模拟数据，真实图像数据集待接入",
            }
            results.append(result)
        return results

    @staticmethod
    def _get_recommendation(damage_type: str) -> str:
        recommendations = {
            "crack": "建议2周内安排无人机复检，监测裂纹扩展",
            "erosion": "建议季度巡检时打磨修复",
            "delamination": "建议1个月内安排停机检查",
            "dirt": "建议下次定检时清洗",
            "lightning_damage": "建议立即停机检查，评估结构损伤",
            "leading_edge_wear": "建议年度维护时更换前缘保护膜",
        }
        return recommendations.get(damage_type, "建议安排人工巡检确认")


blade_simulator = BladeImageSimulator()
