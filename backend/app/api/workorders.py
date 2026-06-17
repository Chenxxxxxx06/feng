import asyncio
import logging
from datetime import datetime, timedelta, timezone
from smtplib import SMTPRecipientsRefused

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.ai import _detect_anomalies, _generate_local_diagnosis
from app.api.auth import get_current_user
from app.config import get_settings
from app.database import get_db
from app.models import (
    Fault,
    FaultKnowledgeNode,
    MaintenanceRecord,
    NotificationConfig,
    NotificationLog,
    SCADARecord,
    Turbine,
    User,
    WorkOrder,
)
from app.schemas import (
    MaintenanceRecordCreate,
    MaintenanceRecordResponse,
    NotificationLogResponse,
    WorkOrderCreate,
    WorkOrderDetailResponse,
    WorkOrderEmailRequest,
    WorkOrderResponse,
    WorkOrderUpdate,
)
from app.services.email_service import EmailConfigError, send_email
from app.services.qwen_client import diagnose_fault

router = APIRouter(dependencies=[Depends(get_current_user)])
logger = logging.getLogger(__name__)

VALID_STATUS = {"pending", "assigned", "in_progress", "review", "completed", "closed", "cancelled"}
STATUS_ACTION = {
    "pending": "created",
    "assigned": "assigned",
    "in_progress": "started",
    "review": "reviewed",
    "completed": "repaired",
    "closed": "closed",
    "cancelled": "cancelled",
}


def _model_fields() -> set[str]:
    return {col.name for col in WorkOrder.__table__.columns}


def _filter_model_data(data: dict) -> dict:
    fields = _model_fields()
    return {key: val for key, val in data.items() if key in fields}


def _fmt_item(item) -> str:
    """Format a knowledge item that may be a str or dict."""
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return item.get("action") or item.get("name") or item.get("title") or str(item)
    return str(item)


def _fmt_items(items: list) -> list[str]:
    return [_fmt_item(item) for item in items]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _workorder_plain_body(
    wo: WorkOrder,
    turbine: Turbine | None,
    ai_section: dict | None,
    knowledge: dict | None,
) -> str:
    """Build structured plain-text work order email."""
    priority_label = {"low": "低", "medium": "中", "high": "高", "urgent": "紧急"}.get(wo.priority or "medium", wo.priority or "中")
    status_label = {
        "pending": "待处理", "assigned": "已分配", "in_progress": "进行中",
        "review": "审核中", "completed": "已完成", "closed": "已关闭", "cancelled": "已取消",
    }.get(wo.status, wo.status)

    lines = [
        "╔══════════════════════════════════════════╗",
        "║  风调预顺 PHM — 维修工单通知              ║",
        f"║  WO-{wo.id:04d} | {priority_label}优先级 | {status_label}",
        "╚══════════════════════════════════════════╝",
        "",
        "【工单概要】",
        f"  编号:       WO-{wo.id:04d}",
        f"  标题:       {wo.title}",
        f"  描述:       {wo.description or '（无）'}",
    ]
    if turbine:
        hi_str = f"{turbine.hi_value:.1f}" if turbine.hi_value is not None else "--"
        lines += [
            f"  风机:       {turbine.name} | 型号: {turbine.model or '--'} | 区域: {turbine.region or '--'}",
            f"  健康指数:   {hi_str} | 状态: {turbine.status or '--'}",
        ]
    else:
        lines.append(f"  风机ID:     {wo.turbine_id}")

    lines += [
        f"  故障类型:   {wo.fault_type or '未设置'}",
        f"  优先级:     {priority_label}",
        f"  状态:       {status_label}",
        f"  责任人:     {wo.assignee or '待分配'}",
        f"  截止日期:   {wo.due_date.strftime('%Y-%m-%d') if wo.due_date else '未设置'}",
        f"  预估成本:   ¥{wo.cost_estimate:,.0f}" if wo.cost_estimate else "  预估成本:   未设置",
        "",
    ]

    # AI / diagnosis section
    if ai_section:
        source_tag = "🤖 AI诊断报告" if ai_section.get("source") == "ai" else "📋 本地规则诊断"
        lines.append(f"【{source_tag}】")
        lines.append(f"  {ai_section.get('diagnosis', '')}")
        anomalies = ai_section.get("anomalies") or []
        if anomalies:
            lines.append("")
            lines.append("  异常指标:")
            for a in anomalies:
                level_icon = "🔴" if a.get("level") == "high" else "🟡"
                lines.append(
                    f"  {level_icon} {a['indicator']}: 当前 {a['value']} "
                    f"（正常: {a['normal']}）偏差: {a['deviation']}"
                )
        lines.append("")

    # fault knowledge / encyclopedia section
    if knowledge:
        sev_label = {"low": "低", "medium": "中", "high": "高", "critical": "紧急"}.get(
            knowledge.get("severity", ""), knowledge.get("severity", "")
        )
        lines.append("【📚 故障百科 · 知识库参考】")
        lines.append(f"  故障类型: {knowledge.get('fault_type', '')}  |  分类: {knowledge.get('category', '')}  |  严重度: {sev_label}")
        lines.append("")
        # Symptoms
        symptoms = knowledge.get("symptoms") or []
        if symptoms:
            lines.append("  ▸ 故障症状/指标:")
            for s in symptoms[:5]:
                if isinstance(s, dict):
                    lines.append(f"    · {s.get('indicator', '')} 阈值: {s.get('threshold', '')} {s.get('unit', '')}")
                else:
                    lines.append(f"    · {_fmt_item(s)}")
            lines.append("")
        # Root causes
        if knowledge.get("root_causes"):
            lines.append(f"  ▸ 可能根因: {'; '.join(_fmt_items(knowledge['root_causes'][:5]))}")
            lines.append("")
        # Solutions
        if knowledge.get("solutions"):
            lines.append("  ▸ 建议方案:")
            for sol in knowledge["solutions"][:4]:
                if isinstance(sol, dict):
                    diff = sol.get("difficulty", "")
                    diff_label = {"easy": "简单", "medium": "中等", "hard": "困难"}.get(diff, diff)
                    lines.append(f"    · {sol.get('action', '')} (难度: {diff_label}, 停机: {sol.get('downtime_hours', '?')}h)")
                else:
                    lines.append(f"    · {_fmt_item(sol)}")
            lines.append("")
        # Spare parts
        if knowledge.get("spare_parts"):
            lines.append("  ▸ 相关备件:")
            for sp in knowledge["spare_parts"][:5]:
                if isinstance(sp, dict):
                    cost = f"约¥{sp.get('est_cost', 0):,.0f}" if sp.get('est_cost') else ""
                    lines.append(f"    · {sp.get('name', '')} x{sp.get('quantity', 1)} {cost}")
                else:
                    lines.append(f"    · {_fmt_item(sp)}")
            lines.append("")
        # Related faults
        related = knowledge.get("related_faults") or []
        if related:
            lines.append("  ▸ 关联故障:")
            for rf in related[:3]:
                if isinstance(rf, dict):
                    prob = rf.get("probability", 0)
                    lines.append(f"    · {rf.get('name', '')} (伴生概率: {int(prob * 100)}%)")
                else:
                    lines.append(f"    · {_fmt_item(rf)}")
            lines.append("")
        # Historical cases
        cases = knowledge.get("cases") or []
        if cases:
            lines.append("  ▸ 历史案例:")
            for c in cases[:2]:
                if isinstance(c, dict):
                    lines.append(f"    · {c.get('turbine', '')} ({c.get('date', '')})")
                    lines.append(f"      处置: {c.get('resolution', '')}  |  费用: ¥{c.get('total_cost', 0):,}  |  停机: {c.get('downtime_days', 0)}天")
                else:
                    lines.append(f"    · {_fmt_item(c)}")
            lines.append("")

    lines += [
        "【操作指引】",
        "  请登录风调预顺PHM系统查看并处理此工单。",
        "",
        "────────────────────────────────────────",
        "风调预顺 PHM 系统 | 预测性运维平台",
        "此邮件由系统自动生成，请勿直接回复",
    ]
    return "\n".join(lines)


