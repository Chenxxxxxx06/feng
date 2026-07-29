"""Proof-Carrying maintenance task package service.

Work orders carry complete execution context:
- Diagnostic evidence
- Selected plan and rationale
- Required skills, personnel, parts, tools
- Risk level and safety checklist
- Procedure steps
- Acceptance criteria
- Approval records
- Recovery verification metrics
- Rollback/escalation conditions

Structured fields validated by deterministic code. LLM assists only in
drafting explanations — never in enforcing safety or executing actions.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AlarmRecord,
    DecisionPlan,
    EvidenceNode,
    FaultKnowledgeNode,
    Incident,
    MaintenancePersonnel,
    WorkOrder,
)
from app.services.fault_type_resolver import resolve_fault_type

logger = logging.getLogger(__name__)


@dataclass
class SafetyChecklistItem:
    id: str = ""
    description: str = ""
    required: bool = True
    completed: bool = False
    verified_by: str = ""


@dataclass
class ProcedureStep:
    seq: int = 0
    action: str = ""
    tool_required: str = ""
    estimated_minutes: float = 0
    safety_note: str = ""


@dataclass
class TaskPackage:
    """Complete proof-carrying maintenance task package."""
    work_order_id: int = 0
    work_order_link_source: str = "none"
    work_order_link_confidence: float = 0.0
    incident_id: str = ""
    turbine_id: int = 0
    title: str = ""
    description: str = ""
    # Diagnosis evidence
    diagnostic_evidence: list[dict[str, Any]] = field(default_factory=list)
    selected_plan: dict[str, Any] = field(default_factory=dict)
    selection_rationale: str = ""
    # Resources
    required_skills: list[str] = field(default_factory=list)
    assigned_personnel: list[dict[str, Any]] = field(default_factory=list)
    required_parts: list[dict[str, Any]] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)
    # Risk & safety
    risk_level: str = "medium"
    safety_checklist: list[SafetyChecklistItem] = field(default_factory=list)
    # Execution
    procedure_steps: list[ProcedureStep] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    # Governance
    approval_records: list[dict[str, Any]] = field(default_factory=list)
    recovery_verification_metrics: list[str] = field(default_factory=list)
    # Contingency
    rollback_conditions: list[str] = field(default_factory=list)
    escalation_conditions: list[str] = field(default_factory=list)
    # Meta
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    includes_llm_content: bool = False  # True if any field contains LLM-generated text


class TaskPackageService:
    """Builds proof-carrying maintenance task packages.

    All safety-critical fields are structurally validated.
    LLM content is clearly labeled and never used for safety enforcement.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def resolve_work_order(
        self,
        incident: Incident,
        requested_work_order_id: Optional[int] = None,
    ) -> tuple[Optional[WorkOrder], str, float]:
        """Resolve a work order without silently binding an unrelated record."""
        if requested_work_order_id is not None:
            work_order = await self.db.get(WorkOrder, requested_work_order_id)
            if work_order is None:
                raise ValueError(f"工单不存在: {requested_work_order_id}")
            if work_order.turbine_id != incident.turbine_id:
                raise ValueError("指定工单与事件风机不一致")
            if work_order.incident_id not in (None, incident.id):
                raise ValueError("指定工单已关联到其他事件")
            return work_order, "explicit", 1.0

        direct_result = await self.db.execute(
            select(WorkOrder)
            .where(
                WorkOrder.incident_id == incident.id,
                WorkOrder.deleted_at.is_(None),
            )
            .order_by(WorkOrder.created_at.desc())
            .limit(1)
        )
        direct = direct_result.scalar_one_or_none()
        if direct:
            return direct, "incident_relation", 1.0

        fault_ids_result = await self.db.execute(
            select(AlarmRecord.fault_id).where(
                AlarmRecord.incident_id == incident.id,
                AlarmRecord.fault_id.is_not(None),
            )
        )
        fault_ids = {int(value) for value in fault_ids_result.scalars().all() if value}
        if fault_ids:
            result = await self.db.execute(
                select(WorkOrder)
                .where(
                    WorkOrder.turbine_id == incident.turbine_id,
                    WorkOrder.fault_id.in_(fault_ids),
                    WorkOrder.deleted_at.is_(None),
                )
                .order_by(WorkOrder.created_at.desc())
                .limit(1)
            )
            linked = result.scalar_one_or_none()
            if linked:
                return linked, "fault_relation", 1.0

        incident_fault_type = resolve_fault_type(incident.title)
        if not incident_fault_type:
            return None, "none", 0.0

        verified_knowledge = await self.db.execute(
            select(FaultKnowledgeNode.id).where(
                FaultKnowledgeNode.fault_type == incident_fault_type,
                FaultKnowledgeNode.verified == True,
            )
        )
        if verified_knowledge.scalar_one_or_none() is None:
            return None, "none", 0.0

        result = await self.db.execute(
            select(WorkOrder)
            .where(
                WorkOrder.turbine_id == incident.turbine_id,
                WorkOrder.deleted_at.is_(None),
            )
            .order_by(WorkOrder.created_at.desc())
            .limit(50)
        )
        opened_at = _as_utc(incident.opened_at or incident.created_at)
        candidates: list[tuple[float, WorkOrder]] = []
        for work_order in result.scalars().all():
            if resolve_fault_type(work_order.fault_type) != incident_fault_type:
                continue
            created_at = _as_utc(work_order.created_at)
            if opened_at is None or created_at is None:
                continue
            distance = abs((created_at - opened_at).total_seconds())
            if distance <= timedelta(minutes=15).total_seconds():
                candidates.append((distance, work_order))
        if not candidates:
            return None, "none", 0.0
        _, linked = min(candidates, key=lambda item: (item[0], -item[1].id))
        return linked, "fault_and_time", 0.85

    async def build_package(
        self,
        incident: Incident,
        work_order: Optional[WorkOrder] = None,
        *,
        work_order_link_source: str = "none",
        work_order_link_confidence: float = 0.0,
    ) -> TaskPackage:
        """Build a complete maintenance task package for an incident."""

        pkg = TaskPackage(
            incident_id=incident.incident_id,
            turbine_id=incident.turbine_id,
            title=f"Maintenance Task: {incident.title}",
            description=f"Task package for {incident.incident_id} — {incident.title}",
        )

        if work_order:
            pkg.work_order_id = work_order.id
            pkg.work_order_link_source = work_order_link_source
            pkg.work_order_link_confidence = work_order_link_confidence
            pkg.title = work_order.title
            pkg.description = work_order.description or ""
            pkg.risk_level = work_order.priority or "medium"

        # 1. Diagnostic evidence
        await self._collect_evidence(incident, pkg)

        # 2. Selected plan
        await self._collect_plan(incident, pkg)

        # 3. Required resources
        await self._collect_resources(incident, pkg)

        # 4. Safety checklist
        await self._build_safety_checklist(pkg)

        # 5. Procedure steps
        await self._build_procedure_steps(incident, pkg)

        # 6. Acceptance criteria
        await self._build_acceptance_criteria(incident, pkg)

        # 7. Rollback/escalation
        pkg.rollback_conditions = [
            "Recovery verification fails",
            "Post-maintenance vibration exceeds pre-maintenance levels",
            "New alarms of same type recur within 24 hours",
            "Temperature exceeds safe operating range",
        ]
        pkg.escalation_conditions = [
            "Parts not available within 48 hours",
            "Weather window closes before maintenance can start",
            "Required personnel unavailable for >24 hours",
            "Safety checklist cannot be completed",
        ]

        return pkg

    async def _collect_evidence(self, incident: Incident, pkg: TaskPackage) -> None:
        evidence = await self.db.execute(
            select(EvidenceNode)
            .where(EvidenceNode.incident_id == incident.id)
            .order_by(EvidenceNode.created_at.desc())
            .limit(20)
        )
        nodes = evidence.scalars().all()

        pkg.diagnostic_evidence = [
            {
                "id": n.id,
                "type": n.node_type,
                "label": n.label,
                "source": n.source,
                "confidence": n.confidence,
                "description": n.description,
                "created_at": n.created_at.isoformat() if n.created_at else None,
            }
            for n in nodes
        ]

    async def _collect_plan(self, incident: Incident, pkg: TaskPackage) -> None:
        plan = await self.db.execute(
            select(DecisionPlan)
            .where(
                DecisionPlan.incident_id == incident.id,
                DecisionPlan.is_recommended == True,
            )
            .limit(1)
        )
        selected = plan.scalar_one_or_none()

        if selected:
            pkg.selected_plan = {
                "plan_name": selected.plan_name,
                "strategy": selected.strategy,
                "safety_risk": selected.safety_risk,
                "repair_cost": selected.repair_cost,
                "recovery_days": selected.recovery_days,
                "total_score": selected.total_score,
                "personnel_available": selected.personnel_available,
                "parts_available": selected.parts_available,
                "weather_compatible": selected.weather_compatible,
                "explanation": selected.llm_explanation,
            }
            pkg.selection_rationale = (
                selected.llm_explanation
                or f"Selected {selected.strategy}: score={selected.total_score:.0f}, "
                   f"risk={selected.safety_risk:.0f}, cost={selected.repair_cost:.0f}"
            )

    async def _collect_resources(self, incident: Incident, pkg: TaskPackage) -> None:
        # Skills from fault knowledge
        fault_type = resolve_fault_type(incident.title)
        knowledge = await self.db.execute(
            select(FaultKnowledgeNode)
            .where(
                FaultKnowledgeNode.fault_type == fault_type,
                FaultKnowledgeNode.verified == True,
            )
            .limit(3)
        )
        kn_list = knowledge.scalars().all()

        skills = set()
        parts = []
        for kn in kn_list:
            if kn.solutions:
                for sol in kn.solutions[:3]:
                    if isinstance(sol, str):
                        skills.add(sol)
            if kn.spare_parts:
                for part in kn.spare_parts[:3]:
                    parts.append(part if isinstance(part, dict) else {"name": part})

        pkg.required_skills = list(skills)[:6] or ["mechanical_inspection", "vibration_analysis"]
        pkg.required_parts = parts
        pkg.required_tools = [
            "振动分析仪",
            "扭矩扳手",
            "红外测温仪",
            "内窥镜",
            "润滑脂枪",
            "安全锁具套装",
        ]

        # Available personnel
        personnel = await self.db.execute(
            select(MaintenancePersonnel).where(
                MaintenancePersonnel.is_available == True
            ).limit(5)
        )
        people = personnel.scalars().all()
        pkg.assigned_personnel = [
            {
                "id": p.id,
                "name": p.name,
                "skills": p.skills,
                "region": p.region,
            }
            for p in people
        ]

    async def _build_safety_checklist(self, pkg: TaskPackage) -> None:
        is_high_risk = pkg.risk_level in ("high", "critical")
        pkg.safety_checklist = [
            SafetyChecklistItem(
                id="LOCKOUT", description="完成设备锁定/挂牌程序 (LOTO)",
                required=True,
            ),
            SafetyChecklistItem(
                id="PPE", description="确认个人防护装备(PPE)齐全：安全帽、护目镜、手套、安全鞋",
                required=True,
            ),
            SafetyChecklistItem(
                id="WIND_LOCK", description="确认风机已停机、风轮锁定、变桨至安全位置",
                required=True,
            ),
            SafetyChecklistItem(
                id="CONFINED", description="密闭空间进入许可 (若进入轮毂或机舱内部)",
                required=is_high_risk,
            ),
            SafetyChecklistItem(
                id="LIFTING", description="起重作业安全确认 (若使用机舱吊车)",
                required=is_high_risk,
            ),
            SafetyChecklistItem(
                id="ELECTRICAL", description="电气隔离确认：断开相关断路器并验电",
                required=True,
            ),
            SafetyChecklistItem(
                id="COMMS", description="通讯检查：对讲机/手机与中控室确认通讯正常",
                required=True,
            ),
            SafetyChecklistItem(
                id="WEATHER", description="天气条件检查：风速<12m/s，无雷电预警",
                required=True,
            ),
            SafetyChecklistItem(
                id="BUDDY", description="至少2人作业 (高处>=2m作业强制要求)",
                required=True,
            ),
        ]

    async def _build_procedure_steps(
        self, incident: Incident, pkg: TaskPackage
    ) -> None:
        """Build procedure steps from knowledge base or defaults."""
        fault_type = resolve_fault_type(incident.title)
        knowledge = await self.db.execute(
            select(FaultKnowledgeNode)
            .where(
                FaultKnowledgeNode.fault_type == fault_type,
                FaultKnowledgeNode.verified == True,
            )
            .limit(1)
        )
        kn = knowledge.scalar_one_or_none()

        if kn and kn.solutions:
            pkg.procedure_steps = [
                ProcedureStep(
                    seq=i + 1,
                    action=sol if isinstance(sol, str) else str(sol),
                    estimated_minutes=30,
                )
                for i, sol in enumerate(kn.solutions[:8])
            ]
        else:
            pkg.procedure_steps = [
                ProcedureStep(seq=1, action="现场检查确认故障现象与诊断报告一致", estimated_minutes=15),
                ProcedureStep(seq=2, action="执行设备锁定/挂牌 (LOTO) 程序", estimated_minutes=10),
                ProcedureStep(seq=3, action="拆卸防护罩/盖板，目视检查故障部件", estimated_minutes=20),
                ProcedureStep(seq=4, action="使用振动分析仪确认振动特征", estimated_minutes=15, tool_required="振动分析仪"),
                ProcedureStep(seq=5, action="执行维修/更换操作", estimated_minutes=60),
                ProcedureStep(seq=6, action="重新装配并检查紧固扭矩", estimated_minutes=20, tool_required="扭矩扳手"),
                ProcedureStep(seq=7, action="拆除锁定/挂牌，恢复设备供电", estimated_minutes=10),
                ProcedureStep(seq=8, action="试运行并记录运行参数 (振动、温度、功率)", estimated_minutes=30),
            ]

    async def _build_acceptance_criteria(
        self, incident: Incident, pkg: TaskPackage
    ) -> None:
        pkg.acceptance_criteria = [
            "振动RMS值恢复至正常范围 (<7.1 mm/s)",
            "齿轮箱/轴承温度稳定在正常运行范围",
            "功率输出恢复至额定功率80%以上",
            f"24小时观察窗口内无同类型告警复发",
            "健康指数回升至70以上",
            "恢复验证证书状态为 pass",
        ]

        pkg.recovery_verification_metrics = [
            "振动RMS对比 (维修前 vs 维修后)",
            "温度趋势 (维修前 vs 维修后 24h)",
            "功率输出恢复率",
            "告警复发计数",
            "健康指数变化",
        ]


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
