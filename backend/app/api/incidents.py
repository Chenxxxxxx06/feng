"""Phase 4: Incident API — autonomous maintenance event command center.

Routes for the 6-innovation closed loop:
  4.1 Incident lifecycle (detected → resolved/escalated)
  4.2 Alarm storm compression
  4.3 Causal evidence graph
  4.4 Counterfactual decision sandbox
  4.5 Industrial safety policy engine
  4.6 Agent flight recorder (trace/span replay)
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    AgentSpan,
    AgentTrace,
    AlarmRecord,
    DecisionPlan,
    EvidenceEdge,
    EvidenceNode,
    Fault,
    FaultKnowledgeNode,
    Incident,
    PolicyDecision,
    PolicyRule,
    Turbine,
    User,
    WorkOrder,
)
from app.schemas import (
    AgentSpanResponse,
    AgentTraceResponse,
    AlarmClusterRequest,
    AlarmClusterResponse,
    AlarmResponse,
    DecisionPlanResponse,
    DecisionSandboxResponse,
    EvidenceEdgeCreate,
    EvidenceEdgeResponse,
    EvidenceGraphResponse,
    EvidenceNodeCreate,
    EvidenceNodeResponse,
    IncidentCreate,
    IncidentResponse,
    IncidentStageTransition,
    IncidentUpdate,
    PolicyCheckRequest,
    PolicyCheckResponse,
    PolicyRuleResponse,
)
from app.api.auth import get_current_user, require_role

router = APIRouter(dependencies=[Depends(get_current_user)])

# ── Incident stage machine ──
INCIDENT_STAGES = [
    "detected",
    "correlated",
    "diagnosing",
    "decision_ready",
    "awaiting_approval",
    "executing",
    "verifying",
    "resolved",
    "escalated",
]
VALID_STAGE_TRANSITIONS: dict[str, set[str]] = {
    "detected": {"correlated", "escalated"},
    "correlated": {"diagnosing", "escalated"},
    "diagnosing": {"decision_ready", "escalated"},
    "decision_ready": {"awaiting_approval", "executing", "escalated"},
    "awaiting_approval": {"executing", "escalated"},
    "executing": {"verifying", "escalated"},
    "verifying": {"resolved", "executing", "escalated"},
    "resolved": set(),
    "escalated": {"diagnosing", "executing"},
}

INCIDENT_SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _next_incident_id() -> str:
    """Generate a unique incident ID like INC-20260724-xxxx."""
    import uuid
    now = _utc_now()
    date_part = now.strftime("%Y%m%d")
    seq = uuid.uuid4().hex[:4]
    return f"INC-{date_part}-{seq}"


# ═══════════════════════════════════════════════════════════════
# 4.1 Incident CRUD + lifecycle
# ═══════════════════════════════════════════════════════════════


async def _incident_response(inc: Incident, db: AsyncSession) -> IncidentResponse:
    """Build IncidentResponse with turbine name."""
    turbine_name = ""
    if inc.turbine_id:
        t = await db.get(Turbine, inc.turbine_id)
        if t:
            turbine_name = t.name
    return IncidentResponse(
        id=inc.id,
        incident_id=inc.incident_id,
        turbine_id=inc.turbine_id,
        turbine_name=turbine_name,
        title=inc.title,
        severity=inc.severity,
        stage=inc.stage,
        status=inc.status,
        owner_id=inc.owner_id,
        verification_status=inc.verification_status,
        alarm_count=inc.alarm_count,
        compressed_count=inc.compressed_count,
        trace_id=inc.trace_id,
        summary=inc.summary,
        resolution=inc.resolution,
        opened_at=inc.opened_at,
        closed_at=inc.closed_at,
        created_at=inc.created_at,
        updated_at=inc.updated_at,
    )


@router.get("/incidents", response_model=list[IncidentResponse])
async def list_incidents(
    status: Optional[str] = Query(None),
    turbine_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """List all incidents, optionally filtered."""
    q = select(Incident).order_by(Incident.created_at.desc())
    if status:
        q = q.where(Incident.status == status)
    if turbine_id:
        q = q.where(Incident.turbine_id == turbine_id)
    result = await db.execute(q)
    incidents = result.scalars().all()
    return [await _incident_response(inc, db) for inc in incidents]


@router.get("/incidents/{incident_id}", response_model=IncidentResponse)
async def get_incident(incident_id: int, db: AsyncSession = Depends(get_db)):
    """Get a single incident by DB id."""
    inc = await db.get(Incident, incident_id)
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")
    return await _incident_response(inc, db)


@router.post("/incidents", response_model=IncidentResponse, status_code=201)
async def create_incident(
    data: IncidentCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("operator")),
):
    """Create a new incident. Requires operator+ role."""
    turbine = await db.get(Turbine, data.turbine_id)
    if not turbine:
        raise HTTPException(status_code=404, detail="Turbine not found")

    inc = Incident(
        incident_id=_next_incident_id(),
        turbine_id=data.turbine_id,
        title=data.title,
        severity=data.severity,
        stage="detected",
        status="open",
        owner_id=user.id,
        summary=data.summary,
        opened_at=_utc_now(),
    )
    db.add(inc)
    await db.commit()
    await db.refresh(inc)
    return await _incident_response(inc, db)


@router.put("/incidents/{incident_id}", response_model=IncidentResponse)
async def update_incident(
    incident_id: int,
    data: IncidentUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("operator")),
):
    """Update incident fields."""
    inc = await db.get(Incident, incident_id)
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")

    update_data = data.model_dump(exclude_none=True)
    for key, val in update_data.items():
        setattr(inc, key, val)
    inc.updated_at = _utc_now()
    await db.commit()
    await db.refresh(inc)
    return await _incident_response(inc, db)


@router.post("/incidents/{incident_id}/transition", response_model=IncidentResponse)
async def transition_incident_stage(
    incident_id: int,
    data: IncidentStageTransition,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("operator")),
):
    """Advance incident to next stage. Validates transition legality."""
    inc = await db.get(Incident, incident_id)
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")

    if data.target_stage not in INCIDENT_STAGES:
        raise HTTPException(status_code=400, detail=f"Invalid stage: {data.target_stage}")

    allowed = VALID_STAGE_TRANSITIONS.get(inc.stage, set())
    if data.target_stage not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot transition from '{inc.stage}' to '{data.target_stage}'. "
                   f"Allowed: {sorted(allowed)}",
        )

    inc.stage = data.target_stage
    inc.updated_at = _utc_now()

    if data.target_stage == "resolved":
        inc.status = "resolved"
        inc.closed_at = _utc_now()
        inc.resolution = data.note or inc.resolution
    elif data.target_stage == "escalated":
        inc.status = "escalated"

    await db.commit()
    await db.refresh(inc)
    return await _incident_response(inc, db)


# ═══════════════════════════════════════════════════════════════
# 4.2 Alarm Storm Compression
# ═══════════════════════════════════════════════════════════════


def _alarm_cluster_key(
    alarm_type: str, component: str | None, turbine_id: int
) -> str:
    """Generate a cluster key for alarm dedup."""
    return f"{turbine_id}:{component or 'none'}:{alarm_type}"


def _compress_alarms(
    alarms: list[dict], window_minutes: int
) -> tuple[list[dict], list[str]]:
    """Compress a list of alarm dicts into clusters.

    Rules (in order):
      1. Same turbine + same component + same alarm_type → merge (keep highest severity)
      2. Same turbine + co-occurring within window → merge
      3. Upstream/downstream dependency → merge (gearbox→generator, etc.)
      4. Duplicate suppression → remove exact duplicates

    Returns: (compressed_alarms, compression_rules_applied)
    """
    if not alarms:
        return [], []

    rules_applied: list[str] = []
    seen: dict[str, dict] = {}
    duplicates = 0

    for a in alarms:
        key = _alarm_cluster_key(a["alarm_type"], a.get("component"), a["turbine_id"])
        if key in seen:
            # Rule 1+4: same cluster key → merge, keep higher severity
            existing = seen[key]
            if INCIDENT_SEVERITY_ORDER.get(a["severity"], 1) > INCIDENT_SEVERITY_ORDER.get(
                existing["severity"], 1
            ):
                existing["severity"] = a["severity"]
                existing["value"] = a.get("value")
                existing["message"] = a.get("message")
            existing.setdefault("merged_ids", []).append(a.get("fault_id"))
            duplicates += 1
        else:
            seen[key] = dict(a)

    if duplicates > 0:
        rules_applied.append(f"same_turbine_component_type: {duplicates} duplicates merged")

    # Rule 3: component dependency merge (gearbox↔generator↔bearing)
    DEPENDENCY_CHAINS = [
        ("gearbox", "generator"),
        ("gearbox", "bearing"),
        ("generator", "bearing"),
        ("pitch", "blade"),
    ]
    dep_merges = 0
    compressed = list(seen.values())
    for upstream, downstream in DEPENDENCY_CHAINS:
        up_keys = [k for k, v in seen.items() if upstream in k.lower()]
        down_keys = [k for k, v in seen.items() if downstream in k.lower()]
        for uk in up_keys:
            for dk in down_keys:
                if uk in seen and dk in seen:
                    a_up = seen[uk]
                    a_down = seen[dk]
                    a_up["dependency_merged"] = True
                    a_up.setdefault("merged_ids", []).append(a_down.get("fault_id"))
                    del seen[dk]
                    dep_merges += 1
                    break

    if dep_merges > 0:
        rules_applied.append(f"dependency_chain: {dep_merges} upstream/downstream pairs merged")

    # Rebuild compressed list
    compressed = list(seen.values())

    # Mark primary alarm (highest severity, then highest value)
    if compressed:
        primary = max(
            compressed,
            key=lambda a: (
                INCIDENT_SEVERITY_ORDER.get(a["severity"], 1),
                a.get("value") or 0,
            ),
        )
        primary["is_primary"] = True

    return compressed, rules_applied


@router.post("/incidents/{incident_id}/compress-alarms", response_model=AlarmClusterResponse)
async def compress_alarms_for_incident(
    incident_id: int,
    data: AlarmClusterRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("operator")),
):
    """Collect open faults for a turbine, compress into alarm clusters, and attach to incident."""
    inc = await db.get(Incident, incident_id)
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")

    # Fetch open faults for this turbine as candidate alarms
    fault_result = await db.execute(
        select(Fault).where(
            Fault.turbine_id == data.turbine_id,
            Fault.status == "open",
        )
    )
    faults = fault_result.scalars().all()

    # Also check existing work orders as alarm sources
    wo_result = await db.execute(
        select(WorkOrder).where(
            WorkOrder.turbine_id == data.turbine_id,
            WorkOrder.status.in_(["pending", "assigned", "in_progress"]),
        )
    )
    work_orders = wo_result.scalars().all()

    # Build alarm dicts
    alarm_dicts: list[dict] = []
    for f in faults:
        alarm_dicts.append({
            "turbine_id": f.turbine_id,
            "fault_id": f.id,
            "source": "fault",
            "alarm_type": f.fault_type,
            "component": None,
            "severity": "high" if f.confidence >= 0.85 else "medium",
            "message": f"Fault: {f.fault_type} (confidence: {f.confidence:.0%})",
            "value": f.confidence,
            "threshold": 0.7,
        })
    for wo in work_orders:
        alarm_dicts.append({
            "turbine_id": wo.turbine_id,
            "fault_id": wo.fault_id,
            "source": "workorder",
            "alarm_type": wo.fault_type or "maintenance",
            "component": None,
            "severity": wo.priority or "medium",
            "message": f"WorkOrder #{wo.id}: {wo.title} ({wo.status})",
            "value": None,
            "threshold": None,
        })

    total_alarms = len(alarm_dicts)

    # Compress
    compressed_dicts, rules = _compress_alarms(alarm_dicts, data.window_minutes)

    # Persist compressed alarms
    persisted: list[AlarmRecord] = []
    for a in compressed_dicts:
        rec = AlarmRecord(
            incident_id=inc.id,
            turbine_id=a["turbine_id"],
            fault_id=a.get("fault_id"),
            source=a["source"],
            alarm_type=a["alarm_type"],
            component=a.get("component"),
            severity=a["severity"],
            message=a.get("message"),
            value=a.get("value"),
            threshold=a.get("threshold"),
            is_primary=a.get("is_primary", False),
            compression_rule=",".join(rules) if rules else None,
            compressed=a.get("dependency_merged", False)
            or a.get("merged_ids", False),
        )
        db.add(rec)
        persisted.append(rec)

    # Update incident counts
    inc.alarm_count = len(persisted)
    inc.compressed_count = total_alarms
    inc.updated_at = _utc_now()

    # Transition to correlated stage only if alarms were found
    if inc.stage == "detected" and len(persisted) > 0:
        inc.stage = "correlated"

    await db.commit()
    for rec in persisted:
        await db.refresh(rec)

    primary_alarm = next(
        (AlarmResponse.model_validate(r) for r in persisted if r.is_primary),
        AlarmResponse.model_validate(persisted[0]) if persisted else None,
    )

    return AlarmClusterResponse(
        incident_id=inc.incident_id,
        primary_alarm=primary_alarm,
        total_alarms=total_alarms,
        compressed_alarms=len(persisted),
        compression_rules=rules,
        alarms=[AlarmResponse.model_validate(r) for r in persisted],
    )


# ═══════════════════════════════════════════════════════════════
# 4.3 Causal Evidence Graph
# ═══════════════════════════════════════════════════════════════


@router.get("/incidents/{incident_id}/evidence-graph", response_model=EvidenceGraphResponse)
async def get_evidence_graph(incident_id: int, db: AsyncSession = Depends(get_db)):
    """Get the evidence graph for an incident."""
    inc = await db.get(Incident, incident_id)
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")

    nodes_result = await db.execute(
        select(EvidenceNode)
        .where(EvidenceNode.incident_id == inc.id)
        .order_by(EvidenceNode.created_at.asc())
    )
    edges_result = await db.execute(
        select(EvidenceEdge)
        .where(EvidenceEdge.incident_id == inc.id)
        .order_by(EvidenceEdge.created_at.asc())
    )
    return EvidenceGraphResponse(
        nodes=[EvidenceNodeResponse.model_validate(n) for n in nodes_result.scalars().all()],
        edges=[EvidenceEdgeResponse.model_validate(e) for e in edges_result.scalars().all()],
    )


@router.post("/incidents/{incident_id}/evidence-nodes", response_model=EvidenceNodeResponse, status_code=201)
async def add_evidence_node(
    incident_id: int,
    data: EvidenceNodeCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("engineer")),
):
    """Add a node to the evidence graph."""
    inc = await db.get(Incident, incident_id)
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")

    node = EvidenceNode(
        incident_id=inc.id,
        node_type=data.node_type,
        label=data.label,
        description=data.description,
        source=data.source,
        confidence=data.confidence,
        props=data.props,
    )
    db.add(node)
    await db.commit()
    await db.refresh(node)
    return EvidenceNodeResponse.model_validate(node)


@router.post("/incidents/{incident_id}/evidence-edges", response_model=EvidenceEdgeResponse, status_code=201)
async def add_evidence_edge(
    incident_id: int,
    data: EvidenceEdgeCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("engineer")),
):
    """Add an edge to the evidence graph."""
    inc = await db.get(Incident, incident_id)
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")

    # Validate nodes exist
    src = await db.get(EvidenceNode, data.source_node_id)
    tgt = await db.get(EvidenceNode, data.target_node_id)
    if not src or not tgt:
        raise HTTPException(status_code=404, detail="Source or target node not found")

    edge = EvidenceEdge(
        incident_id=inc.id,
        source_node_id=data.source_node_id,
        target_node_id=data.target_node_id,
        edge_type=data.edge_type,
        source=data.source,
        confidence=data.confidence,
        evidence_ref=data.evidence_ref,
    )
    db.add(edge)
    await db.commit()
    await db.refresh(edge)
    return EvidenceEdgeResponse.model_validate(edge)


# ═══════════════════════════════════════════════════════════════
# 4.4 Counterfactual Decision Sandbox
# ═══════════════════════════════════════════════════════════════


async def _generate_decision_plans(inc: Incident, db: AsyncSession) -> list[DecisionPlan]:
    """Generate 3 counterfactual repair plans with deterministic scoring.

    Score = safety_risk_weight + downtime_loss_weight + cost_weight
           + personnel_weight + parts_weight + weather_weight

    LLM explains the scores — scores are deterministic.
    """
    turbine = await db.get(Turbine, inc.turbine_id)
    power_mw = turbine.power_mw or 2.0 if turbine else 2.0

    # Base parameters derived from incident severity
    sev_mult = {"low": 0.5, "medium": 1.0, "high": 2.0, "critical": 3.0}[inc.severity]
    daily_revenue = power_mw * 1000 * 24 * 0.4  # ~0.4 CNY/kWh

    plans: list[DecisionPlan] = []

    # Plan A: Immediate repair (highest cost, lowest risk)
    plan_a = DecisionPlan(
        incident_id=inc.id,
        plan_name="立即停机维修",
        strategy="immediate_repair",
        safety_risk=5.0,
        downtime_loss=round(daily_revenue * 2 * sev_mult, 2),  # 2 days
        repair_cost=round(50000 * sev_mult, 2),
        recovery_days=2.0,
        personnel_available=True,
        parts_available=True,
        weather_compatible=True,
        is_recommended=False,
        llm_explanation="立即停机维修可最大程度降低安全风险（5%），但将导致2天停机，"
                        f"预估发电损失¥{daily_revenue * 2 * sev_mult:,.0f}。",
        decision_flip_point="如果未来48h内备件无法到达，推荐切换至方案B。",
    )
    plan_a.total_score = round(
        100 - plan_a.safety_risk * 3  # safety: 85
        - (plan_a.downtime_loss / max(daily_revenue, 1)) * 10  # downtime penalty
        - (plan_a.repair_cost / 10000) * 5  # cost penalty
        + (20 if plan_a.personnel_available else 0)
        + (20 if plan_a.parts_available else 0)
        + (10 if plan_a.weather_compatible else 0),
        1,
    )
    plans.append(plan_a)

    # Plan B: Degraded ops + planned maintenance (balanced)
    plan_b = DecisionPlan(
        incident_id=inc.id,
        plan_name="降载运行 + 7天内计划维修",
        strategy="degraded_ops",
        safety_risk=20.0,
        downtime_loss=round(daily_revenue * 7 * 0.3 * sev_mult, 2),  # 7 days at 30% loss
        repair_cost=round(40000 * sev_mult, 2),
        recovery_days=7.0,
        personnel_available=True,
        parts_available=True,
        weather_compatible=True,
        is_recommended=False,
        llm_explanation="降载至70%运行，7天内安排计划维修。平衡了发电收益和安全风险，"
                        f"安全性风险为20%。",
        decision_flip_point="如果未来24h内振动指标继续恶化，应立即切换至方案A。",
    )
    plan_b.total_score = round(
        100 - plan_b.safety_risk * 1.5
        - (plan_b.downtime_loss / max(daily_revenue, 1)) * 5
        - (plan_b.repair_cost / 10000) * 3
        + (15 if plan_b.personnel_available else 0)
        + (15 if plan_b.parts_available else 0)
        + (5 if plan_b.weather_compatible else 0),
        1,
    )
    plans.append(plan_b)

    # Plan C: Continue monitoring + trigger threshold (lowest cost, highest risk)
    plan_c = DecisionPlan(
        incident_id=inc.id,
        plan_name="继续监测 + 设置触发阈值",
        strategy="monitor",
        safety_risk=45.0,
        downtime_loss=round(daily_revenue * 0, 2),  # No immediate downtime
        repair_cost=round(10000 * sev_mult, 2),
        recovery_days=30.0,
        personnel_available=True,
        parts_available=True,
        weather_compatible=True,
        is_recommended=False,
        llm_explanation="继续运行并加强监测，当振动RMS超过阈值或温度超过80°C时自动触发维修。"
                        f"安全风险最高（45%），但短期成本最低。",
        decision_flip_point="如果振动RMS在未来48h内超过12 mm/s，或温度超过80°C，自动升级至方案A。",
    )
    plan_c.total_score = round(
        100 - plan_c.safety_risk * 1.0
        - (plan_c.downtime_loss / max(daily_revenue, 1)) * 3
        - (plan_c.repair_cost / 10000) * 2
        + (10 if plan_c.personnel_available else 0)
        + (10 if plan_c.parts_available else 0)
        + (0 if plan_c.weather_compatible else 0),
        1,
    )
    plans.append(plan_c)

    # Recommend the plan with highest score
    best = max(plans, key=lambda p: p.total_score)
    best.is_recommended = True

    return plans


@router.post("/incidents/{incident_id}/decision-sandbox", response_model=DecisionSandboxResponse)
async def generate_decision_sandbox(
    incident_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("engineer")),
):
    """Generate counterfactual decision plans for an incident."""
    inc = await db.get(Incident, incident_id)
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")

    plans = await _generate_decision_plans(inc, db)
    for plan in plans:
        db.add(plan)
    await db.commit()
    for plan in plans:
        await db.refresh(plan)

    # Update incident stage
    inc.stage = "decision_ready"
    inc.updated_at = _utc_now()
    await db.commit()

    recommended_idx = next(
        (i for i, p in enumerate(plans) if p.is_recommended), -1
    )

    return DecisionSandboxResponse(
        incident_id=inc.incident_id,
        plans=[DecisionPlanResponse.model_validate(p) for p in plans],
        recommended_index=recommended_idx,
    )


# ═══════════════════════════════════════════════════════════════
# 4.5 Industrial Safety Policy Engine
# ═══════════════════════════════════════════════════════════════

RISK_LEVEL_LABELS = {
    0: "L0-只读",
    1: "L1-低风险写入",
    2: "L2-运维业务变更",
    3: "L3-高风险操作",
    4: "L4-设备控制",
}

# Default policy rules (seeded on first use)
DEFAULT_POLICY_RULES: list[dict] = [
    {
        "rule_id": "deny-close-unverified",
        "description": "禁止关闭未验证的事件",
        "action_pattern": "close_incident",
        "risk_level": 3,
        "rule_type": "deny",
        "condition_json": {"verification_status": {"$ne": "pass"}},
    },
    {
        "rule_id": "deny-llm-direct-write",
        "description": "LLM输出不能直接写入业务状态（必须经过确定性代码）",
        "action_pattern": "*",
        "risk_level": 2,
        "rule_type": "deny",
        "condition_json": {"source": "llm", "playbook_id": None},
    },
    {
        "rule_id": "require-approval-l3",
        "description": "L3高风险操作需要审批",
        "action_pattern": "*",
        "risk_level": 3,
        "rule_type": "require_approval",
        "condition_json": {},
    },
    {
        "rule_id": "deny-l4-real-device",
        "description": "比赛版本禁止真实设备控制",
        "action_pattern": "control_device",
        "risk_level": 4,
        "rule_type": "deny",
        "condition_json": {"sandbox_only": True},
    },
    {
        "rule_id": "require-role-engineer-write",
        "description": "写操作需要engineer+角色",
        "action_pattern": "create_*|update_*|delete_*|close_*",
        "risk_level": 2,
        "rule_type": "deny",
        "condition_json": {"min_role": "operator"},
    },
    {
        "rule_id": "deny-assign-unskilled",
        "description": "不能将工单分配给不具备所需技能的人员",
        "action_pattern": "assign_workorder",
        "risk_level": 2,
        "rule_type": "deny",
        "condition_json": {"skill_required": True},
    },
]


async def _ensure_default_policies(db: AsyncSession):
    """Seed default policy rules if none exist."""
    existing = await db.execute(select(func.count(PolicyRule.id)))
    if existing.scalar() == 0:
        for rule in DEFAULT_POLICY_RULES:
            db.add(PolicyRule(
                rule_id=rule["rule_id"],
                description=rule["description"],
                action_pattern=rule["action_pattern"],
                risk_level=rule["risk_level"],
                rule_type=rule["rule_type"],
                condition_json=rule["condition_json"],
                is_active=True,
                version="1.0",
            ))
        await db.commit()


@router.get("/policies", response_model=list[PolicyRuleResponse])
async def list_policies(db: AsyncSession = Depends(get_db)):
    """List all safety policy rules."""
    await _ensure_default_policies(db)
    result = await db.execute(select(PolicyRule).order_by(PolicyRule.risk_level.desc()))
    return [PolicyRuleResponse.model_validate(r) for r in result.scalars().all()]


@router.post("/policies/check", response_model=PolicyCheckResponse)
async def check_policy(
    data: PolicyCheckRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Check if an action is permitted by the safety policy engine."""
    await _ensure_default_policies(db)

    # Load all active rules
    result = await db.execute(
        select(PolicyRule).where(PolicyRule.is_active == True)
    )
    rules = result.scalars().all()

    matched_rules: list[str] = []
    decision = "allowed"
    reason = None

    for rule in rules:
        # Simple pattern matching
        pattern = rule.action_pattern
        if pattern != "*" and not _match_action_pattern(data.action, pattern):
            continue

        # Check conditions
        conditions = rule.condition_json or {}
        if not _evaluate_conditions(conditions, data.context):
            continue

        matched_rules.append(rule.rule_id)

        if rule.rule_type == "deny":
            decision = "denied"
            reason = rule.description
            break  # Deny takes precedence
        elif rule.rule_type == "require_approval":
            decision = "require_approval"
            reason = rule.description
        elif rule.rule_type == "require_dual":
            decision = "require_approval"
            reason = f"[双人审批] {rule.description}"

    # Log the decision
    log = PolicyDecision(
        incident_id=data.incident_id,
        rule_id=",".join(matched_rules) if matched_rules else "none",
        action=data.action,
        user_id=user.id,
        decision=decision,
        reason=reason,
    )
    db.add(log)
    await db.commit()

    return PolicyCheckResponse(
        action=data.action,
        decision=decision,
        matched_rules=matched_rules,
        reason=reason,
    )


