"""Data Agent — queries real-time turbine data from DB."""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from .base import AgentBase

DATA_AGENT_PROMPT = """
你是风调预顺PHM数据分析Agent。你有以下数据库表的访问权限。

表结构:
- turbines: id, name, model, power_mw, region, status, hi_value, last_maintenance
- scada_records: turbine_id, timestamp, power_kw, wind_speed_ms, rotor_rpm,
  gen_temperature_c, gearbox_temperature_c, bearing_temperature_c, pitch_angle_deg, extra
- faults: turbine_id, detected_at, fault_type, confidence, status
- rul_predictions: turbine_id, component, remaining_life_days, confidence_lower, confidence_upper

当前数据:
{data_context}

查询任务: {query}

请基于以上数据输出JSON摘要:
{{
  "turbine_info": {{"id": ID, "name": "风机名", "status": "状态", "region": "区域"}},
  "current_scada": {{
    "振动RMS": {{"value": 数值, "threshold": 12, "status": "normal|anomaly"}},
    "齿轮箱温度": {{"value": 数值, "threshold": 80, "status": "normal|anomaly"}},
    "轴承温度": {{"value": 数值, "threshold": 75, "status": "normal|anomaly"}}
  }},
  "rul_status": {{"remaining_days": 天数或null, "urgency": "ok|watch|critical"}},
  "recent_faults": [{{"date": "日期", "type": "故障类型", "status": "状态"}}],
  "anomaly_summary": "一句话异常总结或正常"
}}

如果数据中没有明显异常，anomaly_summary 写"当前运行正常"。
"""


class DataAgent(AgentBase):
    def __init__(self, model: str = "qwen-max", api_key: str | None = None, api_provider: str | None = None, api_base_url: str | None = None):
        super().__init__(name="data_agent", system_prompt=DATA_AGENT_PROMPT, model=model, api_key=api_key, api_provider=api_provider, api_base_url=api_base_url)

    async def gather_context(self, turbine_id: int | None, db: AsyncSession) -> dict:
        """Gather real-time data from DB for the agent to analyze."""
        from app.models import Turbine, SCADARecord, Fault, RULPrediction

        ctx: dict = {"turbines": [], "scada_summary": [], "faults": [], "rul": []}

        # Turbines
        stmt = select(Turbine)
        if turbine_id:
            stmt = stmt.where(Turbine.id == turbine_id)
        result = await db.execute(stmt)
        ctx["turbines"] = [
            {"id": t.id, "name": t.name, "status": t.status, "region": t.region,
             "power_mw": t.power_mw, "last_maintenance": str(t.last_maintenance) if t.last_maintenance else None}
            for t in result.scalars().all()
        ]

        # Latest SCADA (per turbine)
        if turbine_id:
            scada_result = await db.execute(
                select(SCADARecord).where(SCADARecord.turbine_id == turbine_id)
                .order_by(desc(SCADARecord.timestamp)).limit(20)
            )
            for row in scada_result.scalars().all():
                extra = row.extra or {}
                ctx["scada_summary"].append({
                    "timestamp": str(row.timestamp),
                    "power_kw": row.power_kw, "wind_speed_ms": row.wind_speed_ms,
                    "gen_temp": row.gen_temperature_c, "gearbox_temp": row.gearbox_temperature_c,
                    "bearing_temp": row.bearing_temperature_c,
                    "vibration_rms": extra.get("vibration_rms"),
                })

        # Recent faults
        fault_stmt = select(Fault).order_by(desc(Fault.detected_at)).limit(10)
        if turbine_id:
            fault_stmt = fault_stmt.where(Fault.turbine_id == turbine_id)
        fault_result = await db.execute(fault_stmt)
        ctx["faults"] = [
            {"turbine_id": f.turbine_id, "date": str(f.detected_at), "type": f.fault_type, "status": f.status}
            for f in fault_result.scalars().all()
        ]

        # RUL
        rul_stmt = select(RULPrediction).order_by(desc(RULPrediction.predicted_at)).limit(10)
        if turbine_id:
            rul_stmt = rul_stmt.where(RULPrediction.turbine_id == turbine_id)
        rul_result = await db.execute(rul_stmt)
        ctx["rul"] = [
            {"turbine_id": r.turbine_id, "component": r.component, "remaining_days": r.remaining_life_days}
            for r in rul_result.scalars().all()
        ]

        return ctx
