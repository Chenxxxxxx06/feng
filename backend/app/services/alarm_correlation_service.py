"""Alarm correlation service — weighted graph alarm compression.

Replaces string-dedup with explainable weighted alarm graph clustering.
Uses time proximity, same turbine/component, topology proximity,
operating conditions, causal rules, and signal correlation.

Algorithm: Union-Find over weighted edges. Alarms with edge weight
above a configurable threshold are merged into the same cluster.
The primary alarm in each cluster is selected by severity × recency.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import numpy as np
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AlarmRecord, Fault, Incident, Turbine

logger = logging.getLogger(__name__)


@dataclass
class AlarmNode:
    """One alarm in the correlation graph."""
    alarm_id: int
    turbine_id: int
    component: str = ""
    alarm_type: str = ""
    severity: str = "medium"
    fired_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    value: Optional[float] = None
    source: str = "unknown"


@dataclass
class AlarmCluster:
    """A compressed alarm cluster."""
    cluster_id: int
    primary_alarm_id: int
    alarm_ids: list[int]
    alarm_count: int
    components: list[str]
    severity: str
    primary_reason: str  # Why this is the primary alarm
    merged_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class AlarmCorrelationResult:
    """Full alarm correlation output."""
    original_count: int
    compressed_count: int
    compression_ratio: float
    clusters: list[AlarmCluster]
    clusters_json: list[dict[str, Any]]  # Serializable for API response
    algorithm: str = "weighted_graph_union_find_v1"
    window_minutes: int = 60


class AlarmCorrelationService:
    """Weighted graph alarm correlation using Union-Find clustering.

    Edge weights combine:
    - time_proximity: exp(-|Δt| / window_minutes)
    - same_turbine: 1.0 if same turbine, 0.0 otherwise
    - same_component: 1.0 if same component, 0.5 if same component group
    - topology_proximity: 0.5 if components are in same subsystem
    - causal_rule_match: 0.3 if known causal relationship exists
    - signal_correlation: Pearson correlation of alarm values (if available)
    """

    # Component topology groups (components in same subsystem)
    COMPONENT_GROUPS: dict[str, set[str]] = {
        "drivetrain": {"gearbox", "main_shaft", "bearing", "generator", "coupling"},
        "blade": {"blade", "pitch_system", "rotor"},
        "electrical": {"generator", "converter", "transformer", "grid"},
        "cooling": {"cooling_system", "radiator", "pump"},
        "tower": {"tower", "foundation", "nacelle"},
        "control": {"controller", "sensor", "actuator", "yaw_system"},
    }

    # Known causal relationships: alarm_type_a → alarm_type_b
    CAUSAL_RULES: list[tuple[str, str]] = [
        ("vibration_high", "bearing_wear"),
        ("bearing_wear", "temperature_high"),
        ("temperature_high", "cooling_system_fault"),
        ("gearbox_wear", "vibration_high"),
        ("vibration_high", "generator_overheat"),
        ("blade_damage", "vibration_high"),
        ("pitch_fault", "blade_damage"),
    ]

    def __init__(
        self,
        window_minutes: int = 60,
        threshold: float = 0.35,
        db: Optional[AsyncSession] = None,
    ):
        self.window_minutes = window_minutes
        self.threshold = threshold  # Edge weight threshold for merging
        self.db = db

    # ── Main entry point ──

    async def correlate(
        self,
        alarms: list[dict[str, Any]],
        turbine_id: Optional[int] = None,
    ) -> AlarmCorrelationResult:
        """Correlate and compress a list of alarms into clusters.

        Args:
            alarms: List of alarm dicts with keys:
                id, turbine_id, component, alarm_type, severity, fired_at, value, source
            turbine_id: Filter by turbine (optional)

        Returns:
            AlarmCorrelationResult with clusters and compression stats.
        """
        if not alarms:
            return AlarmCorrelationResult(
                original_count=0,
                compressed_count=0,
                compression_ratio=0.0,
                clusters=[],
                clusters_json=[],
                window_minutes=self.window_minutes,
            )

        # Filter by turbine if specified
        if turbine_id is not None:
            alarms = [a for a in alarms if a.get("turbine_id") == turbine_id]

        original_count = len(alarms)
        if original_count <= 1:
            clusters = [
                AlarmCluster(
                    cluster_id=0,
                    primary_alarm_id=alarms[0].get("id", 0) if alarms else 0,
                    alarm_ids=[a.get("id", 0) for a in alarms],
                    alarm_count=original_count,
                    components=list({a.get("component", "") for a in alarms}),
                    severity=self._highest_severity(alarms),
                    primary_reason="Single alarm — no compression needed",
                )
            ]
            return self._build_result(original_count, clusters)

        # Build nodes
        nodes = [
            AlarmNode(
                alarm_id=a.get("id", i),
                turbine_id=a.get("turbine_id", 0),
                component=a.get("component", ""),
                alarm_type=a.get("alarm_type", a.get("fault_type", "")),
                severity=a.get("severity", "medium"),
                fired_at=self._parse_time(a.get("fired_at", a.get("detected_at"))),
                value=a.get("value"),
                source=a.get("source", "unknown"),
            )
            for i, a in enumerate(alarms)
        ]

        # Build weighted adjacency and run Union-Find
        parent = list(range(len(nodes)))
        rank = [0] * len(nodes)

        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                weight = self._edge_weight(nodes[i], nodes[j])
                if weight >= self.threshold:
                    self._union(i, j, parent, rank)

        # Group by root
        groups: dict[int, list[int]] = defaultdict(list)
        for i in range(len(nodes)):
            root = self._find(i, parent)
            groups[root].append(i)

        # Build clusters
        clusters: list[AlarmCluster] = []
        for cluster_id, (root, indices) in enumerate(groups.items()):
            cluster_nodes = [nodes[i] for i in indices]
            primary = self._select_primary(cluster_nodes)

            clusters.append(AlarmCluster(
                cluster_id=cluster_id,
                primary_alarm_id=primary.alarm_id,
                alarm_ids=[nodes[i].alarm_id for i in indices],
                alarm_count=len(indices),
                components=list({n.component for n in cluster_nodes if n.component}),
                severity=self._highest_severity(
                    [{"severity": n.severity} for n in cluster_nodes]
                ),
                primary_reason=f"Highest severity ({primary.severity}) × most recent in cluster",
            ))

        return self._build_result(original_count, clusters)

    # ── Edge weight computation ──

    def _edge_weight(self, a: AlarmNode, b: AlarmNode) -> float:
        """Compute weighted edge between two alarm nodes.

        Returns 0.0–1.0. Higher = more likely same root cause.
        """
        w_time = self._time_proximity(a, b)
        w_turbine = 1.0 if a.turbine_id == b.turbine_id and a.turbine_id > 0 else 0.3
        w_component = self._component_proximity(a.component, b.component)
        w_topology = self._topology_proximity(a.component, b.component)
        w_causal = self._causal_proximity(a.alarm_type, b.alarm_type)
        w_signal = self._signal_correlation(a, b)

        # Weighted sum with configurable weights
        weights = {
            "time": 0.30,
            "turbine": 0.20,
            "component": 0.20,
            "topology": 0.10,
            "causal": 0.10,
            "signal": 0.10,
        }

        return (
            weights["time"] * w_time
            + weights["turbine"] * w_turbine
            + weights["component"] * w_component
            + weights["topology"] * w_topology
            + weights["causal"] * w_causal
            + weights["signal"] * w_signal
        )

    def _time_proximity(self, a: AlarmNode, b: AlarmNode) -> float:
        """Exponential decay of time difference."""
        if a.fired_at is None or b.fired_at is None:
            return 0.5
        delta_min = abs((a.fired_at - b.fired_at).total_seconds()) / 60.0
        if delta_min > self.window_minutes:
            return 0.0
        return float(np.exp(-delta_min / self.window_minutes))

    def _component_proximity(self, comp_a: str, comp_b: str) -> float:
        """Component name similarity."""
        if not comp_a or not comp_b:
            return 0.3  # Unknown component — neutral
        if comp_a.lower() == comp_b.lower():
            return 1.0
        # Partial match (e.g., "gearbox_bearing" and "gearbox_gear")
        if comp_a.lower() in comp_b.lower() or comp_b.lower() in comp_a.lower():
            return 0.6
        return 0.0

    def _topology_proximity(self, comp_a: str, comp_b: str) -> float:
        """Check if components are in the same subsystem group."""
        if not comp_a or not comp_b:
            return 0.0
        for group, members in self.COMPONENT_GROUPS.items():
            a_in = any(m in comp_a.lower() for m in members)
            b_in = any(m in comp_b.lower() for m in members)
            if a_in and b_in:
                return 0.5
        return 0.0

    def _causal_proximity(self, type_a: str, type_b: str) -> float:
        """Check known causal relationships."""
        for cause, effect in self.CAUSAL_RULES:
            if (cause in type_a.lower() and effect in type_b.lower()) or \
               (cause in type_b.lower() and effect in type_a.lower()):
                return 0.3
        return 0.0

    def _signal_correlation(self, a: AlarmNode, b: AlarmNode) -> float:
        """Correlation of alarm values (placeholder — needs time series)."""
        # For single-point alarms, we can't compute correlation.
        # Returns neutral 0.5 when both have values, 0.0 otherwise.
        if a.value is not None and b.value is not None:
            return 0.5
        return 0.0

    # ── Union-Find ──

    def _find(self, x: int, parent: list[int]) -> int:
        if parent[x] != x:
            parent[x] = self._find(parent[x], parent)
        return parent[x]

    def _union(self, x: int, y: int, parent: list[int], rank: list[int]) -> None:
        rx, ry = self._find(x, parent), self._find(y, parent)
        if rx == ry:
            return
        if rank[rx] < rank[ry]:
            parent[rx] = ry
        elif rank[rx] > rank[ry]:
            parent[ry] = rx
        else:
            parent[ry] = rx
            rank[rx] += 1

    # ── Primary alarm selection ──

    SEVERITY_WEIGHTS = {"critical": 10, "high": 7, "medium": 4, "low": 1}

    def _select_primary(self, nodes: list[AlarmNode]) -> AlarmNode:
        """Select primary alarm: highest severity × most recent."""
        if not nodes:
            raise ValueError("Cannot select primary from empty cluster")

        now = datetime.now(timezone.utc)

        def score(n: AlarmNode) -> float:
            sev = self.SEVERITY_WEIGHTS.get(n.severity.lower(), 2)
            age_hours = (
                (now - n.fired_at).total_seconds() / 3600.0
                if n.fired_at
                else 999.0
            )
            recency = max(0.1, 24.0 / (age_hours + 1.0))
            return sev * recency

        return max(nodes, key=score)

    # ── Helpers ──

    def _highest_severity(self, alarms: list[dict[str, Any]]) -> str:
        sev_order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
        return max(
            alarms,
            key=lambda a: sev_order.get(str(a.get("severity", "medium")).lower(), 0),
            default={"severity": "medium"},
        ).get("severity", "medium")

    def _parse_time(self, raw: Any) -> datetime:
        if raw is None:
            return datetime.now(timezone.utc)
        if isinstance(raw, datetime):
            return raw
        try:
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return datetime.now(timezone.utc)

    def _build_result(
        self, original_count: int, clusters: list[AlarmCluster]
    ) -> AlarmCorrelationResult:
        compressed_count = len(clusters)
        ratio = (
            (original_count - compressed_count) / original_count
            if original_count > 0
            else 0.0
        )

        clusters_json = []
        for c in clusters:
            clusters_json.append({
                "cluster_id": c.cluster_id,
                "primary_alarm_id": c.primary_alarm_id,
                "alarm_ids": c.alarm_ids,
                "alarm_count": c.alarm_count,
                "components": c.components,
                "severity": c.severity,
                "primary_reason": c.primary_reason,
            })

        return AlarmCorrelationResult(
            original_count=original_count,
            compressed_count=compressed_count,
            compression_ratio=ratio,
            clusters=clusters,
            clusters_json=clusters_json,
            window_minutes=self.window_minutes,
        )
