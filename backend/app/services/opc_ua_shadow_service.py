"""OPC UA digital shadow — address-space prototype simulator.

【状态】未接线的原型模拟器：本模块用伪随机数据（random.uniform/gauss）模拟
OPC UA 服务端行为，**未连接任何真实工业设备**，当前**未被任何路由引用**。
保留它的目的是给出接入真实 SCADA/OPC UA 时的地址空间与语义映射蓝本；
其输出不可用作实验结果或真实工况证据。

Provides (all in-process, no network / no asyncua dependency):
- Simulated OPC UA server behaviour driven by pseudo-random value generators
- 6-10 turbine nodes with realistic address space
- Address space browsing
- Node semantic mapping (OPC UA node → platform concept)
- MonitoredItem subscription with value change notifications
- Data quality codes (Good/Uncertain/Bad)
- Threshold-based incident creation
- Reconnect handling with exponential backoff
- Certificate/security mode documentation
- Write operations → ControlSandbox ONLY
- Policy engine blocks real device control

IMPORTANT: This is a READ-ONLY digital shadow for demo.
NOT production OPC UA. ADR documents what's needed for production.
"""
from __future__ import annotations

import logging
import math
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class DataQuality(str, Enum):
    GOOD = "Good"
    GOOD_LOCAL_OVERRIDE = "Good_LocalOverride"
    UNCERTAIN = "Uncertain"
    BAD = "Bad"
    BAD_NO_COMMUNICATION = "Bad_NoCommunication"


class SecurityMode(str, Enum):
    NONE = "None"
    SIGN = "Sign"
    SIGN_AND_ENCRYPT = "SignAndEncrypt"


@dataclass
class OPCUANode:
    """One node in the OPC UA address space."""
    node_id: str = ""          # ns=2;s=Turbine01.Gearbox.VibrationRMS
    browse_name: str = ""      # Gearbox.VibrationRMS
    display_name: str = ""     # Gearbox Vibration RMS
    node_class: str = "Variable"
    data_type: str = "Double"
    value: Any = None
    quality: DataQuality = DataQuality.GOOD
    unit: str = ""
    description: str = ""
    # Semantic mapping
    platform_concept: str = ""  # Maps to platform model
    alarm_threshold_high: Optional[float] = None
    alarm_threshold_low: Optional[float] = None
    # Metadata
    parent_node_id: str = ""
    children: list[str] = field(default_factory=list)


@dataclass
class MonitoredItem:
    """A subscription to a node's value changes."""
    item_id: str = field(default_factory=lambda: f"MON-{uuid.uuid4().hex[:8]}")
    node_id: str = ""
    callback: Optional[Callable] = None
    sampling_interval_ms: int = 1000
    queue_size: int = 10
    last_value: Any = None
    last_quality: DataQuality = DataQuality.GOOD
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class OPCUAConnectionState:
    """Connection state for the OPC UA server."""
    connected: bool = False
    endpoint_url: str = "opc.tcp://localhost:4840/windops/shadow"
    security_mode: SecurityMode = SecurityMode.NONE
    certificate_path: str = ""
    reconnect_attempts: int = 0
    max_reconnect_attempts: int = 10
    reconnect_backoff_base: float = 1.5  # Exponential backoff multiplier
    last_connected_at: Optional[datetime] = None
    last_disconnected_at: Optional[datetime] = None


# ── Turbine address space definition ──
# Simulated OPC UA information model for 8 wind turbines

TURBINE_NODES: list[dict[str, Any]] = [
    {
        "turbine_id": "T01", "name": "Wind Turbine 01",
        "rated_power_kw": 2000.0, "latitude": 42.3, "longitude": -71.8,
    },
    {
        "turbine_id": "T02", "name": "Wind Turbine 02",
        "rated_power_kw": 2000.0, "latitude": 42.31, "longitude": -71.79,
    },
    {
        "turbine_id": "T03", "name": "Wind Turbine 03",
        "rated_power_kw": 1500.0, "latitude": 42.32, "longitude": -71.78,
    },
    {
        "turbine_id": "T04", "name": "Wind Turbine 04",
        "rated_power_kw": 2000.0, "latitude": 42.29, "longitude": -71.81,
    },
    {
        "turbine_id": "T05", "name": "Wind Turbine 05",
        "rated_power_kw": 1500.0, "latitude": 42.33, "longitude": -71.77,
    },
    {
        "turbine_id": "T06", "name": "Wind Turbine 06",
        "rated_power_kw": 2000.0, "latitude": 42.28, "longitude": -71.82,
    },
    {
        "turbine_id": "T07", "name": "Wind Turbine 07",
        "rated_power_kw": 2000.0, "latitude": 42.34, "longitude": -71.76,
    },
    {
        "turbine_id": "T08", "name": "Wind Turbine 08",
        "rated_power_kw": 1500.0, "latitude": 42.27, "longitude": -71.83,
    },
]