def _workorder_html_body(
    wo: WorkOrder,
    turbine: Turbine | None,
    ai_section: dict | None,
    knowledge: dict | None,
) -> str:
    """Build HTML work order email with inline CSS."""
    _PRIORITY = {"low": "低", "medium": "中", "high": "高", "urgent": "紧急"}
    _PRIORITY_COLOR = {"low": "#2da44e", "medium": "#d29922", "high": "#cf222e", "urgent": "#cf222e"}
    _STATUS = {
        "pending": "待处理", "assigned": "已分配", "in_progress": "进行中",
        "review": "审核中", "completed": "已完成", "closed": "已关闭", "cancelled": "已取消",
    }
    _STATUS_COLOR = {
        "pending": "#6e7681", "assigned": "#58a6ff", "in_progress": "#d29922",
        "review": "#a371f7", "completed": "#2da44e", "closed": "#6e7681", "cancelled": "#cf222e",
    }

    priority_key = wo.priority or "medium"
    priority_label = _PRIORITY.get(priority_key, "中")
    priority_color = _PRIORITY_COLOR.get(priority_key, "#d29922")
    status_label = _STATUS.get(wo.status, wo.status)
    status_color = _STATUS_COLOR.get(wo.status, "#6e7681")
    # priority up-arrow indicator
    arrow_bits = ""
    if wo.priority:
        try:
            arrow_bits = "⬆" * ["low", "medium", "high", "urgent"].index(wo.priority)
        except ValueError:
            arrow_bits = ""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f6f8fa;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f6f8fa;padding:20px 0;">
