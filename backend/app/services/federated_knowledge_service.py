"""Federated PHM knowledge sharing — privacy-preserving multi-farm learning.

【状态】演示级模拟（`mode = "simulation"`）：三个参与风场为**进程内模拟实例**，
数据保存在内存中，**服务重启即清零**，farms 之间也不存在真实网络边界。
本模块用于验证联邦知识共享协议的流程（共享→下载→本地回测→接受/冲突→撤回，
以及差分隐私加噪），**并非真实的多方部署**，其统计结果不可作为跨场实证结论。

Three isolated simulated wind farm instances:
- NO raw SCADA exchange
- Share pattern-validated knowledge summaries or model statistics only
- Sample-size-weighted aggregation
- Conflicting knowledge detection
- Local back-test before acceptance
- Version, source, and withdrawal tracking

If differential privacy is implemented:
- Uses correct Laplace/Gaussian mechanism (NOT "add a little random noise")
- Records epsilon/delta
- Shows privacy-utility tradeoff
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class KnowledgeStatus(str, Enum):
    DRAFT = "draft"
    SHARED = "shared"        # Published to federation hub
    RECEIVED = "received"    # Downloaded by other farm
    BACKTESTED = "backtested"  # Passed local validation
    ACCEPTED = "accepted"     # Integrated into local knowledge
    REJECTED = "rejected"     # Failed back-test
    WITHDRAWN = "withdrawn"  # Retracted by source farm
    CONFLICT = "conflict"     # Conflicts with existing local knowledge


@dataclass
class KnowledgeFragment:
    """One shareable knowledge fragment (NO raw SCADA data)."""
    fragment_id: str = field(default_factory=lambda: f"FK-{uuid.uuid4().hex[:8]}")
    source_farm_id: str = ""     # Which farm shared this
    fault_type: str = ""
    category: str = ""           # pattern / threshold / rule / statistic
    content: dict[str, Any] = field(default_factory=dict)
    sample_size: int = 0         # How many cases support this
    confidence: float = 0.5
    # Statistical summary (NOT raw data)
    summary_stats: dict[str, Any] = field(default_factory=dict)
    # Version tracking
    version: int = 1
    previous_version_id: str = ""
    # Differential privacy (if applied)
    dp_applied: bool = False
    dp_epsilon: Optional[float] = None
    dp_delta: Optional[float] = None
    dp_mechanism: str = ""       # Laplace / Gaussian / None
    # Metadata
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: KnowledgeStatus = KnowledgeStatus.DRAFT
    content_hash: str = ""


@dataclass
class FarmInstance:
    """One simulated wind farm instance."""
    farm_id: str = ""
    farm_name: str = ""
    turbine_count: int = 10
    region: str = ""
    local_knowledge: list[KnowledgeFragment] = field(default_factory=list)
    shared_knowledge: list[KnowledgeFragment] = field(default_factory=list)
    accepted_external: list[KnowledgeFragment] = field(default_factory=list)


@dataclass
class FederationHub:
    """Central knowledge coordination hub (simulated)."""
    hub_id: str = "FED-HUB-001"
    farms: dict[str, FarmInstance] = field(default_factory=dict)
    shared_registry: list[KnowledgeFragment] = field(default_factory=list)
    conflict_log: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class FederatedKnowledgeResult:
    """Result of a federated knowledge operation."""
    operation: str = ""
    success: bool = False
    message: str = ""
    fragment_id: str = ""
    conflicts_detected: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class FederatedKnowledgeService:
    """Federated PHM knowledge sharing across isolated wind farms.

    Each farm maintains its own knowledge base. Only pattern-validated
    summaries (statistics, rules, thresholds) are shared — NEVER raw SCADA.
    """

    def __init__(self):
        self.hub = FederationHub()
        self._init_farms()

    def _init_farms(self) -> None:
        """Initialize three simulated wind farms with local knowledge."""
        farms = [
            FarmInstance(
                farm_id="FARM-A", farm_name="东海风场 (Donghai Wind Farm)",
                turbine_count=30, region="Jiangsu",
                local_knowledge=[
                    self._make_local_knowledge("FARM-A", "bearing_wear",
                        {"vibration_threshold": 7.1, "temperature_threshold": 75.0}, 45),
                    self._make_local_knowledge("FARM-A", "gear_pitting",
                        {"meshing_freq_sideband_threshold": 0.15, "oil_debris_threshold": 120}, 32),
                ],
            ),
            FarmInstance(
                farm_id="FARM-B", farm_name="西北风场 (Xibei Wind Farm)",
                turbine_count=25, region="Gansu",
                local_knowledge=[
                    self._make_local_knowledge("FARM-B", "bearing_wear",
                        {"vibration_threshold": 6.8, "temperature_threshold": 72.0}, 38),
                    self._make_local_knowledge("FARM-B", "blade_erosion",
                        {"leading_edge_wear_rate": 0.03, "power_loss_pct": 2.5}, 20),
                ],
            ),
            FarmInstance(
                farm_id="FARM-C", farm_name="南部风场 (Nanbu Wind Farm)",
                turbine_count=20, region="Guangdong",
                local_knowledge=[
                    self._make_local_knowledge("FARM-C", "bearing_wear",
                        {"vibration_threshold": 7.5, "temperature_threshold": 78.0}, 28),
                    self._make_local_knowledge("FARM-C", "cooling_fault",
                        {"coolant_flow_threshold": 0.7, "temp_rise_rate": 2.5}, 15),
                ],
            ),
        ]
        for farm in farms:
            self.hub.farms[farm.farm_id] = farm

    def _make_local_knowledge(
        self, farm_id: str, fault_type: str, params: dict, sample_size: int
    ) -> KnowledgeFragment:
        frag = KnowledgeFragment(
            source_farm_id=farm_id,
            fault_type=fault_type,
            category="threshold",
            content=params,
            sample_size=sample_size,
            confidence=min(0.9, 0.5 + sample_size / 100),
            summary_stats={
                "mean": {k: v for k, v in params.items()},
                "sample_size": sample_size,
                "region": self.hub.farms[farm_id].region if farm_id in self.hub.farms else "",
            },
            status=KnowledgeStatus.DRAFT,
        )
        frag.content_hash = self._hash_content(frag.content)
        return frag

    # ── Federation operations ──

    def share_knowledge(
        self, farm_id: str, fragment: KnowledgeFragment
    ) -> FederatedKnowledgeResult:
        """Share a knowledge fragment from a farm to the federation hub.

        Only summary statistics are shared — NEVER raw data.
        Optionally applies differential privacy.
        """
        farm = self.hub.farms.get(farm_id)
        if farm is None:
            return FederatedKnowledgeResult(
                operation="share", success=False,
                message=f"Farm {farm_id} not found",
            )

        fragment.source_farm_id = farm_id
        fragment.status = KnowledgeStatus.SHARED
        fragment.content_hash = self._hash_content(fragment.content)
        fragment.created_at = datetime.now(timezone.utc)

        farm.shared_knowledge.append(fragment)
        self.hub.shared_registry.append(fragment)

        return FederatedKnowledgeResult(
            operation="share", success=True,
            fragment_id=fragment.fragment_id,
            message=f"Knowledge fragment {fragment.fragment_id} shared from {farm_id}",
        )

    def download_knowledge(
        self, target_farm_id: str
    ) -> list[KnowledgeFragment]:
        """Download available knowledge from federation hub to a farm.

        Only fragments NOT from the requesting farm are returned.
        Farm must back-test before integrating.
        """
        farm = self.hub.farms.get(target_farm_id)
        if farm is None:
            return []

        available = [
            f for f in self.hub.shared_registry
            if f.source_farm_id != target_farm_id
            and f.status not in (KnowledgeStatus.WITHDRAWN, KnowledgeStatus.REJECTED)
        ]

        for frag in available:
            frag.status = KnowledgeStatus.RECEIVED

        return available

    def backtest_and_accept(
        self, farm_id: str, fragment_id: str
    ) -> FederatedKnowledgeResult:
        """Back-test received knowledge against local data before accepting.

        In production: replay historical incidents to validate.
        Here: simulated validation with conflict detection.
        """
        farm = self.hub.farms.get(farm_id)
        if farm is None:
            return FederatedKnowledgeResult(
                operation="backtest", success=False,
                message=f"Farm {farm_id} not found",
            )

        # Find fragment
        frag = None
        for f in self.hub.shared_registry:
            if f.fragment_id == fragment_id:
                frag = f
                break

        if frag is None:
            return FederatedKnowledgeResult(
                operation="backtest", success=False,
                message=f"Fragment {fragment_id} not found",
            )

        # Detect conflicts with existing local knowledge
        conflicts = self._detect_conflicts(frag, farm.local_knowledge)

        if conflicts:
            frag.status = KnowledgeStatus.CONFLICT
            self.hub.conflict_log.append({
                "fragment_id": fragment_id,
                "source_farm": frag.source_farm_id,
                "target_farm": farm_id,
                "conflicts": conflicts,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return FederatedKnowledgeResult(
                operation="backtest", success=False,
                fragment_id=fragment_id,
                conflicts_detected=len(conflicts),
                message=f"Conflict detected: {conflicts[0] if conflicts else 'unknown'}",
            )

        # Accept
        frag.status = KnowledgeStatus.ACCEPTED
        farm.accepted_external.append(frag)

        return FederatedKnowledgeResult(
            operation="backtest", success=True,
            fragment_id=fragment_id,
            message=f"Fragment {fragment_id} accepted by {farm_id} after back-test",
        )

    def withdraw_knowledge(
        self, farm_id: str, fragment_id: str
    ) -> FederatedKnowledgeResult:
        """Withdraw previously shared knowledge (e.g., found to be incorrect)."""
        for frag in self.hub.shared_registry:
            if frag.fragment_id == fragment_id and frag.source_farm_id == farm_id:
                frag.status = KnowledgeStatus.WITHDRAWN
                return FederatedKnowledgeResult(
                    operation="withdraw", success=True,
                    fragment_id=fragment_id,
                    message=f"Fragment {fragment_id} withdrawn by {farm_id}",
                )
        return FederatedKnowledgeResult(
            operation="withdraw", success=False,
            message=f"Fragment {fragment_id} not found or not owned by {farm_id}",
        )

    def aggregate_knowledge(
        self, fault_type: str
    ) -> dict[str, Any]:
        """Aggregate shared knowledge about a fault type across all farms.

        Uses sample-size-weighted mean for numerical parameters.
        Detects conflicting thresholds across farms.
        """
        relevant = [
            f for f in self.hub.shared_registry
            if f.fault_type == fault_type
            and f.status in (KnowledgeStatus.SHARED, KnowledgeStatus.ACCEPTED)
        ]

        if not relevant:
            return {"fault_type": fault_type, "farms_contributing": 0, "message": "No shared knowledge"}

        # Collect all numerical parameters
        all_params: dict[str, list[tuple[float, int]]] = {}
        for frag in relevant:
            for key, val in frag.content.items():
                if isinstance(val, (int, float)):
                    all_params.setdefault(key, []).append((float(val), frag.sample_size))

        # Weighted mean aggregation
        aggregated: dict[str, Any] = {}
        for key, vals in all_params.items():
            total_weight = sum(w for _, w in vals)
            if total_weight > 0:
                weighted_mean = sum(v * w for v, w in vals) / total_weight
                aggregated[key] = round(weighted_mean, 3)
                # Check variance — high variance = potential conflict
                mean = weighted_mean
                variance = sum(w * (v - mean) ** 2 for v, w in vals) / total_weight if total_weight > 0 else 0
                if variance > mean * 0.1:  # CV > ~30%
                    aggregated[f"{key}_high_variance_warning"] = f"CV={variance**0.5/mean:.0%}"

        return {
            "fault_type": fault_type,
            "farms_contributing": len(set(f.source_farm_id for f in relevant)),
            "total_fragments": len(relevant),
            "total_sample_size": sum(f.sample_size for f in relevant),
            "aggregated_params": aggregated,
            "aggregation_method": "sample_size_weighted_mean",
        }

    def get_federation_status(self) -> dict[str, Any]:
        """Get overall federation hub status.

        ``mode`` is always ``"simulation"``: the farms are in-process instances,
        not real remote participants (see module docstring).
        """
        farms_status = []
        for fid, farm in self.hub.farms.items():
            farms_status.append({
                "farm_id": fid,
                "farm_name": farm.farm_name,
                "turbine_count": farm.turbine_count,
                "local_knowledge_count": len(farm.local_knowledge),
                "shared_count": len(farm.shared_knowledge),
                "accepted_external_count": len(farm.accepted_external),
            })

        return {
            "hub_id": self.hub.hub_id,
            "mode": "simulation",
            "mode_note": (
                "三个参与风场为进程内模拟实例，重启清零；"
                "用于验证联邦共享协议流程，非真实多方部署。"
            ),
            "total_farms": len(self.hub.farms),
            "total_shared_fragments": len(self.hub.shared_registry),
            "total_conflicts": len(self.hub.conflict_log),
            "farms": farms_status,
            "conflicts": self.hub.conflict_log[-5:],  # Last 5
        }

    def apply_differential_privacy(
        self,
        fragment: KnowledgeFragment,
        epsilon: float = 1.0,
        delta: float = 1e-5,
        mechanism: str = "laplace",
    ) -> KnowledgeFragment:
        """Apply differential privacy to numerical parameters.

        Uses CORRECT Laplace or Gaussian mechanism — NOT "add a little noise."
        """
        import numpy as np

        sensitivity = 1.0  # Assume each parameter has sensitivity 1

        noised_content = {}
        for key, val in fragment.content.items():
            if isinstance(val, (int, float)):
                if mechanism == "laplace":
                    scale = sensitivity / epsilon
                    noise = np.random.laplace(0, scale)
                elif mechanism == "gaussian":
                    # Gaussian: sigma = sqrt(2*ln(1.25/delta)) * sensitivity / epsilon
                    sigma = np.sqrt(2 * np.log(1.25 / delta)) * sensitivity / epsilon
                    noise = np.random.normal(0, sigma)
                else:
                    noise = 0
                noised_content[key] = round(val + noise, 3)
            else:
                noised_content[key] = val

        fragment.content = noised_content
        fragment.dp_applied = True
        fragment.dp_epsilon = epsilon
        fragment.dp_delta = delta
        fragment.dp_mechanism = mechanism
        fragment.content_hash = self._hash_content(fragment.content)

        return fragment

    # ── Helpers ──

    def _detect_conflicts(
        self,
        incoming: KnowledgeFragment,
        local: list[KnowledgeFragment],
    ) -> list[str]:
        """Detect conflicts between incoming and local knowledge."""
        conflicts: list[str] = []
        for local_frag in local:
            if local_frag.fault_type != incoming.fault_type:
                continue
            # Check if same parameter has significantly different threshold
            for key in set(incoming.content.keys()) & set(local_frag.content.keys()):
                inc_val = incoming.content[key]
                loc_val = local_frag.content[key]
                if isinstance(inc_val, (int, float)) and isinstance(loc_val, (int, float)):
                    if loc_val != 0 and abs(inc_val - loc_val) / abs(loc_val) > 0.2:
                        conflicts.append(
                            f"{key}: incoming={inc_val}, local={loc_val} "
                            f"(diff={abs(inc_val - loc_val) / abs(loc_val):.0%})"
                        )
        return conflicts

    @staticmethod
    def _hash_content(content: dict[str, Any]) -> str:
        import json
        return hashlib.sha256(
            json.dumps(content, sort_keys=True, default=str).encode()
        ).hexdigest()[:16]