# Component/variable definitions per turbine
COMPONENT_VARIABLES = [
    {"component": "Gearbox", "variables": [
        {"name": "VibrationRMS", "unit": "mm/s", "threshold_high": 7.1, "data_type": "Double"},
        {"name": "Temperature", "unit": "°C", "threshold_high": 80.0, "data_type": "Double"},
        {"name": "OilDebrisLevel", "unit": "ppm", "threshold_high": 150.0, "data_type": "Double"},
    ]},
    {"component": "Generator", "variables": [
        {"name": "Temperature", "unit": "°C", "threshold_high": 90.0, "data_type": "Double"},
        {"name": "PowerOutput", "unit": "kW", "threshold_low": 100.0, "data_type": "Double"},
        {"name": "RPM", "unit": "rpm", "threshold_high": 1800.0, "data_type": "Double"},
    ]},
    {"component": "MainBearing", "variables": [
        {"name": "VibrationRMS", "unit": "mm/s", "threshold_high": 5.6, "data_type": "Double"},
        {"name": "Temperature", "unit": "°C", "threshold_high": 70.0, "data_type": "Double"},
    ]},
    {"component": "Blade", "variables": [
        {"name": "PitchAngle", "unit": "deg", "data_type": "Double"},
        {"name": "StrainGauge", "unit": "µε", "threshold_high": 500.0, "data_type": "Double"},
    ]},
]