<tr><td align="center">
<table width="620" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.12);">

  <!-- Header -->
  <tr><td style="background:#1a1a2e;padding:20px 24px;color:#fff;">
    <h2 style="margin:0 0 6px;font-size:18px;">🔧 风调预顺 PHM — 维修工单通知</h2>
    <span style="background:{priority_color};color:#fff;padding:2px 8px;border-radius:4px;font-size:12px;margin-right:8px;">
      {arrow_bits}{priority_label}优先级
    </span>
    <span style="background:{status_color};color:#fff;padding:2px 8px;border-radius:4px;font-size:12px;">{status_label}</span>
    <span style="float:right;font-size:13px;opacity:.7;">WO-{wo.id:04d}</span>
  </td></tr>

  <!-- Order Summary -->
  <tr><td style="padding:20px 24px;border-bottom:1px solid #e1e4e8;">
    <h3 style="margin:0 0 12px;font-size:15px;color:#24292f;">📋 工单概要</h3>
    <table width="100%" cellpadding="4" cellspacing="0" style="font-size:13px;color:#57606a;">
      <tr><td width="80" style="color:#24292f;font-weight:600;">编号</td><td>WO-{wo.id:04d}</td></tr>
      <tr><td style="color:#24292f;font-weight:600;">标题</td><td style="color:#24292f;font-weight:500;">{wo.title}</td></tr>
      <tr><td style="color:#24292f;font-weight:600;vertical-align:top;">描述</td><td>{wo.description or '（无）'}</td></tr>"""

    if turbine:
        hi_str = f"{turbine.hi_value:.1f}" if turbine.hi_value is not None else "--"
        html += f"""<tr><td style="color:#24292f;font-weight:600;">风机</td><td>{turbine.name} | 型号: {turbine.model or '--'} | 区域: {turbine.region or '--'}</td></tr>
      <tr><td style="color:#24292f;font-weight:600;">健康指数</td><td>{hi_str} | 状态: {turbine.status or '--'}</td></tr>"""
    else:
        html += f"""<tr><td style="color:#24292f;font-weight:600;">风机ID</td><td>{wo.turbine_id}</td></tr>"""

    cost_str = f"¥{wo.cost_estimate:,.0f}" if wo.cost_estimate else "未设置"
    html += f"""<tr><td style="color:#24292f;font-weight:600;">故障类型</td><td>{wo.fault_type or '未设置'}</td></tr>
      <tr><td style="color:#24292f;font-weight:600;">责任人</td><td>{wo.assignee or '待分配'}</td></tr>
      <tr><td style="color:#24292f;font-weight:600;">截止日期</td><td>{wo.due_date.strftime('%Y-%m-%d') if wo.due_date else '未设置'}</td></tr>
      <tr><td style="color:#24292f;font-weight:600;">预估成本</td><td style="color:#cf222e;font-weight:600;">{cost_str}</td></tr>
    </table>
  </td></tr>"""

    # AI / diagnosis section
    if ai_section:
        source_tag = "🤖 AI 诊断报告" if ai_section.get("source") == "ai" else "📋 本地规则诊断"
        html += f"""
  <tr><td style="padding:20px 24px;border-bottom:1px solid #e1e4e8;">
    <h3 style="margin:0 0 12px;font-size:15px;color:#24292f;">{source_tag}</h3>
    <p style="margin:0 0 12px;font-size:13px;color:#57606a;line-height:1.6;">{ai_section.get('diagnosis', '')}</p>"""
        anomalies = ai_section.get("anomalies") or []
        if anomalies:
            html += """<table width="100%" cellpadding="6" cellspacing="0" style="font-size:12px;border-collapse:collapse;">
      <tr style="background:#f6f8fa;color:#24292f;font-weight:600;">
        <td style="border:1px solid #e1e4e8;">指标</td><td style="border:1px solid #e1e4e8;">当前值</td>
        <td style="border:1px solid #e1e4e8;">正常范围</td><td style="border:1px solid #e1e4e8;">偏差</td></tr>"""
            for a in anomalies:
                level_bg = "#fff1f0" if a.get("level") == "high" else "#fff8c5"
                html += f"""<tr style="background:{level_bg};">
        <td style="border:1px solid #e1e4e8;">{a['indicator']}</td>
        <td style="border:1px solid #e1e4e8;font-weight:600;">{a['value']}</td>
        <td style="border:1px solid #e1e4e8;">{a['normal']}</td>
        <td style="border:1px solid #e1e4e8;color:{'#cf222e' if a.get('level') == 'high' else '#9a6700'};">{a['deviation']}</td></tr>"""
            html += "</table>"
        html += "\n  </td></tr>"

    # fault knowledge / encyclopedia section
    if knowledge:
        sev_label = {"low": "低", "medium": "中", "high": "高", "critical": "紧急"}.get(
            knowledge.get("severity", ""), knowledge.get("severity", "")
        )
        _SEV_COLOR = {"low": "#2da44e", "medium": "#d29922", "high": "#cf222e", "critical": "#cf222e"}
        sev_color = _SEV_COLOR.get(knowledge.get("severity", ""), "#6e7681")
        html += f"""
  <tr><td style="padding:20px 24px;border-bottom:1px solid #e1e4e8;">
    <h3 style="margin:0 0 12px;font-size:15px;color:#24292f;">📚 故障百科 · 知识库参考</h3>
    <p style="margin:0 0 12px;font-size:13px;color:#57606a;">
      {knowledge.get('icon', '')} <b>{knowledge.get('fault_type', '')}</b>
      &nbsp;|&nbsp; 分类: {knowledge.get('category', '')}
      &nbsp;|&nbsp; 严重度: <span style="color:{sev_color};font-weight:600;">{sev_label}</span>
    </p>
    <table width="100%" cellpadding="4" cellspacing="0" style="font-size:13px;color:#57606a;">"""
        # Symptoms
        symptoms = knowledge.get("symptoms") or []
        if symptoms:
            sym_text = "<br>".join(
                f"· {s.get('indicator','')} 阈值: {s.get('threshold','')} {s.get('unit','')}"
                if isinstance(s, dict) else f"· {_fmt_item(s)}"
                for s in symptoms[:5]
            )
            html += f"""<tr><td width="80" style="color:#24292f;font-weight:600;vertical-align:top;">故障症状</td><td>{sym_text}</td></tr>"""
        if knowledge.get("root_causes"):
            html += f"""<tr><td style="color:#24292f;font-weight:600;">可能根因</td><td>{'; '.join(_fmt_items(knowledge['root_causes'][:5]))}</td></tr>"""
        if knowledge.get("solutions"):
            sol_lines = []
            for sol in knowledge["solutions"][:4]:
                if isinstance(sol, dict):
                    diff = sol.get("difficulty", "")
                    diff_label = {"easy": "简单", "medium": "中等", "hard": "困难"}.get(diff, diff)
                    sol_lines.append(f"· {sol.get('action','')} (难度:{diff_label}, 停机:{sol.get('downtime_hours','?')}h)")
                else:
                    sol_lines.append(f"· {_fmt_item(sol)}")
            html += f"""<tr><td style="color:#24292f;font-weight:600;vertical-align:top;">建议方案</td><td>{"<br>".join(sol_lines)}</td></tr>"""
        if knowledge.get("spare_parts"):
            sp_lines = []
            for sp in knowledge["spare_parts"][:5]:
                if isinstance(sp, dict):
                    cost = f"约¥{sp.get('est_cost', 0):,.0f}" if sp.get('est_cost') else ""
                    sp_lines.append(f"· {sp.get('name','')} x{sp.get('quantity',1)} {cost}")
                else:
                    sp_lines.append(f"· {_fmt_item(sp)}")
            html += f"""<tr><td style="color:#24292f;font-weight:600;vertical-align:top;">相关备件</td><td>{"<br>".join(sp_lines)}</td></tr>"""
        # Related faults
        related = knowledge.get("related_faults") or []
        if related:
            rel_lines = []
            for rf in related[:3]:
                if isinstance(rf, dict):
                    prob = rf.get("probability", 0)
                    rel_lines.append(f"· {rf.get('name','')} (伴生概率: {int(prob*100)}%)")
                else:
                    rel_lines.append(f"· {_fmt_item(rf)}")
            html += f"""<tr><td style="color:#24292f;font-weight:600;vertical-align:top;">关联故障</td><td>{"<br>".join(rel_lines)}</td></tr>"""
        # Historical cases
        cases = knowledge.get("cases") or []
        if cases:
            case_lines = []
            for c in cases[:2]:
                if isinstance(c, dict):
                    case_lines.append(
                        f"· {c.get('turbine','')} ({c.get('date','')}) — "
                        f"处置: {c.get('resolution','')} | "
                        f"费用: ¥{c.get('total_cost',0):,} | 停机: {c.get('downtime_days',0)}天"
                    )
                else:
                    case_lines.append(f"· {_fmt_item(c)}")
            html += f"""<tr><td style="color:#24292f;font-weight:600;vertical-align:top;">历史案例</td><td>{"<br>".join(case_lines)}</td></tr>"""
        html += """
    </table>
  </td></tr>"""

    html += """
  <!-- Footer -->
  <tr><td style="background:#f6f8fa;padding:16px 24px;text-align:center;font-size:11px;color:#8b949e;">
    <p style="margin:0 0 4px;">请登录 <b>风调预顺 PHM 系统</b> 查看并处理此工单</p>
    <p style="margin:0;">此邮件由系统自动生成，请勿直接回复</p>
  </td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""
    return html


