"""Open PHM API service — open-capability specification for wind turbine PHM.

【状态】**混合规范（hybrid）**：本模块输出的 OpenAPI 3.0 文档由两部分合并而成：

1. ``implemented``（已实现）：从运行中的 FastAPI 应用 ``app.openapi()`` **自动提取**的
   真实端点。它们此刻就能调用，路径、方法、摘要全部来自运行时内省，不可能吹牛。
2. ``planned``（规划中）：手工维护的 ``/api/v1/phm/*`` 统一开放契约。它是对外开放的
   目标形态（稳定路径 + 稳定 schema），当前尚未落地为真实路由。

每个规划端点都带 ``x-implementation-status`` 与 ``x-implemented-by``：
后者列出**当前已经能提供同等能力**的真实端点，并且在生成时会与运行时路由表核对，
核对不上的会被标成 ``unverified``。这样规范既诚实（不把规划说成已实现），
又有说服力（能力已存在，只差统一门面）。

Delivers:
- Hybrid OpenAPI 3.0 spec: runtime-introspected `implemented` + hand-maintained `planned`
- Capability matrix mapping planned open endpoints to today's real endpoints
- Python client SDK interface (written against the target contract)
- Example request/responses (clearly labeled simulated where applicable)
- Industry template adapters (photovoltaic, pump, compressor) with machine-readable term mapping
- Tool interface, Playbook, Policy template documentation
- Third-party dependency and license inventory
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

#: 规划中的统一开放端点 → 当前已实现、可提供同等能力的真实端点。
#: 生成规范时会拿这里的路径去运行时路由表核对，核对不上即标 unverified，
#: 避免「纸面能力」蒙混过关。
CAPABILITY_BINDINGS: dict[tuple[str, str], list[str]] = {
    ("/health/predict", "post"): [
        "GET /api/turbines/{turbine_id}/health",
        "GET /api/turbines/{turbine_id}/health-passport",
        "GET /api/prediction/rul",
        "GET /api/prediction/summary",
    ],
    ("/diagnosis/diagnose", "post"): [
        "POST /api/diagnosis/auto-detect",
        "POST /api/diagnosis/fault-genotype",
        "POST /api/diagnosis/causal-discovery",
        "POST /api/agent/diagnose",
    ],
    ("/maintenance/recommend", "post"): [
        "POST /api/incidents/{incident_id}/generate-plans",
        "GET /api/prediction/maintenance-plan",
        "POST /api/prediction/schedule",
        "POST /api/incidents/{incident_id}/negotiate-resource",
    ],
    ("/incidents", "get"): ["GET /api/incidents"],
    ("/incidents", "post"): ["POST /api/incidents"],
    ("/evidence/{incident_id}", "get"): [
        "GET /api/incidents/{incident_id}/evidence-graph",
        "GET /api/incidents/{incident_id}/evidence-completeness",
        "GET /api/incidents/{incident_id}/audit-chain",
    ],
}


@dataclass
class APIEndpoint:
    path: str = ""
    method: str = "GET"
    summary: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    parameters: list[dict[str, Any]] = field(default_factory=list)
    request_body: dict[str, Any] | None = None
    responses: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class IndustryTemplate:
    """Quick-start template for adapting PHM API to another industry.

    ``term_mapping`` / ``metric_mapping`` / ``fault_mapping`` 是**机器可读**的替换表，
    ``backend/scripts/instantiate_industry_template.py`` 直接消费它们，
    把风电 playbook 实例化成目标行业的可运行适配包 —— 让「可迁移」从口号变成产物。
    """
    name: str = ""       # photovoltaic / pump / compressor
    domain: str = ""
    key_entities: list[str] = field(default_factory=list)
    key_metrics: list[str] = field(default_factory=list)
    fault_types: list[str] = field(default_factory=list)
    adapter_notes: str = ""
    example_config: dict[str, Any] = field(default_factory=dict)
    #: 术语替换：风电词汇 → 目标行业词汇（含中英文，脚本按最长匹配优先替换）
    term_mapping: dict[str, str] = field(default_factory=dict)
    #: 指标替换：风电指标名 → 目标行业指标名
    metric_mapping: dict[str, str] = field(default_factory=dict)
    #: 故障类型替换：风电故障 → 目标行业故障
    fault_mapping: dict[str, str] = field(default_factory=dict)


@dataclass
class OpenAPISpec:
    version: str = "1.0.0"
    title: str = "WindOps PHM API"
    description: str = ""
    base_url: str = "/api/v1/phm"
    endpoints: list[APIEndpoint] = field(default_factory=list)


class OpenPHMAPIService:
    """Generates and serves the Open PHM API specification."""

    # ── 运行时内省：从 FastAPI 提取真实已实现端点 ──

    @staticmethod
    def _runtime_openapi() -> dict[str, Any] | None:
        """读取运行中的 FastAPI 应用的 OpenAPI 文档（失败返回 None，不影响规范输出）。"""
        try:
            from app.main import app  # 延迟导入，避免循环依赖

            return app.openapi()
        except Exception as exc:  # pragma: no cover - 防御性
            logger.warning(f"无法内省运行时 OpenAPI 文档，规范将只含手工契约部分：{exc}")
            return None

    def _collect_implemented(self) -> tuple[dict[str, Any], set[str]]:
        """把运行时路由整理成 ``{"METHOD /path": {...}}``，并返回索引集合。"""
        runtime = self._runtime_openapi()
        implemented: dict[str, Any] = {}
        index: set[str] = set()
        if not runtime:
            return implemented, index
        for path, ops in (runtime.get("paths") or {}).items():
            for method, op in ops.items():
                if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                    continue
                key = f"{method.upper()} {path}"
                index.add(key)
                implemented[key] = {
                    "path": path,
                    "method": method.upper(),
                    "summary": op.get("summary", ""),
                    "tags": op.get("tags", []),
                    "operation_id": op.get("operationId", ""),
                }
        return implemented, index

    def _capability_matrix(self, index: set[str]) -> list[dict[str, Any]]:
        """把「规划端点 ↔ 已实现端点」的绑定关系与运行时路由表核对。"""
        matrix: list[dict[str, Any]] = []
        for (planned_path, method), bindings in CAPABILITY_BINDINGS.items():
            verified = [b for b in bindings if b in index]
            unverified = [b for b in bindings if b not in index]
            matrix.append({
                "planned_endpoint": f"{method.upper()} /api/v1/phm{planned_path}",
                "capability_status": "implemented_via_existing_endpoints" if verified else "planned_only",
                "implemented_by": verified,
                "unverified_bindings": unverified,
                "note": (
                    f"能力已由 {len(verified)} 个真实端点提供，统一开放门面待落地。"
                    if verified else "当前尚无等效实现，属于规划能力。"
                ),
            })
        return matrix

    def get_spec(self) -> dict[str, Any]:
        """Get the open-capability OpenAPI 3.0 specification (hybrid).

        由两部分合并：
        - ``x-implemented-endpoints``：从运行中的 FastAPI ``app.openapi()`` **自动提取**的
          真实端点（此刻即可调用）；
        - ``paths``：手工维护的 ``/api/v1/phm/*`` 统一开放目标契约，逐个操作标注
          ``x-implementation-status`` 与 ``x-implemented-by``（已与运行时路由表核对）。

        因此本规范既诚实（规划就是规划），又有说服力（能力已经存在）。
        """
        implemented, index = self._collect_implemented()
        matrix = self._capability_matrix(index)
        covered = sum(1 for row in matrix if row["implemented_by"])

        spec = {
            "openapi": "3.0.0",
            "status": "hybrid" if implemented else "draft",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "spec_status": {
                "status": "hybrid" if implemented else "draft",
                "generated_from": (
                    "hybrid: FastAPI 运行时内省(implemented) + 手工维护目标契约(planned)"
                    if implemented else "hand_maintained"
                ),
                "runtime_introspection_available": bool(implemented),
                "implemented_endpoint_count": len(implemented),
                "planned_endpoint_count": len(CAPABILITY_BINDINGS),
                "planned_endpoints_backed_by_implementation": covered,
                "note": (
                    "`x-implemented-endpoints` 为真实存在、可直接调用的端点，来自 FastAPI 自动生成的 "
                    "/openapi.json；`paths` 下的 /api/v1/phm/* 为**规划中**的统一开放契约，"
                    "尚未落地为真实路由，但每个操作都标注了当前提供同等能力的真实端点。"
                ),
            },
            "info": {
                "title": "WindOps PHM Open API v1.0 (implemented + planned)",
                "description": (
                    "开放风电预测性健康管理(PHM) API 规范（混合规范）。\n\n"
                    f"✔ 已实现：{len(implemented)} 个真实端点，由 FastAPI 运行时自动提取，"
                    "见 `x-implemented-endpoints`，此刻即可调用。\n"
                    f"◻ 规划中：{len(CAPABILITY_BINDINGS)} 个 `/api/v1/phm/*` 统一开放端点，"
                    f"其中 {covered} 个的能力已由现有真实端点提供（见 `x-capability-matrix`），"
                    "只差统一门面。\n\n"
                    "规划的标准化接口用于：设备健康预测、故障诊断、维修方案推荐、\n"
                    "事件管理、证据查询、恢复验证。\n\n"
                    "⚠ 标注 `simulated` 的示例为模拟数据，不代表真实风场运行数据。\n"
                    "生产部署前需根据实际风场配置调整参数。"
                ),
                "version": "1.0.0-hybrid",
                "contact": {"name": "WindOps Team"},
                "license": {"name": "Apache 2.0", "url": "https://www.apache.org/licenses/LICENSE-2.0"},
            },
            "servers": [
                {"url": "http://localhost:8080/api/v1/phm", "description": "本地开发服务器"},
                {"url": "https://windops.example.com/api/v1/phm", "description": "生产服务器 (示例)"},
            ],
            "tags": [
                {"name": "Health", "description": "健康状态预测与评估"},
                {"name": "Diagnosis", "description": "故障诊断与根因分析"},
                {"name": "Maintenance", "description": "维修方案推荐与任务管理"},
                {"name": "Incident", "description": "运维事件生命周期管理"},
                {"name": "Evidence", "description": "证据管理与查询"},
            ],
            "paths": {
                "/health/predict": {
                    "post": {
                        "summary": "预测设备健康状态",
                        "tags": ["Health"],
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "turbine_id": {"type": "string", "description": "风机标识"},
                                            "time_range_hours": {"type": "integer", "default": 168},
                                            "features": {"type": "array", "items": {"type": "string"}},
                                        },
                                    }
                                }
                            },
                        },
                        "responses": {
                            "200": {
                                "description": "健康预测结果",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "health_index": {"type": "number"},
                                                "degradation_rate": {"type": "number"},
                                                "rul_days": {"type": "number"},
                                                "confidence_interval": {"type": "object"},
                                                "anomalies": {"type": "array"},
                                            },
                                        }
                                    }
                                },
                            },
                        },
                    }
                },
                "/diagnosis/diagnose": {
                    "post": {
                        "summary": "故障诊断",
                        "tags": ["Diagnosis"],
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "turbine_id": {"type": "string"},
                                            "symptoms": {"type": "object", "description": "症状特征字典"},
                                            "method": {"type": "string", "enum": ["rule", "genotype", "llm"], "default": "rule"},
                                        },
                                    }
                                }
                            },
                        },
                        "responses": {
                            "200": {
                                "description": "诊断结果",
                            },
                        },
                    }
                },
                "/maintenance/recommend": {
                    "post": {
                        "summary": "维修方案推荐",
                        "tags": ["Maintenance"],
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "incident_id": {"type": "string"},
                                            "constraints": {"type": "object", "description": "资源约束 (人员/备件/天气)"},
                                        },
                                    }
                                }
                            },
                        },
                        "responses": {
                            "200": {"description": "维修方案列表"},
                        },
                    }
                },
                "/incidents": {
                    "get": {
                        "summary": "获取事件列表",
                        "tags": ["Incident"],
                        "parameters": [
                            {"name": "status", "in": "query", "schema": {"type": "string"}},
                            {"name": "turbine_id", "in": "query", "schema": {"type": "integer"}},
                        ],
                        "responses": {
                            "200": {"description": "事件列表"},
                        },
                    },
                    "post": {
                        "summary": "创建事件",
                        "tags": ["Incident"],
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["turbine_id", "title"],
                                        "properties": {
                                            "turbine_id": {"type": "integer"},
                                            "title": {"type": "string"},
                                            "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                                        },
                                    }
                                }
                            },
                        },
                        "responses": {
                            "201": {"description": "创建成功"},
                        },
                    },
                },
                "/evidence/{incident_id}": {
                    "get": {
                        "summary": "获取事件证据",
                        "tags": ["Evidence"],
                        "parameters": [
                            {"name": "incident_id", "in": "path", "required": True, "schema": {"type": "string"}},
                        ],
                        "responses": {
                            "200": {"description": "证据列表"},
                        },
                    },
                },
            },
            "x-implemented-endpoints": implemented,
            "x-capability-matrix": matrix,
            "components": {
                "schemas": {
                    "HealthPrediction": {
                        "type": "object",
                        "properties": {
                            "health_index": {"type": "number", "description": "健康指数 0-100"},
                            "degradation_rate": {"type": "number", "description": "退化率 %/月"},
                            "rul_days": {"type": "number", "description": "剩余使用寿命 天"},
                            "confidence_interval": {
                                "type": "object",
                                "properties": {
                                    "lower": {"type": "number"},
                                    "upper": {"type": "number"},
                                },
                            },
                        },
                    },
                },
                "securitySchemes": {
                    "bearerAuth": {
                        "type": "http",
                        "scheme": "bearer",
                        "bearerFormat": "JWT",
                    },
                },
            },
            "security": [{"bearerAuth": []}],
        }

        # 逐个规划操作打上实现状态标注（与运行时路由表核对过）
        binding_by_key = {row["planned_endpoint"]: row for row in matrix}
        for planned_path, operations in spec["paths"].items():
            for method, operation in operations.items():
                row = binding_by_key.get(f"{method.upper()} /api/v1/phm{planned_path}")
                backed = bool(row and row["implemented_by"])
                operation["x-implementation-status"] = "planned"
                operation["x-capability-available"] = backed
                operation["x-implemented-by"] = row["implemented_by"] if row else []
                operation["x-note"] = (
                    "统一开放路径尚未落地；同等能力现已由左列真实端点提供，可直接调用。"
                    if backed else "规划能力，当前尚无等效实现。"
                )
        return spec

    def get_python_client_template(self) -> str:
        """Generate Python client SDK template for the draft open API contract."""
        return '''"""
WindOps PHM Python Client (draft)

NOTE: written against the hand-maintained /api/v1/phm draft contract, which is
not implemented on the backend yet. Use it as an integration blueprint.

Usage:
    from windops_phm import WindOpsClient
    client = WindOpsClient(base_url="http://localhost:8080", api_key="...")
    health = client.predict_health(turbine_id="T01")
    diagnosis = client.diagnose_fault(turbine_id="T01", symptoms={"vibration_rms": 8.5})
"""

import requests
from typing import Optional, Any


class WindOpsClient:
    def __init__(self, base_url: str, api_key: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        if api_key:
            self.session.headers["Authorization"] = f"Bearer {api_key}"
        self.session.headers["Content-Type"] = "application/json"

    def predict_health(self, turbine_id: str, time_range_hours: int = 168) -> dict:
        resp = self.session.post(
            f"{self.base_url}/api/v1/phm/health/predict",
            json={"turbine_id": turbine_id, "time_range_hours": time_range_hours},
        )
        resp.raise_for_status()
        return resp.json()

    def diagnose_fault(self, turbine_id: str, symptoms: dict) -> dict:
        resp = self.session.post(
            f"{self.base_url}/api/v1/phm/diagnosis/diagnose",
            json={"turbine_id": turbine_id, "symptoms": symptoms},
        )
        resp.raise_for_status()
        return resp.json()

    def recommend_maintenance(self, incident_id: str) -> dict:
        resp = self.session.post(
            f"{self.base_url}/api/v1/phm/maintenance/recommend",
            json={"incident_id": incident_id},
        )
        resp.raise_for_status()
        return resp.json()

    def list_incidents(self, status: Optional[str] = None) -> list:
        params = {}
        if status:
            params["status"] = status
        resp = self.session.get(f"{self.base_url}/api/v1/phm/incidents", params=params)
        resp.raise_for_status()
        return resp.json()
'''

    def get_industry_templates(self) -> list[dict[str, Any]]:
        """Get industry adaptation templates."""
        templates: list[IndustryTemplate] = [
            IndustryTemplate(
                name="photovoltaic",
                domain="光伏电站运维",
                key_entities=["光伏阵列", "逆变器", "汇流箱", "变压器"],
                key_metrics=["发电功率kW", "转换效率%", "组件温度°C", "I-V特性"],
                fault_types=["组件衰减", "逆变器故障", "热斑", "PID效应", "接线盒故障"],
                adapter_notes=(
                    "光伏场景映射：turbine→光伏阵列，gearbox→逆变器，"
                    "vibration→I-V特性，power→发电功率。"
                    "故障基因需替换为光伏特有故障模式。"
                ),
                example_config={"asset_type": "solar_array", "rated_power_kw": 500, "metrics": ["power_kw", "efficiency", "irradiance"]},
                term_mapping={
                    "风机": "光伏阵列", "风电场": "光伏电站", "机组": "阵列",
                    "叶片": "组件", "齿轮箱": "逆变器", "发电机": "汇流箱",
                    "主轴承": "汇流箱熔断器", "偏航": "跟踪支架", "变桨": "MPPT调节",
                    "塔筒": "支架结构", "风速": "辐照度", "风向": "太阳方位角",
                    "turbine": "solar_array", "gearbox": "inverter", "blade": "module",
                    "generator": "combiner_box", "wind_speed": "irradiance",
                    "nacelle": "inverter_cabinet", "yaw": "tracker", "pitch": "mppt",
                },
                metric_mapping={
                    "有功功率kW": "发电功率kW", "风速m/s": "辐照度W/m²",
                    "齿轮箱油温°C": "逆变器温度°C", "振动mm/s": "I-V曲线偏差%",
                    "发电机转速rpm": "直流母线电压V",
                },
                fault_mapping={
                    "齿轮箱磨损": "组件衰减", "主轴承故障": "逆变器故障",
                    "叶片裂纹": "热斑", "变桨系统异常": "PID效应",
                    "发电机绕组过热": "接线盒故障",
                },
            ),
            IndustryTemplate(
                name="pump",
                domain="水泵/泵站运维",
                key_entities=["水泵", "电机", "轴承", "密封件"],
                key_metrics=["流量m³/h", "扬程m", "振动mm/s", "电流A", "温度°C"],
                fault_types=["轴承磨损", "叶轮气蚀", "密封泄漏", "电机过热", "不平衡"],
                adapter_notes=(
                    "水泵场景映射：turbine→泵组，gearbox→联轴器，"
                    "vibration→泵体振动，flow→功率。"
                    "需添加气蚀检测特征。"
                ),
                example_config={"asset_type": "centrifugal_pump", "rated_flow_m3h": 200, "metrics": ["flow", "head", "vibration", "current"]},
                term_mapping={
                    "风机": "泵组", "风电场": "泵站", "机组": "泵组",
                    "叶片": "叶轮", "齿轮箱": "联轴器", "发电机": "驱动电机",
                    "主轴承": "泵轴承", "偏航": "调速", "变桨": "阀门开度",
                    "塔筒": "泵体", "风速": "入口流量", "风向": "管路压差",
                    "turbine": "pump", "gearbox": "coupling", "blade": "impeller",
                    "generator": "motor", "wind_speed": "inlet_flow",
                    "nacelle": "pump_casing", "yaw": "speed_control", "pitch": "valve_position",
                },
                metric_mapping={
                    "有功功率kW": "轴功率kW", "风速m/s": "流量m³/h",
                    "齿轮箱油温°C": "轴承温度°C", "振动mm/s": "泵体振动mm/s",
                    "发电机转速rpm": "泵转速rpm",
                },
                fault_mapping={
                    "齿轮箱磨损": "轴承磨损", "主轴承故障": "轴承磨损",
                    "叶片裂纹": "叶轮气蚀", "变桨系统异常": "密封泄漏",
                    "发电机绕组过热": "电机过热",
                },
            ),
            IndustryTemplate(
                name="compressor",
                domain="压缩机运维",
                key_entities=["压缩机", "电机", "冷却器", "油系统"],
                key_metrics=["排气压力MPa", "排气温度°C", "振动mm/s", "油压MPa", "电流A"],
                fault_types=["气阀故障", "活塞环磨损", "轴承故障", "油路堵塞", "气缸泄漏"],
                adapter_notes=(
                    "压缩机场景映射：turbine→压缩机组，vibration→缸体振动，"
                    "pressure→功率。需添加压力脉动特征。"
                ),
                example_config={"asset_type": "reciprocating_compressor", "rated_pressure_mpa": 1.0, "metrics": ["discharge_pressure", "discharge_temp", "vibration", "oil_pressure"]},
                term_mapping={
                    "风机": "压缩机组", "风电场": "压缩机站", "机组": "压缩机组",
                    "叶片": "活塞", "齿轮箱": "曲轴箱", "发电机": "驱动电机",
                    "主轴承": "曲轴轴承", "偏航": "负荷调节", "变桨": "气阀调节",
                    "塔筒": "机身", "风速": "进气流量", "风向": "级间压比",
                    "turbine": "compressor", "gearbox": "crankcase", "blade": "piston",
                    "generator": "motor", "wind_speed": "suction_flow",
                    "nacelle": "compressor_frame", "yaw": "load_control", "pitch": "valve_control",
                },
                metric_mapping={
                    "有功功率kW": "轴功率kW", "风速m/s": "排气压力MPa",
                    "齿轮箱油温°C": "排气温度°C", "振动mm/s": "缸体振动mm/s",
                    "发电机转速rpm": "压缩机转速rpm",
                },
                fault_mapping={
                    "齿轮箱磨损": "活塞环磨损", "主轴承故障": "轴承故障",
                    "叶片裂纹": "气阀故障", "变桨系统异常": "气缸泄漏",
                    "发电机绕组过热": "油路堵塞",
                },
            ),
        ]

        return [
            {
                "name": t.name,
                "domain": t.domain,
                "key_entities": t.key_entities,
                "key_metrics": t.key_metrics,
                "fault_types": t.fault_types,
                "adapter_notes": t.adapter_notes,
                "example_config": t.example_config,
                "term_mapping": t.term_mapping,
                "metric_mapping": t.metric_mapping,
                "fault_mapping": t.fault_mapping,
                "instantiation": {
                    "script": "backend/scripts/instantiate_industry_template.py",
                    "command": f"python scripts/instantiate_industry_template.py {t.name}",
                    "output_dir": f"backend/exports/{t.name}/",
                    "note": "生成可运行适配包：映射后的 playbook 知识库 + OpenAPI + 客户端 SDK + README + 校验清单。",
                },
            }
            for t in templates
        ]

    def get_third_party_inventory(self) -> dict[str, Any]:
        """Return third-party dependency and license inventory."""
        return {
            "dependencies": [
                {"name": "FastAPI", "version": ">=0.100.0", "license": "MIT"},
                {"name": "SQLAlchemy", "version": ">=2.0", "license": "MIT"},
                {"name": "Alembic", "version": ">=1.13", "license": "MIT"},
                {"name": "Pydantic", "version": ">=2.0", "license": "MIT"},
                {"name": "NumPy", "version": ">=1.24", "license": "BSD-3-Clause"},
                {"name": "Uvicorn", "version": ">=0.23", "license": "BSD-3-Clause"},
                {"name": "React", "version": ">=18", "license": "MIT"},
                {"name": "Vite", "version": ">=5", "license": "MIT"},
                {"name": "TypeScript", "version": ">=5", "license": "Apache-2.0"},
                {"name": "Tailwind CSS", "version": ">=3", "license": "MIT"},
            ],
            "optional_dependencies": [
                {"name": "asyncua", "version": ">=1.0", "license": "LGPL-3.0", "note": "OPC UA connectivity"},
                {"name": "cryptography", "version": ">=41", "license": "Apache-2.0", "note": "Ed25519 audit signatures"},
                {"name": "playwright", "version": ">=1.40", "license": "Apache-2.0", "note": "E2E testing"},
            ],
            "data_sources": [
                {"name": "CARE Dataset", "license": "CC BY 4.0", "url": "https://www.nrel.gov/grid/care.html"},
                {"name": "ERA5", "license": "Copernicus License", "url": "https://cds.climate.copernicus.eu"},
                {"name": "Open-Meteo", "license": "CC BY 4.0", "url": "https://open-meteo.com"},
            ],
            "commercial_api_usage": [
                {"name": "通义千问 (DashScope)", "provider": "Alibaba Cloud", "purpose": "LLM辅助诊断解释"},
                {"name": "OpenAI API", "provider": "OpenAI", "purpose": "可选LLM后端"},
            ],
        }