class OPCUAShadowService:
    """Simulated OPC UA digital shadow for wind farm connectivity.

    Production deployment would require:
    - Real asyncua server with proper certificate management
    - Network security (TLS, VPN) between IT and OT networks
    - Vendor-specific OPC UA companion spec compliance
    - Redundant server configuration
    - Proper error recovery and failover

    See ADR: docs/adr/opc-ua-production-requirements.md
    """

    def __init__(self):
        self.nodes: dict[str, OPCUANode] = {}
        self.subscriptions: dict[str, MonitoredItem] = {}
        self.connection = OPCUAConnectionState()
        self._build_address_space()
        self._incident_callback: Optional[Callable] = None

    # ── Address space ──

    def _build_address_space(self) -> None:
        """Build OPC UA address space with turbine hierarchy."""
        self.nodes["ns=2;s=WindFarm"] = OPCUANode(
            node_id="ns=2;s=WindFarm",
            browse_name="WindFarm",
            display_name="Wind Farm",
            node_class="Object",
            platform_concept="wind_farm",
        )

        for tdef in TURBINE_NODES:
            tid = tdef["turbine_id"]
            turbine_node_id = f"ns=2;s={tid}"

            self.nodes[turbine_node_id] = OPCUANode(
                node_id=turbine_node_id,
                browse_name=tid,
                display_name=tdef["name"],
                node_class="Object",
                platform_concept="turbine",
                parent_node_id="ns=2;s=WindFarm",
            )
            self.nodes["ns=2;s=WindFarm"].children.append(turbine_node_id)

            # Power variable
            power_node_id = f"{turbine_node_id}.Power"
            self.nodes[power_node_id] = OPCUANode(
                node_id=power_node_id,
                browse_name="Power",
                display_name="Active Power",
                data_type="Double",
                value=tdef["rated_power_kw"] * 0.7,  # Operating at 70%
                quality=DataQuality.GOOD,
                unit="kW",
                platform_concept="power_kw",
                parent_node_id=turbine_node_id,
            )
            self.nodes[turbine_node_id].children.append(power_node_id)

            # Component variables
            for comp_def in COMPONENT_VARIABLES:
                comp = comp_def["component"]
                comp_node_id = f"{turbine_node_id}.{comp}"

                self.nodes[comp_node_id] = OPCUANode(
                    node_id=comp_node_id,
                    browse_name=comp,
                    display_name=comp,
                    node_class="Object",
                    platform_concept="component",
                    parent_node_id=turbine_node_id,
                )
                self.nodes[turbine_node_id].children.append(comp_node_id)

                for var_def in comp_def["variables"]:
                    var_name = var_def["name"]
                    var_node_id = f"{comp_node_id}.{var_name}"

                    self.nodes[var_node_id] = OPCUANode(
                        node_id=var_node_id,
                        browse_name=var_name,
                        display_name=f"{comp} {var_name}",
                        data_type=var_def["data_type"],
                        value=self._simulate_initial_value(var_def, tdef),
                        quality=DataQuality.GOOD,
                        unit=var_def.get("unit", ""),
                        alarm_threshold_high=var_def.get("threshold_high"),
                        alarm_threshold_low=var_def.get("threshold_low"),
                        platform_concept=f"{comp.lower()}_{var_name.lower()}",
                        parent_node_id=comp_node_id,
                    )
                    self.nodes[comp_node_id].children.append(var_node_id)

    def _simulate_initial_value(
        self, var_def: dict, tdef: dict
    ) -> float:
        """Generate realistic initial value based on variable type."""
        name = var_def["name"]
        if name == "VibrationRMS":
            return round(random.uniform(2.0, 5.0), 2)
        elif name == "Temperature":
            return round(random.uniform(40.0, 65.0), 1)
        elif name == "OilDebrisLevel":
            return round(random.uniform(20.0, 80.0), 1)
        elif name == "PowerOutput":
            return round(tdef["rated_power_kw"] * random.uniform(0.5, 0.9), 0)
        elif name == "RPM":
            return round(random.uniform(1400, 1700), 0)
        elif name == "PitchAngle":
            return round(random.uniform(0, 15), 1)
        elif name == "StrainGauge":
            return round(random.uniform(100, 300), 1)
        return 0.0

    # ── Browsing ──

    def browse(self, node_id: str = "ns=2;s=WindFarm") -> list[dict[str, Any]]:
        """Browse children of a node."""
        node = self.nodes.get(node_id)
        if node is None:
            return []
        return [
            {
                "node_id": child_id,
                "browse_name": self.nodes[child_id].browse_name if child_id in self.nodes else "",
                "display_name": self.nodes[child_id].display_name if child_id in self.nodes else "",
                "node_class": self.nodes[child_id].node_class if child_id in self.nodes else "",
            }
            for child_id in node.children
        ]

    def browse_all(self) -> list[dict[str, Any]]:
        """Browse full address space."""
        return [
            {
                "node_id": n.node_id,
                "browse_name": n.browse_name,
                "display_name": n.display_name,
                "node_class": n.node_class,
                "data_type": n.data_type,
                "value": n.value,
                "unit": n.unit,
                "quality": n.quality.value,
                "platform_concept": n.platform_concept,
                "parent_node_id": n.parent_node_id,
            }
            for n in self.nodes.values()
        ]

    def read_node(self, node_id: str) -> Optional[dict[str, Any]]:
        """Read a single node's value and metadata."""
        node = self.nodes.get(node_id)
        if node is None:
            return None
        return {
            "node_id": node.node_id,
            "value": node.value,
            "quality": node.quality.value,
            "unit": node.unit,
            "data_type": node.data_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # ── Subscription ──

    def subscribe(
        self,
        node_id: str,
        callback: Optional[Callable] = None,
        sampling_ms: int = 1000,
    ) -> Optional[str]:
        """Create a MonitoredItem subscription."""
        node = self.nodes.get(node_id)
        if node is None:
            return None

        item = MonitoredItem(
            node_id=node_id,
            callback=callback,
            sampling_interval_ms=sampling_ms,
            last_value=node.value,
            last_quality=node.quality,
        )
        self.subscriptions[item.item_id] = item
        return item.item_id

    def unsubscribe(self, item_id: str) -> bool:
        """Remove a subscription."""
        if item_id in self.subscriptions:
            del self.subscriptions[item_id]
            return True
        return False

    def list_subscriptions(self) -> list[dict[str, Any]]:
        """List active subscriptions."""
        return [
            {
                "item_id": s.item_id,
                "node_id": s.node_id,
                "sampling_interval_ms": s.sampling_interval_ms,
                "last_value": s.last_value,
                "last_quality": s.last_quality.value,
            }
            for s in self.subscriptions.values()
        ]

    # ── Simulation tick ──

    def tick(self, incident_callback: Optional[Callable] = None) -> list[dict[str, Any]]:
        """Simulate one time step. Updates values, checks thresholds, calls callbacks.

        Call every second in production via asyncio loop.
        """
        self._incident_callback = incident_callback
        events: list[dict[str, Any]] = []

        for node_id, node in self.nodes.items():
            if node.node_class != "Variable":
                continue
            if node.value is None or not isinstance(node.value, (int, float)):
                continue

            # Add noise
            noise_scale = abs(node.value) * 0.01  # 1% noise
            node.value = round(node.value + random.gauss(0, noise_scale), 2)

            # Simulate occasional degradation
            if random.random() < 0.001:  # 0.1% chance per tick
                node.quality = DataQuality.UNCERTAIN
                events.append({
                    "type": "quality_change",
                    "node_id": node_id,
                    "quality": "Uncertain",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

            # Check thresholds
            event = self._check_threshold(node, node_id)
            if event:
                events.append(event)

        # Process subscription callbacks
        for item in self.subscriptions.values():
            node = self.nodes.get(item.node_id)
            if node and node.value != item.last_value:
                if item.callback:
                    item.callback(item.node_id, node.value, node.quality.value)
                item.last_value = node.value

        return events

    def _check_threshold(
        self, node: OPCUANode, node_id: str
    ) -> Optional[dict[str, Any]]:
        """Check if value exceeds alarm threshold."""
        if node.value is None or not isinstance(node.value, (int, float)):
            return None

        if (
            node.alarm_threshold_high is not None
            and node.value > node.alarm_threshold_high
        ):
            return {
                "type": "threshold_violation",
                "node_id": node_id,
                "variable": node.browse_name,
                "value": node.value,
                "threshold": node.alarm_threshold_high,
                "direction": "high",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "create_incident": True,
                "incident_title": f"{node.display_name} threshold exceeded: {node.value} > {node.alarm_threshold_high} {node.unit}",
            }

        if (
            node.alarm_threshold_low is not None
            and node.value < node.alarm_threshold_low
        ):
            return {
                "type": "threshold_violation",
                "node_id": node_id,
                "variable": node.browse_name,
                "value": node.value,
                "threshold": node.alarm_threshold_low,
                "direction": "low",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "create_incident": True,
                "incident_title": f"{node.display_name} below threshold: {node.value} < {node.alarm_threshold_low} {node.unit}",
            }

        return None

    # ── Control sandbox ──

    def write_to_sandbox(self, node_id: str, value: Any) -> dict[str, Any]:
        """Write a value to the ControlSandbox.

        REAL device control is BLOCKED by policy engine.
        This sandbox exists for simulation/demo only.
        """
        return {
            "node_id": node_id,
            "written": True,
            "value": value,
            "sandbox": True,
            "real_device": False,
            "warning": (
                "WRITTEN TO SANDBOX ONLY. "
                "Real device control is blocked by policy REG-003/REG-008. "
                "Production control requires SCADA system through OPC UA security."
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # ── Connection management ──

    def connect(self, endpoint_url: str = "") -> OPCUAConnectionState:
        """Simulate connection to OPC UA server."""
        if endpoint_url:
            self.connection.endpoint_url = endpoint_url
        self.connection.connected = True
        self.connection.reconnect_attempts = 0
        self.connection.last_connected_at = datetime.now(timezone.utc)
        logger.info(f"OPC UA shadow connected to {self.connection.endpoint_url}")
        return self.connection

    def disconnect(self) -> None:
        """Simulate disconnection."""
        self.connection.connected = False
        self.connection.last_disconnected_at = datetime.now(timezone.utc)
        # Mark all nodes as uncertain
        for node in self.nodes.values():
            if node.node_class == "Variable":
                node.quality = DataQuality.BAD_NO_COMMUNICATION
        logger.warning("OPC UA shadow disconnected")

    def reconnect(self) -> OPCUAConnectionState:
        """Simulate reconnection with exponential backoff."""
        if self.connection.reconnect_attempts >= self.connection.max_reconnect_attempts:
            logger.error("Max reconnect attempts reached")
            return self.connection

        self.connection.reconnect_attempts += 1
        backoff = self.connection.reconnect_backoff_base ** self.connection.reconnect_attempts
        logger.info(f"Reconnect attempt {self.connection.reconnect_attempts}/{self.connection.max_reconnect_attempts}, "
                    f"backoff: {backoff:.1f}s")

        self.connection.connected = True
        self.connection.last_connected_at = datetime.now(timezone.utc)
        # Restore quality
        for node in self.nodes.values():
            if node.node_class == "Variable":
                node.quality = DataQuality.GOOD
        return self.connection