async def _fetch_turbine_info(wo: WorkOrder, db: AsyncSession) -> Turbine | None:
    """Fetch turbine record for a work order."""
    return await db.get(Turbine, wo.turbine_id)


# ── Fault-type → Knowledge-node fuzzy matching helpers ──────

# English internal fault_type codes → Chinese labels.
# Work orders store English codes (e.g. "generator_overheat") but the
# knowledge base uses Chinese names (e.g. "发电机过热").  This mapping
# bridges the two so _fetch_fault_knowledge can match correctly.
_EN_TO_CN_FAULT: dict[str, str] = {
    "bearing_inner_race_wear": "轴承内圈磨损",
    "bearing_outer_race": "轴承外圈故障",
    "bearing_ball": "轴承滚动体故障",
    "bearing_wear": "轴承磨损",
    "bearing_fault": "轴承磨损",
    "bearing_cage_failure": "轴承保持架故障",
    "gearbox_tooth_pitting": "齿轮箱点蚀",
    "gearbox_tooth_wear": "齿轮箱齿面磨损",
    "gearbox_fault": "齿轮箱点蚀",
    "generator_overheat": "发电机过热",
    "generator_fault": "发电机过热",
    "blade_leading_edge_erosion": "叶片前缘侵蚀",
    "blade_damage": "叶片裂纹",
    "blade_crack": "叶片裂纹",
    "blade_ice": "叶片结冰",
    "pitch_system_fault": "变桨系统故障",
    "main_shaft_misalignment": "轴对中不良",
    "shaft_misalignment": "轴对中不良",
    "cooling_system_fault": "冷却系统故障",
    "electrical_connection": "电气连接异常",
    "electrical_fault": "变频器故障",
    "unbalance": "转子不平衡",
    "misalignment": "轴对中不良",
    "looseness": "轴承磨损",
    "resonance": "齿轮箱点蚀",
    "yaw_failure": "偏航系统故障",
    "yaw_sensor_fault": "风向传感器故障",
    "coupling_wear": "联轴器磨损",
    "converter_fault": "变频器故障",
    "transformer_overheat": "变压器过热",
    "tower_weld_crack": "塔筒焊缝裂纹",
    "tower_foundation": "基础沉降",
    "no_fault_detected": "未识别到明确故障",
}

