"""Multi-modal conflict & correlation analysis.

Compares evidence from different modalities (image, SCADA, vibration,
alarm, knowledge base) and generates typed evidence edges:

  - supports: evidence from two sources agree
  - contradicts: evidence conflict (needs investigation)
  - requires_check: additional data needed
  - caused_by: upstream cause identified
  - resolved_by: fix verified

Core innovation (P0-4): conflicting evidence is NOT hidden — it is
surfaced with possible explanations and next-step recommendations.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AlarmRecord,
    EvidenceEdge,
    EvidenceNode,
    FaultKnowledgeNode,
    Incident,
    SCADARecord,
    VibrationData,
)

logger = logging.getLogger(__name__)


@dataclass
class ModalityCheck:
    """One cross-modality comparison result."""
    source_type: str = ""       # image / scada / vibration / alarm / knowledge
    target_type: str = ""       # compared modality
    edge_type: str = ""         # supports / contradicts / requires_check / caused_by
    source_node_id: Optional[int] = None
    target_node_id: Optional[int] = None
    confidence: float = 0.5
    finding: str = ""
    explanation: str = ""
    recommendation: str = ""
    severity: str = "info"      # info / warning / error / critical


@dataclass
class ConflictReport:
    """Complete multi-modal conflict analysis report."""
    incident_id: str = ""
    checks: list[ModalityCheck] = field(default_factory=list)
    supports_count: int = 0
    contradicts_count: int = 0
    requires_check_count: int = 0
    generated_edges: list[dict] = field(default_factory=list)
    overall_assessment: str = ""
    evidence_sufficient: bool = False
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class MultimodalConflictService:
    """Cross-modality conflict detection and evidence edge generation."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def analyze_incident(self, incident: Incident) -> ConflictReport:
        """Run full multi-modal conflict analysis for an incident.

        Compares all available evidence modalities and generates
        typed evidence edges.
        """
        report = ConflictReport(incident_id=incident.incident_id)

        # ── Gather all evidence nodes for this incident ──
        ev_result = await self.db.execute(
            select(EvidenceNode)
            .where(EvidenceNode.incident_id == incident.id)
            .order_by(EvidenceNode.created_at.asc())
        )
        evidence_nodes = ev_result.scalars().all()

        if not evidence_nodes:
            report.overall_assessment = "无证据节点，无法进行多模态分析"
            report.evidence_sufficient = False
            return report

        # ── Collect modality data ──
        latest_scada = await self._get_latest_scada(incident.turbine_id)
        vibration_data = await self._get_recent_vibration(incident.turbine_id)
        alarms = await self._get_alarms(incident.id)
        knowledge_nodes = await self._get_knowledge_for_incident(incident)

        # ── Classify evidence by source ──
        image_ev = [e for e in evidence_nodes if e.source == "drone_inspection"]
        scada_ev = [e for e in evidence_nodes if e.source in ("scada", "rule")]
        vib_ev = [e for e in evidence_nodes if e.source == "vibration"]
        alarm_ev = [e for e in evidence_nodes if e.source in ("alarm", "fault_detection")]

        # ── Run cross-modality checks ──
        checks: list[ModalityCheck] = []

        # 1. Image vs SCADA
        if image_ev and latest_scada:
            checks.extend(self._check_image_vs_scada(image_ev, latest_scada))

        # 2. Image vs Vibration
        if image_ev and vibration_data:
            checks.extend(self._check_image_vs_vibration(image_ev, vibration_data))

        # 3. SCADA vs Vibration
        if scada_ev and vib_ev:
            checks.extend(self._check_scada_vs_vibration(scada_ev, vib_ev, latest_scada, vibration_data))

        # 4. Alarms vs Evidence
        if alarms and evidence_nodes:
            checks.extend(self._check_alarms_vs_evidence(alarms, evidence_nodes))

        # 5. Knowledge vs Observations
        if knowledge_nodes and evidence_nodes:
            checks.extend(self._check_knowledge_vs_observations(knowledge_nodes, evidence_nodes))

        # ── Generate evidence edges ──
        for check in checks:
            if check.source_node_id and check.target_node_id:
                edge = EvidenceEdge(
                    incident_id=incident.id,
                    source_node_id=check.source_node_id,
                    target_node_id=check.target_node_id,
                    edge_type=check.edge_type,
                    source="multimodal_analysis",
                    confidence=check.confidence,
                    evidence_ref=(
                        f"{check.finding}\n"
                        f"解释: {check.explanation}\n"
                        f"建议: {check.recommendation}"
                    ),
                )
                self.db.add(edge)
                report.generated_edges.append({
                    "source_id": check.source_node_id,
                    "target_id": check.target_node_id,
                    "edge_type": check.edge_type,
                    "confidence": check.confidence,
                    "finding": check.finding,
                })

        await self.db.flush()

        # ── Summary ──
        report.checks = checks
        report.supports_count = sum(1 for c in checks if c.edge_type == "supports")
        report.contradicts_count = sum(1 for c in checks if c.edge_type == "contradicts")
        report.requires_check_count = sum(1 for c in checks if c.edge_type == "requires_check")

        if report.contradicts_count > 0:
            report.overall_assessment = (
                f"发现 {report.contradicts_count} 处多模态证据冲突，"
                f"需要进一步调查。不建议在冲突解决前关闭事件。"
            )
            report.evidence_sufficient = False
        elif report.requires_check_count > 0:
            report.overall_assessment = (
                f"证据基本一致，但 {report.requires_check_count} 处需要补充检查。"
            )
            report.evidence_sufficient = report.requires_check_count <= 2
        else:
            report.overall_assessment = (
                f"多模态证据一致（{report.supports_count} 处支持），可进行诊断决策。"
            )
            report.evidence_sufficient = report.supports_count >= 1

        return report

    # ── Data gatherers ──

    async def _get_latest_scada(self, turbine_id: int) -> Optional[dict]:
        result = await self.db.execute(
            select(SCADARecord)
            .where(SCADARecord.turbine_id == turbine_id)
            .order_by(SCADARecord.timestamp.desc())
            .limit(1)
        )
        rec = result.scalar_one_or_none()
        if not rec:
            return None
        return {
            "power_kw": rec.power_kw,
            "wind_speed_ms": rec.wind_speed_ms,
            "rotor_rpm": rec.rotor_rpm,
            "gen_temperature_c": rec.gen_temperature_c,
            "gearbox_temperature_c": rec.gearbox_temperature_c,
            "bearing_temperature_c": rec.bearing_temperature_c,
            "timestamp": rec.timestamp,
        }

    async def _get_recent_vibration(self, turbine_id: int) -> list[dict]:
        result = await self.db.execute(
            select(VibrationData)
            .where(VibrationData.turbine_id == turbine_id)
            .order_by(VibrationData.timestamp.desc())
            .limit(5)
        )
        return [
            {
                "component": v.component,
                "rms": v.rms,
                "peak_freq_hz": v.peak_freq_hz,
                "timestamp": v.timestamp,
            }
            for v in result.scalars().all()
        ]

    async def _get_alarms(self, incident_id: int) -> list[dict]:
        result = await self.db.execute(
            select(AlarmRecord)
            .where(AlarmRecord.incident_id == incident_id)
            .order_by(AlarmRecord.fired_at.desc())
            .limit(10)
        )
        return [
            {
                "alarm_type": a.alarm_type,
                "severity": a.severity,
                "message": a.message,
                "value": a.value,
                "threshold": a.threshold,
            }
            for a in result.scalars().all()
        ]

    async def _get_knowledge_for_incident(self, incident: Incident) -> list[dict]:
        # Search knowledge by fault type keywords from incident title
        title = incident.title or ""
        result = await self.db.execute(
            select(FaultKnowledgeNode)
            .where(FaultKnowledgeNode.fault_type.ilike(f"%{title[:4]}%"))
            .limit(3)
        )
        nodes = result.scalars().all()
        if not nodes and title:
            # Broader search
            result = await self.db.execute(
                select(FaultKnowledgeNode).limit(3)
            )
            nodes = result.scalars().all()
        return [
            {
                "fault_type": n.fault_type,
                "category": n.category,
                "symptoms": n.symptoms,
                "root_causes": n.root_causes,
                "solutions": n.solutions,
            }
            for n in nodes
        ]

    # ── Cross-modality checkers ──

    def _check_image_vs_scada(
        self, image_ev: list[EvidenceNode], scada: dict
    ) -> list[ModalityCheck]:
        checks: list[ModalityCheck] = []
        for ev in image_ev:
            props = ev.props or {}
            defects = props.get("defects", [])
            has_damage = any(
                d.get("type") in ("leading_edge_erosion", "blade_crack", "blade_surface_damage", "blade_delamination")
                for d in defects
            )

            if not has_damage:
                # Image shows no damage, SCADA normal → supports (consistent normal)
                checks.append(ModalityCheck(
                    source_type="image", target_type="scada",
                    edge_type="supports",
                    source_node_id=ev.id,
                    confidence=0.85,
                    finding="图像与SCADA一致: 均未发现异常",
                    explanation="巡检图像未检出可见损伤，SCADA运行参数在正常范围内。",
                    recommendation="继续常规巡检计划。",
                ))
                continue

            # Image shows damage — check SCADA
            power_kw = scada.get("power_kw") or 0
            gear_temp = scada.get("gearbox_temperature_c") or 0
            bear_temp = scada.get("bearing_temperature_c") or 0

            power_normal = power_kw > 1400  # >70% of 2MW
            temp_normal = gear_temp < 80 and bear_temp < 75

            if power_normal and temp_normal:
                # Image shows damage but SCADA normal → CONFLICT
                checks.append(ModalityCheck(
                    source_type="image", target_type="scada",
                    edge_type="contradicts",
                    source_node_id=ev.id,
                    confidence=0.55,
                    severity="warning",
                    finding=f"图像发现缺陷但SCADA正常 (功率{power_kw:.0f}kW, 齿轮箱{gear_temp:.0f}°C)",
                    explanation=(
                        "叶片图像显示损伤但SCADA运行参数未受影响。可能原因: "
                        "(1)早期损伤尚未影响气动性能; "
                        "(2)缺陷面积小(<5%叶片面积); "
                        "(3)图像检测假阳性。"
                    ),
                    recommendation=(
                        "1. 检查振动RMS趋势确认机械状态; "
                        "2. 对比历史图像确认损伤是否扩大; "
                        "3. 降低检测阈值至0.6排除假阳性; "
                        "4. 暂不紧急停机，但需缩短巡检间隔至1周。"
                    ),
                ))
            elif not temp_normal:
                # Both image and SCADA show problems → supports
                checks.append(ModalityCheck(
                    source_type="image", target_type="scada",
                    edge_type="supports",
                    source_node_id=ev.id,
                    confidence=0.78,
                    finding=f"图像缺陷与SCADA异常一致 (齿轮箱{gear_temp:.0f}°C > 80°C)",
                    explanation="叶片损伤已导致气动不平衡，齿轮箱温度升高。",
                    recommendation="建议尽快安排停机维修。",
                ))
            else:
                checks.append(ModalityCheck(
                    source_type="image", target_type="scada",
                    edge_type="requires_check",
                    source_node_id=ev.id,
                    confidence=0.50,
                    finding="图像发现缺陷，SCADA功率偏低但温度正常",
                    explanation=f"功率{power_kw:.0f}kW偏低但温度正常，需振动数据交叉验证。",
                    recommendation="获取振动频谱数据后重新评估。",
                ))

        return checks

    def _check_image_vs_vibration(
        self, image_ev: list[EvidenceNode], vib_data: list[dict]
    ) -> list[ModalityCheck]:
        checks: list[ModalityCheck] = []
        if not vib_data:
            return checks

        # Check if any vibration RMS exceeds threshold
        high_vib = [v for v in vib_data if v.get("rms") and v["rms"] > 6.0]
        has_abnormal_vib = len(high_vib) > 0

        for ev in image_ev:
            props = ev.props or {}
            defects = props.get("defects", [])
            has_damage = any(
                d.get("type") in ("leading_edge_erosion", "blade_crack", "surface_damage")
                for d in defects
            )

            if has_damage and has_abnormal_vib:
                checks.append(ModalityCheck(
                    source_type="image", target_type="vibration",
                    edge_type="supports",
                    source_node_id=ev.id,
                    confidence=0.82,
                    finding=f"图像缺陷与振动异常一致 (RMS: {high_vib[0]['rms']:.1f} mm/s > 6.0)",
                    explanation="叶片损伤导致转子不平衡，振动RMS升高。",
                    recommendation="优先处理该风机叶片。",
                ))
            elif has_damage and not has_abnormal_vib:
                checks.append(ModalityCheck(
                    source_type="image", target_type="vibration",
                    edge_type="requires_check",
                    source_node_id=ev.id,
                    confidence=0.48,
                    finding="图像发现损伤但振动RMS正常",
                    explanation="早期叶片损伤可能不立即导致振动升高。建议持续监测振动趋势。",
                    recommendation="增加振动测量频率至每日一次。",
                ))

        return checks

    def _check_scada_vs_vibration(
        self, scada_ev: list[EvidenceNode], vib_ev: list[EvidenceNode],
        scada: Optional[dict], vib_data: list[dict],
    ) -> list[ModalityCheck]:
        checks: list[ModalityCheck] = []
        if not scada or not vib_data:
            return checks

        high_temp = (scada.get("gearbox_temperature_c") or 0) > 80
        high_vib = any(v.get("rms", 0) > 6.0 for v in vib_data)

        if high_temp and high_vib:
            for se in scada_ev:
                for ve in vib_ev:
                    checks.append(ModalityCheck(
                        source_type="scada", target_type="vibration",
                        edge_type="supports",
                        source_node_id=se.id, target_node_id=ve.id,
                        confidence=0.80,
                        finding="SCADA高温与振动异常一致，齿轮箱可能存在机械故障",
                        explanation="高温+高振动RMS→齿轮箱磨损或点蚀。",
                        recommendation="检查齿轮油液分析结果，准备齿轮箱内窥镜检查。",
                    ))
        elif high_temp != high_vib:
            checks.append(ModalityCheck(
                source_type="scada", target_type="vibration",
                edge_type="contradicts",
                confidence=0.45,
                finding=f"SCADA温度{'高' if high_temp else '正常'}但振动{'异常' if high_vib else '正常'}",
                explanation="温度和振动不一致可能意味着不同故障模式或传感器问题。",
                recommendation="检查传感器校准状态，获取更多数据点。",
            ))

        return checks

    def _check_alarms_vs_evidence(
        self, alarms: list[dict], evidence_nodes: list[EvidenceNode]
    ) -> list[ModalityCheck]:
        checks: list[ModalityCheck] = []
        if not alarms:
            return checks

        # If alarms exist but evidence nodes don't cover them
        alarm_types = set(a["alarm_type"] for a in alarms)
        evidence_types = set(
            (e.props or {}).get("alarm_type", "")
            for e in evidence_nodes
        )

        for at in alarm_types:
            if at not in evidence_types:
                checks.append(ModalityCheck(
                    source_type="alarm", target_type="evidence",
                    edge_type="requires_check",
                    confidence=0.70,
                    finding=f"告警类型'{at}'缺少对应证据节点",
                    explanation="该告警尚未被任何证据节点引用，存在信息缺口。",
                    recommendation=f"为告警类型'{at}'创建对应的证据检查。",
                    severity="warning",
                ))

        # Check if alarm severity matches evidence severity
        high_alarms = [a for a in alarms if a["severity"] in ("high", "critical")]
        high_evidence = [e for e in evidence_nodes if (e.confidence or 0) > 0.8]
        if high_alarms and not high_evidence:
            checks.append(ModalityCheck(
                source_type="alarm", target_type="evidence",
                edge_type="requires_check",
                confidence=0.65,
                finding=f"{len(high_alarms)}个高严重性告警但无高置信度证据",
                explanation="高级别告警需要更充分的证据支撑当前诊断。",
                recommendation="增加对高优先级告警类型的专项检查。",
                severity="warning",
            ))

        return checks

    def _check_knowledge_vs_observations(
        self, knowledge: list[dict], evidence_nodes: list[EvidenceNode]
    ) -> list[ModalityCheck]:
        checks: list[ModalityCheck] = []
        if not knowledge:
            return checks

        for kn in knowledge:
            symptoms = kn.get("symptoms") or []
            observed_text = " ".join(
                (e.label or "") + " " + (e.description or "")
                for e in evidence_nodes
            ).lower()

            matched = []
            unmatched = []
            for sym in symptoms:
                sym_str = str(sym).lower()
                if isinstance(sym, dict):
                    sym_str = str(sym.get("name", sym.get("description", str(sym)))).lower()
                if sym_str in observed_text or any(
                    sym_str[:4] in (e.label or "").lower()
                    for e in evidence_nodes
                ):
                    matched.append(sym_str)
                else:
                    unmatched.append(sym_str)

            if matched:
                checks.append(ModalityCheck(
                    source_type="knowledge", target_type="observation",
                    edge_type="supports",
                    confidence=0.75,
                    finding=f"已观察到知识库记录的症状: {', '.join(matched[:3])}",
                    explanation=f"故障模式'{kn['fault_type']}'的已知症状与当前观察一致。",
                    recommendation="按知识库推荐方案优先排查。",
                ))
            if unmatched:
                checks.append(ModalityCheck(
                    source_type="knowledge", target_type="observation",
                    edge_type="requires_check",
                    confidence=0.55,
                    finding=f"知识库症状未完全匹配: 缺失{', '.join(unmatched[:3])}",
                    explanation=(
                        f"故障模式'{kn['fault_type']}'的典型症状中，"
                        f"{len(unmatched)}项在当前证据中未体现。"
                    ),
                    recommendation=f"请检查是否遗漏了对{', '.join(unmatched[:2])}的观察。",
                    severity="warning" if len(unmatched) > len(matched) else "info",
                ))

        return checks