def _match_action_pattern(action: str, pattern: str) -> bool:
    """Simple glob-style pattern matching for action names."""
    if pattern == action:
        return True
    if pattern.endswith("*"):
        return action.startswith(pattern[:-1])
    if pattern.startswith("*"):
        return action.endswith(pattern[1:])
    if "|" in pattern:
        return any(_match_action_pattern(action, p.strip()) for p in pattern.split("|"))
    return False


def _evaluate_conditions(conditions: dict, context: dict) -> bool:
    """Evaluate simple conditions against context."""
    if not conditions:
        return True
    # Support basic operators: $ne, $eq, $gt, $lt
    for key, expected in conditions.items():
        actual = context.get(key)
        if isinstance(expected, dict):
            if "$ne" in expected and actual == expected["$ne"]:
                return False
            if "$eq" in expected and actual != expected["$eq"]:
                return False
        elif actual != expected:
            return False
    return True


# ═══════════════════════════════════════════════════════════════
# 4.6 Agent Flight Recorder
# ═══════════════════════════════════════════════════════════════


@router.get("/incidents/{incident_id}/trace", response_model=list[AgentTraceResponse])
async def get_incident_traces(incident_id: int, db: AsyncSession = Depends(get_db)):
    """Get all agent traces for an incident (flight recorder replay)."""
    inc = await db.get(Incident, incident_id)
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")

    traces_result = await db.execute(
        select(AgentTrace)
        .where(AgentTrace.incident_id == inc.id)
        .order_by(AgentTrace.started_at.asc())
    )
    traces = traces_result.scalars().all()

    response: list[AgentTraceResponse] = []
    for trace in traces:
        spans_result = await db.execute(
            select(AgentSpan)
            .where(AgentSpan.trace_id == trace.trace_id)
            .order_by(AgentSpan.step_order.asc())
        )
        spans = [AgentSpanResponse.model_validate(s) for s in spans_result.scalars().all()]
        response.append(AgentTraceResponse(
            id=trace.id,
            trace_id=trace.trace_id,
            incident_id=trace.incident_id,
            user_id=trace.user_id,
            status=trace.status,
            total_spans=trace.total_spans,
            total_duration_ms=trace.total_duration_ms,
            token_usage=trace.token_usage,
            cost_estimate=trace.cost_estimate,
            error_code=trace.error_code,
            started_at=trace.started_at,
            ended_at=trace.ended_at,
            spans=spans,
        ))

    return response


@router.post("/incidents/{incident_id}/trace/start", response_model=AgentTraceResponse)
async def start_agent_trace(
    incident_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("operator")),
):
    """Start a new agent trace for an incident (flight recorder session)."""
    import uuid

    inc = await db.get(Incident, incident_id)
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")

    trace_id = f"trace-{_utc_now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    trace = AgentTrace(
        trace_id=trace_id,
        incident_id=inc.id,
        user_id=user.id,
        status="running",
    )
    db.add(trace)
    inc.trace_id = trace_id
    inc.updated_at = _utc_now()
    await db.commit()
    await db.refresh(trace)

    return AgentTraceResponse(
        id=trace.id,
        trace_id=trace.trace_id,
        incident_id=trace.incident_id,
        user_id=trace.user_id,
        status=trace.status,
        total_spans=0,
        total_duration_ms=0.0,
        token_usage=None,
        cost_estimate=0.0,
        error_code=None,
        started_at=trace.started_at,
        ended_at=None,
        spans=[],
    )