# Keywords extracted from fault_type / work order title used as
# search anchors when an exact fault_type match is not found.
_KNOWLEDGE_KEYWORD_MAP: dict[str, list[str]] = {
    "齿轮": ["齿轮箱点蚀", "齿轮断齿", "齿轮箱漏油"],
    "齿轮箱": ["齿轮箱点蚀", "齿轮断齿", "齿轮箱漏油"],
    "轴承": ["轴承磨损", "轴承保持架故障", "轴承电蚀"],
    "叶片": ["叶片前缘侵蚀", "叶片裂纹", "叶片结冰"],
    "发电机": ["发电机过热", "发电机绝缘老化"],
    "偏航": ["偏航系统故障", "风向传感器故障"],
    "传动": ["轴对中不良", "联轴器磨损"],
    "主轴": ["轴对中不良", "联轴器磨损"],
    "电气": ["变频器故障", "变压器过热"],
    "塔筒": ["塔筒焊缝裂纹", "基础沉降"],
    "变桨": ["变桨系统故障"],
    "冷却": ["发电机过热"],
    "振动": ["轴承磨损", "齿轮箱点蚀", "转子不平衡"],
    "温度": ["发电机过热", "变压器过热"],
    "漏油": ["齿轮箱漏油"],
    "断齿": ["齿轮断齿"],
    "点蚀": ["齿轮箱点蚀"],
    "裂纹": ["叶片裂纹", "塔筒焊缝裂纹"],
    "不平衡": ["转子不平衡"],
    "对中": ["轴对中不良"],
    "不对中": ["轴对中不良"],
    "过热": ["发电机过热", "变压器过热"],
    "电蚀": ["轴承电蚀"],
    "绝缘": ["发电机绝缘老化"],
    "变频": ["变频器故障"],
    "变压器": ["变压器过热"],
}


def _extract_keywords(text: str) -> list[str]:
    """Extract Chinese technical keywords from fault_type / title text."""
    found: list[str] = []
    for keyword in _KNOWLEDGE_KEYWORD_MAP:
        if keyword in text:
            found.append(keyword)
    return found


async def _fetch_fault_knowledge(wo: WorkOrder, db: AsyncSession) -> dict | None:
    """Match fault_type against FaultKnowledgeNode with fuzzy fallback.

    Strategy (best-effort, ordered):
      0. Translate English fault_type code → Chinese label
      1. Exact match on wo.fault_type
      2. Keyword match via _KNOWLEDGE_KEYWORD_MAP → exact match on
         candidate fault_type names
      3. ILIKE fuzzy match on fault_knowledge.fault_type
      4. Category ILIKE match on fault_knowledge.category
    """
    search_text = (wo.fault_type or "").strip()
    if not search_text:
        return None

    # ── 0. Translate English code → Chinese label ──
    # Work orders store internal English codes (e.g. "generator_overheat")
    # but knowledge base uses Chinese names (e.g. "发电机过热").
    cn_label = _EN_TO_CN_FAULT.get(search_text, "")
    search_texts: list[str] = [search_text]
    if cn_label and cn_label != search_text:
        search_texts.append(cn_label)

    # ── 1. Exact match (try both EN code and CN label) ──
    for text in search_texts:
        result = await db.execute(
            select(FaultKnowledgeNode).where(FaultKnowledgeNode.fault_type == text)
        )
        node = result.scalar_one_or_none()
        if node:
            return _knowledge_node_to_dict(node)

    # ── 2. Keyword → candidate fault_type names ──
    # Extract keywords from BOTH the original text and the CN translation
    keywords: list[str] = []
    seen_kw: set[str] = set()
    for text in search_texts:
        for kw in _extract_keywords(text):
            if kw not in seen_kw:
                seen_kw.add(kw)
                keywords.append(kw)

    if keywords:
        # Collect unique candidate names
        candidates: list[str] = []
        seen: set[str] = set()
        for kw in keywords:
            for name in _KNOWLEDGE_KEYWORD_MAP.get(kw, []):
                if name not in seen:
                    seen.add(name)
                    candidates.append(name)

        if candidates:
            result = await db.execute(
                select(FaultKnowledgeNode).where(
                    FaultKnowledgeNode.fault_type.in_(candidates)
                ).limit(1)
            )
            node = result.scalar_one_or_none()
            if node:
                return _knowledge_node_to_dict(node)

    # ── 3. ILIKE fuzzy match on fault_type (try all search texts) ──
    for text in search_texts:
        result = await db.execute(
            select(FaultKnowledgeNode)
            .where(FaultKnowledgeNode.fault_type.ilike(f"%{text}%"))
            .limit(1)
        )
        node = result.scalar_one_or_none()
        if node:
            return _knowledge_node_to_dict(node)

    # ── 4. ILIKE fuzzy match with each keyword ──
    for kw in keywords[:3]:
        result = await db.execute(
            select(FaultKnowledgeNode)
            .where(FaultKnowledgeNode.fault_type.ilike(f"%{kw}%"))
            .limit(1)
        )
        node = result.scalar_one_or_none()
        if node:
            return _knowledge_node_to_dict(node)

    # ── 5. Category ILIKE match ──
    for kw in keywords[:3]:
        result = await db.execute(
            select(FaultKnowledgeNode)
            .where(FaultKnowledgeNode.category.ilike(f"%{kw}%"))
            .limit(1)
        )
        node = result.scalar_one_or_none()
        if node:
            return _knowledge_node_to_dict(node)

    return None


def _knowledge_node_to_dict(node: FaultKnowledgeNode) -> dict:
    return {
        "fault_type": node.fault_type,
        "category": node.category,
        "severity": node.severity,
        "icon": node.icon or "",
        "symptoms": node.symptoms or [],
        "root_causes": node.root_causes or [],
        "solutions": node.solutions or [],
        "spare_parts": node.spare_parts or [],
        "related_faults": node.related_faults or [],
        "cases": node.cases or [],
    }


async def _try_ai_analysis(
    wo: WorkOrder, db: AsyncSession, user: User
) -> dict | None:
    """Try AI-powered fault diagnosis for the work order.

    Returns dict with diagnosis / anomalies / source on success,
    or a local-fallback dict if the AI call fails,
    or None when the user has no API key configured at all.
    """
    effective_key = user.api_key or get_settings().DASHSCOPE_API_KEY or None
    if not effective_key:
        return None

    turbine = await _fetch_turbine_info(wo, db)
    if not turbine:
        return None

    # recent SCADA data
    since = _utc_now() - timedelta(hours=24)
    scada_result = await db.execute(
        select(SCADARecord)
        .where(SCADARecord.turbine_id == wo.turbine_id, SCADARecord.timestamp >= since)
        .order_by(SCADARecord.timestamp.desc())
        .limit(100)
    )
    scada_records = scada_result.scalars().all()

    # fault history
    fault_result = await db.execute(
        select(Fault)
        .where(Fault.turbine_id == wo.turbine_id)
        .order_by(Fault.detected_at.desc())
        .limit(10)
    )
    faults = fault_result.scalars().all()

    turbine_data = {
        "name": turbine.name,
        "model": turbine.model,
        "power_mw": turbine.power_mw,
        "region": turbine.region,
        "hi_value": turbine.hi_value,
        "status": turbine.status,
    }
    fault_data = [
        {
            "type": f.fault_type,
            "confidence": f.confidence,
            "detected_at": f.detected_at.isoformat() if f.detected_at else None,
        }
        for f in faults
    ]

    try:
        anomalies = _detect_anomalies(scada_records, turbine.power_mw or 2.0)
        diagnosis = await asyncio.wait_for(
            asyncio.to_thread(
                diagnose_fault,
                turbine_data,
                fault_data,
                model=user.model_preference,
                api_key=effective_key,
                api_provider=user.api_provider or get_settings().DASHSCOPE_API_KEY,
                base_url=user.api_base_url,
            ),
            timeout=20.0,
        )
        return {"diagnosis": diagnosis, "anomalies": anomalies, "source": "ai"}
    except (Exception, asyncio.TimeoutError):
        logger.warning("AI diagnosis failed for WO-%04d, falling back to local", wo.id)
        # Re-compute anomalies inside the handler in case _detect_anomalies was the failure point
        try:
            anomalies = _detect_anomalies(scada_records, turbine.power_mw or 2.0)
        except Exception:
            anomalies = []
        local_diag = _generate_local_diagnosis(turbine_data, anomalies)
        return {"diagnosis": local_diag, "anomalies": anomalies, "source": "local"}


async def _add_record(
    db: AsyncSession,
    wo: WorkOrder,
    user: User | None,
    action_type: str,
    content: str | None = None,
    before_status: str | None = None,
    after_status: str | None = None,
    extra: dict | None = None,
) -> MaintenanceRecord:
    record = MaintenanceRecord(
        work_order_id=wo.id,
        operator_id=user.id if user else None,
        action_type=action_type,
        content=content,
        before_status=before_status,
        after_status=after_status,
        extra=extra,
    )
    db.add(record)
    return record


async def _resolve_assignee_email(wo: WorkOrder, db: AsyncSession) -> str | None:
    if wo.assignee_email:
        return wo.assignee_email
    if wo.assignee_id:
        result = await db.execute(select(User).where(User.id == wo.assignee_id, User.is_active == True))
        user = result.scalar_one_or_none()
        if user:
            return user.email
    if not wo.assignee:
        return None

    result = await db.execute(select(User).where(User.username == wo.assignee, User.is_active == True))
    user = result.scalar_one_or_none()
    return user.email if user else None


async def _recipient_emails(data: WorkOrderEmailRequest, wo: WorkOrder, db: AsyncSession) -> list[str]:
    recipients = list(data.recipient_emails)
    assignee_email = await _resolve_assignee_email(wo, db)
    if assignee_email:
        recipients.append(assignee_email)

    if data.recipient_user_ids:
        result = await db.execute(select(User).where(User.id.in_(data.recipient_user_ids), User.is_active == True))
        recipients.extend(user.email for user in result.scalars().all())

    return list(dict.fromkeys(email for email in recipients if email))


@router.get("/", response_model=list[WorkOrderResponse])
async def list_workorders(
    status: str | None = Query(None),
    assignee: str | None = Query(None),
    priority: str | None = Query(None),
    turbine_id: int | None = Query(None),
    fault_id: int | None = Query(None),
    include_deleted: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    q = select(WorkOrder).order_by(WorkOrder.created_at.desc())
    if not include_deleted:
        q = q.where(WorkOrder.deleted_at.is_(None))
    if status:
        q = q.where(WorkOrder.status == status)
    if assignee:
        q = q.where(WorkOrder.assignee == assignee)
    if priority:
        q = q.where(WorkOrder.priority == priority)
    if turbine_id:
        q = q.where(WorkOrder.turbine_id == turbine_id)
    if fault_id:
        q = q.where(WorkOrder.fault_id == fault_id)
    result = await db.execute(q)
    return [WorkOrderResponse.model_validate(wo) for wo in result.scalars().all()]


@router.get("/{workorder_id}", response_model=WorkOrderDetailResponse)
async def get_workorder(workorder_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(WorkOrder).where(WorkOrder.id == workorder_id, WorkOrder.deleted_at.is_(None))
    )
    wo = result.scalar_one_or_none()
    if not wo:
        raise HTTPException(status_code=404, detail="WorkOrder not found")

    records_result = await db.execute(
        select(MaintenanceRecord)
        .where(MaintenanceRecord.work_order_id == workorder_id)
        .order_by(MaintenanceRecord.created_at.asc())
    )
    logs_result = await db.execute(
        select(NotificationLog)
        .where(NotificationLog.work_order_id == workorder_id)
        .order_by(NotificationLog.created_at.asc())
    )
    detail = WorkOrderDetailResponse.model_validate(wo)
    detail.records = [MaintenanceRecordResponse.model_validate(record) for record in records_result.scalars().all()]
    detail.notification_logs = [NotificationLogResponse.model_validate(log) for log in logs_result.scalars().all()]
    return detail


@router.post("/", response_model=WorkOrderResponse, status_code=201)
async def create_workorder(
    data: WorkOrderCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    payload = data.model_dump(exclude_none=True)
    turbine = await db.get(Turbine, data.turbine_id)
    if not turbine:
        raise HTTPException(status_code=404, detail="Turbine not found")

    if data.fault_id is not None:
        fault = await db.get(Fault, data.fault_id)
        if not fault:
            raise HTTPException(status_code=404, detail="Fault not found")
        if fault.turbine_id != data.turbine_id:
            raise HTTPException(status_code=400, detail="Work order turbine_id must match fault turbine_id")

    if payload.get("assignee") or payload.get("assignee_id"):
        payload.setdefault("status", "assigned")

    now = _utc_now()
    payload.setdefault("priority", "medium")
    payload.setdefault("created_at", now)
    payload.setdefault("updated_at", now)

    wo = WorkOrder(**_filter_model_data(payload))
    db.add(wo)
    await db.flush()
    await _add_record(db, wo, user, "created", "Work order created", after_status=wo.status)

    await db.commit()
    await db.refresh(wo)
    return WorkOrderResponse.model_validate(wo)


@router.put("/{workorder_id}", response_model=WorkOrderResponse)
async def update_workorder(
    workorder_id: int,
    data: WorkOrderUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(WorkOrder).where(WorkOrder.id == workorder_id, WorkOrder.deleted_at.is_(None))
    )
    wo = result.scalar_one_or_none()
    if not wo:
        raise HTTPException(status_code=404, detail="WorkOrder not found")

    before_status = wo.status
    update_data = data.model_dump(exclude_none=True)
    if data.status and data.status not in VALID_STATUS:
        raise HTTPException(status_code=400, detail="Invalid work order status")

    now = _utc_now()
    if data.status == "completed" and wo.status != "completed":
        update_data["completed_at"] = now
    if data.status == "cancelled":
        update_data["cancelled_at"] = now
    update_data["updated_at"] = now

    for key, val in _filter_model_data(update_data).items():
        setattr(wo, key, val)

    await _add_record(
        db,
        wo,
        user,
        STATUS_ACTION.get(data.status, "updated") if data.status and data.status != before_status else "updated",
        content="Work order updated",
        before_status=before_status,
        after_status=wo.status,
        extra={"updated_fields": sorted(update_data.keys())},
    )

    # ── Update turbine last_maintenance on completion ──
    if data.status in ("completed", "closed") and before_status not in ("completed", "closed"):
        turbine_result = await db.execute(select(Turbine).where(Turbine.id == wo.turbine_id))
        turbine = turbine_result.scalar_one_or_none()
        if turbine:
            turbine.last_maintenance = now
            # Also set downtime_hours on work order if not already set
            if wo.downtime_hours is None and wo.created_at:
                wo.downtime_hours = max(0.5, (now - wo.created_at).total_seconds() / 3600)

    await db.commit()
    await db.refresh(wo)
    return WorkOrderResponse.model_validate(wo)


@router.delete("/{workorder_id}", response_model=WorkOrderResponse)
async def delete_workorder(
    workorder_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(WorkOrder).where(WorkOrder.id == workorder_id, WorkOrder.deleted_at.is_(None))
    )
    wo = result.scalar_one_or_none()
    if not wo:
        raise HTTPException(status_code=404, detail="WorkOrder not found")

    now = _utc_now()
    wo.deleted_at = now
    wo.updated_at = now
    await _add_record(
        db,
        wo,
        user,
        "deleted",
        content="Work order deleted",
        before_status=wo.status,
        after_status=wo.status,
    )

    await db.commit()
    await db.refresh(wo)
    return WorkOrderResponse.model_validate(wo)


@router.post("/{workorder_id}/records", response_model=MaintenanceRecordResponse, status_code=201)
async def add_workorder_record(
    workorder_id: int,
    data: MaintenanceRecordCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(WorkOrder).where(WorkOrder.id == workorder_id, WorkOrder.deleted_at.is_(None))
    )
    wo = result.scalar_one_or_none()
    if not wo:
        raise HTTPException(status_code=404, detail="WorkOrder not found")

    before_status = wo.status
    if data.status:
        if data.status not in VALID_STATUS:
            raise HTTPException(status_code=400, detail="Invalid work order status")
        wo.status = data.status
        wo.updated_at = _utc_now()
        if data.status == "completed" and not wo.completed_at:
            wo.completed_at = _utc_now()

    record = await _add_record(
        db,
        wo,
        user,
        data.action_type,
        content=data.content,
        before_status=before_status,
        after_status=wo.status,
    )
    await db.commit()
    await db.refresh(record)
    return MaintenanceRecordResponse.model_validate(record)


@router.post("/{workorder_id}/send-email")
async def send_workorder_email(
    workorder_id: int,
    data: WorkOrderEmailRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(WorkOrder).where(WorkOrder.id == workorder_id, WorkOrder.deleted_at.is_(None))
    )
    wo = result.scalar_one_or_none()
    if not wo:
        raise HTTPException(status_code=404, detail="WorkOrder not found")

    config_result = await db.execute(select(NotificationConfig).where(NotificationConfig.user_id == user.id))
    config = config_result.scalar_one_or_none()
    if not config:
        config = NotificationConfig(
            user_id=user.id,
            hi_threshold=70.0,
            email_enabled=True,
            email_address=user.email,
            wechat_enabled=False,
        )
        db.add(config)
        await db.commit()
        await db.refresh(config)
    logger.info(
        "Workorder email setting: user_id=%s username=%s config_id=%s email_enabled=%s",
        user.id,
        user.username,
        config.id,
        config.email_enabled,
    )
    if not config.email_enabled:
        raise HTTPException(status_code=400, detail="Email notification is disabled in settings")

    recipients = await _recipient_emails(data, wo, db)
    if not recipients:
        raise HTTPException(status_code=400, detail="No recipient email found for work order assignee")

    subject = data.subject or f"[Fengdiao PHM] WO-{wo.id:04d} {wo.title}"

    # Build rich email body (plain + HTML) unless caller already provided content
    if data.content:
        body = data.content
        html_body = None
    else:
        turbine = await _fetch_turbine_info(wo, db)
        ai_section = await _try_ai_analysis(wo, db, user)
        knowledge = await _fetch_fault_knowledge(wo, db)
        body = _workorder_plain_body(wo, turbine, ai_section, knowledge)
        html_body = _workorder_html_body(wo, turbine, ai_section, knowledge)

    logs = []
    sent_count = 0
    failed_count = 0
    for recipient in recipients:
        try:
            await send_email(recipient, subject, body, html_body=html_body)
            logs.append({"recipient_email": recipient, "status": "sent", "error_message": None})
            db.add(
                NotificationLog(
                    work_order_id=workorder_id,
                    recipient_email=recipient,
                    subject=subject,
                    status="sent",
                    sent_at=_utc_now(),
                )
            )
            sent_count += 1
        except EmailConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except SMTPRecipientsRefused as exc:
            refused = exc.recipients or {}
            details = []
            for email, error in refused.items():
                code, message = error
                if isinstance(message, bytes):
                    message = message.decode("utf-8", errors="replace")
                details.append(f"{email}: {code} {message}")
            error_message = "Recipient mailbox unavailable or refused: " + "; ".join(details)
            logs.append({"recipient_email": recipient, "status": "failed", "error_message": error_message})
            db.add(
                NotificationLog(
                    work_order_id=workorder_id,
                    recipient_email=recipient,
                    subject=subject,
                    status="failed",
                    error_message=error_message,
                )
            )
            failed_count += 1
        except Exception as exc:
            error_message = str(exc)
            logs.append({"recipient_email": recipient, "status": "failed", "error_message": error_message})
            db.add(
                NotificationLog(
                    work_order_id=workorder_id,
                    recipient_email=recipient,
                    subject=subject,
                    status="failed",
                    error_message=error_message,
                )
            )
            failed_count += 1

    if sent_count == 0 and failed_count > 0:
        await db.commit()
        first_error = logs[0]["error_message"] if logs else "Email send failed"
        raise HTTPException(status_code=502, detail=first_error)

    if sent_count:
        wo.notification_sent_at = _utc_now()
        wo.updated_at = _utc_now()
        await _add_record(
            db,
            wo,
            user,
            "email_sent",
            content=f"Sent email to {sent_count} recipient(s)",
            before_status=wo.status,
            after_status=wo.status,
        )
    await db.commit()

    return {
        "work_order_id": workorder_id,
        "sent": sent_count,
        "failed": failed_count,
        "logs": logs,
    }
