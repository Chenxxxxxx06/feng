"""DEPRECATED: Diagnosis orchestration layer.

This module is NOT imported by any code path. All diagnosis logic has been
moved directly into app/api/diagnosis.py. The stubs here referenced disabled
simulators (blade_simulator, vibration_loader) that raise RuntimeError.

Keep this file for reference until blade/vibration ML models are deployed.
"""
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Fault, FaultKnowledgeNode, FaultSignal, Turbine
from app.schemas import (
    AutoFaultDetectionRequest,
    AutoFaultDetectionResponse,
    BatchAutoFaultDetectionRequest,
    BatchAutoFaultDetectionResponse,
    BatchAutoFaultRecord,
    BladeDiagnosisResponse,
    DiagnosisSignalInsight,
    TroubleshootingStep,
    VibrationPreviewResponse,
)
from app.services.data_pipeline.blade_simulator import blade_simulator
from app.services.data_pipeline.vibration_loader import vibration_loader


FAULT_LABELS = {
    "bearing_inner_race_wear": "轴承内圈磨损",
    "bearing_outer_race": "轴承外圈故障",
    "bearing_ball": "轴承滚动体故障",
    "gearbox_tooth_pitting": "齿轮箱齿面点蚀",
    "gearbox_tooth_wear": "齿轮箱齿面磨损",
    "generator_overheat": "发电机过热",
    "blade_leading_edge_erosion": "叶片前缘腐蚀",
    "pitch_system_fault": "变桨系统故障",
    "main_shaft_misalignment": "主轴不对中",
    "cooling_system_fault": "冷却系统故障",
    "electrical_connection": "电气连接异常",
    "no_fault_detected": "未识别到明确故障",
}

KNOWLEDGE_ALIASES = {
    "bearing_inner_race_wear": ["轴承磨损", "轴承内圈故障", "轴承"],
    "bearing_outer_race": ["轴承磨损", "轴承外圈故障", "轴承"],
    "bearing_ball": ["轴承磨损", "轴承"],
    "gearbox_tooth_pitting": ["齿轮箱点蚀", "齿轮箱"],
    "gearbox_tooth_wear": ["齿轮箱点蚀", "齿轮箱"],
    "generator_overheat": ["发电机过热", "发电机"],
    "blade_leading_edge_erosion": ["叶片前缘腐蚀", "叶片"],
    "pitch_system_fault": ["变桨系统故障", "变桨"],
    "main_shaft_misalignment": ["轴对中不良", "主轴不对中"],
    "cooling_system_fault": ["冷却系统故障", "冷却"],
    "electrical_connection": ["电气连接异常", "电气"],
}

SIGNAL_DEFAULTS = {
    "振动RMS值": ("4.8 mm/s", "< 2.8 mm/s", "振动能量高于健康阈值"),
    "轴承温度": ("82 C", "< 75 C", "轴承温度偏高，需结合润滑状态排查"),
    "发电机温度": ("91 C", "< 85 C", "发电机热负荷偏高"),
    "功率偏差": ("-9.6%", "±5%", "同风速区间功率输出偏低"),
    "频率特征": ("132 Hz", "无显著峰值", "存在疑似故障特征频率峰值"),
    "FFT峰值": ("132 Hz", "无显著峰值", "频谱峰值需要进一步确认"),
}

CAUSE_SCENARIOS = [
    [
        ("振动RMS值", "5.2 mm/s", "< 2.8 mm/s", 0.86, "high", "高速轴振动能量持续抬升，疑似轴承游隙或润滑不足。"),
        ("包络谱峰值", "BPFO 3.1x", "无稳定边带", 0.79, "high", "包络谱出现外圈通过频率边带，建议复核轴承外圈。"),
        ("润滑油温差", "13 C", "< 8 C", 0.61, "medium", "油温差偏大，可能存在润滑流量不足或油品劣化。"),
        ("机舱振动横向量", "0.34 g", "< 0.18 g", 0.43, "low", "横向振动同步升高，需排除基础或联轴器对中问题。"),
    ],
    [
        ("齿轮啮合频率", "286 Hz", "无显著峰值", 0.84, "high", "齿轮啮合频率及二倍频增强，疑似齿面磨损或局部点蚀。"),
        ("齿轮箱油温", "88 C", "< 78 C", 0.72, "high", "油温超过同风速工况均值，需检查冷却回路和油位。"),
        ("金属颗粒趋势", "上升 18%", "稳定", 0.58, "medium", "磨粒趋势上升，建议安排油液取样。"),
        ("扭矩波动", "±11.4%", "±6%", 0.39, "low", "传动链扭矩波动偏大，需关联偏航和风速波动。"),
    ],
    [
        ("发电机绕组温度", "104 C", "< 92 C", 0.82, "high", "绕组温度高于健康阈值，疑似散热或负载异常。"),
        ("冷却风机电流", "偏低 16%", "±5%", 0.68, "high", "冷却风机电流偏低，需检查风机转速和滤网堵塞。"),
        ("无功功率波动", "±9.8%", "±4%", 0.52, "medium", "电气侧波动放大，可能与并网控制或连接松动有关。"),
        ("环境温度修正", "+2.7 C", "< +1 C", 0.31, "low", "环境修正后仍偏热，排除单纯天气因素。"),
    ],
    [
        ("叶片图像损伤区域", "0.42 m2", "< 0.05 m2", 0.88, "high", "前缘区域存在连续磨蚀痕迹，需复拍确认扩展范围。"),
        ("功率曲线偏差", "-8.9%", "±5%", 0.71, "high", "同风速段功率低于基准曲线，疑似气动效率下降。"),
        ("桨距角偏差", "2.4 deg", "< 1 deg", 0.57, "medium", "桨距角偏差与功率损失同步出现，需检查变桨校准。"),
        ("巡检间隔", "78 天", "< 45 天", 0.35, "low", "巡检间隔偏长，建议缩短复检周期。"),
    ],
    [
        ("主轴轴向振动", "0.28 g", "< 0.15 g", 0.81, "high", "轴向振动持续偏高，疑似主轴不对中或支撑刚度下降。"),
        ("联轴器温度", "76 C", "< 65 C", 0.67, "high", "联轴器温度偏高，需检查对中和紧固状态。"),
        ("偏航误差", "8.6 deg", "< 5 deg", 0.49, "medium", "偏航误差扩大，可能增加传动链交变载荷。"),
        ("塔筒一阶响应", "增强 12%", "稳定", 0.28, "low", "塔筒响应略有增强，建议结合风况复核。"),
    ],
]


def _fault_label(fault_type: str) -> str:
    return FAULT_LABELS.get(fault_type, fault_type)


def _confidence_interval(confidence: float) -> list[float]:
    lower = max(0.0, confidence - 0.07)
    upper = min(1.0, confidence + 0.04)
    return [round(lower, 2), round(upper, 2)]


def _insight_from_signal(signal: FaultSignal) -> DiagnosisSignalInsight:
    value, normal_range, finding = SIGNAL_DEFAULTS.get(
        signal.sensor_name,
        ("待接入", "待接入", "该传感器被模型标记为相关信号"),
    )
    return DiagnosisSignalInsight(
        sensor_name=signal.sensor_name,
        value=value,
        normal_range=normal_range,
        contribution_score=round(signal.contribution_score, 3),
        priority=signal.priority,
        finding=finding,
    )


def _scenario_insights(fault_type: str, turbine_id: int | None) -> list[DiagnosisSignalInsight]:
    if "blade" in fault_type:
        scenario = CAUSE_SCENARIOS[3]
    elif "gearbox" in fault_type:
        scenario = CAUSE_SCENARIOS[1]
    elif "generator" in fault_type or "electrical" in fault_type or "cooling" in fault_type:
        scenario = CAUSE_SCENARIOS[2]
    elif "shaft" in fault_type:
        scenario = CAUSE_SCENARIOS[4]
    elif fault_type == "no_fault_detected":
        scenario = CAUSE_SCENARIOS[(turbine_id or 0) % len(CAUSE_SCENARIOS)]
    else:
        scenario = CAUSE_SCENARIOS[(turbine_id or 0) % len(CAUSE_SCENARIOS)]

    return [
        DiagnosisSignalInsight(
            sensor_name=name,
            value=value,
            normal_range=normal_range,
            contribution_score=round(max(0.1, score - ((turbine_id or 0) % 3) * 0.03), 3),
            priority=priority,
            finding=finding,
        )
        for name, value, normal_range, score, priority, finding in scenario
    ]


def _fallback_insights(fault_type: str, turbine_id: int | None = None) -> list[DiagnosisSignalInsight]:
    return _scenario_insights(fault_type, turbine_id)


def build_signal_insights(
    signals: list[FaultSignal],
    fault_type: str,
    turbine_id: int | None = None,
) -> list[DiagnosisSignalInsight]:
    if signals:
        base = [_insight_from_signal(signal) for signal in signals]
        names = {signal.sensor_name for signal in base}
        extras = [signal for signal in _scenario_insights(fault_type, turbine_id) if signal.sensor_name not in names]
        return base + extras[:3]
    return _fallback_insights(fault_type, turbine_id)


def build_fallback_troubleshooting_steps(
    fault_type: str,
    insights: list[DiagnosisSignalInsight],
) -> list[TroubleshootingStep]:
    label = _fault_label(fault_type)
    top_signal = insights[0].sensor_name if insights else "最高贡献信号"
    return [
        TroubleshootingStep(
            order=1,
            title="确认异常数据",
            action=f"复核{top_signal}的原始采样、时间戳和传感器状态，排除缺采、漂移或通信异常。",
            expected_effect="确认诊断输入可信，避免把数据质量问题误判为设备故障。",
        ),
        TroubleshootingStep(
            order=2,
            title="现场复测",
            action=f"围绕{label}执行振动复测、温度复测或图像复拍，并记录同工况下的对比数据。",
            expected_effect="获得可复现证据，判断故障是否持续或扩大。",
        ),
        TroubleshootingStep(
            order=3,
            title="部件专项检查",
            action="检查润滑、紧固、冷却、叶片表面和电气连接等与高贡献信号相关的部件。",
            expected_effect="定位可维修原因，形成备件、停机窗口和工单建议。",
        ),
        TroubleshootingStep(
            order=4,
            title="闭环跟踪",
            action="处理后持续观察24小时HI、RMS、温度和功率偏差趋势，并更新故障状态。",
            expected_effect="验证处理效果，降低重复告警和二次故障风险。",
        ),
    ]


async def _knowledge_node_for_fault(db: AsyncSession, fault_type: str) -> FaultKnowledgeNode | None:
    candidates = [fault_type, _fault_label(fault_type), *KNOWLEDGE_ALIASES.get(fault_type, [])]
    for candidate in dict.fromkeys(c for c in candidates if c):
        result = await db.execute(
            select(FaultKnowledgeNode)
            .where(FaultKnowledgeNode.fault_type == candidate)
            .limit(1)
        )
        node = result.scalar_one_or_none()
        if node:
            return node

    for candidate in dict.fromkeys(c for c in candidates if c):
        result = await db.execute(
            select(FaultKnowledgeNode)
            .where(FaultKnowledgeNode.fault_type.ilike(f"%{candidate}%"))
            .limit(1)
        )
        node = result.scalar_one_or_none()
        if node:
            return node

    result = await db.execute(
        select(FaultKnowledgeNode)
        .where(FaultKnowledgeNode.category.ilike(f"%{_fault_label(fault_type)[:2]}%"))
        .limit(1)
    )
    return result.scalar_one_or_none()


def _knowledge_text(items: list, keys: tuple[str, ...] = ("action", "name", "summary")) -> list[str]:
    values: list[str] = []
    for item in items:
        if isinstance(item, str):
            values.append(item)
            continue
        if isinstance(item, dict):
            value = next((str(item[key]) for key in keys if item.get(key)), "")
            if value:
                values.append(value)
    return values


async def build_troubleshooting_steps(
    db: AsyncSession,
    fault_type: str,
    insights: list[DiagnosisSignalInsight],
) -> list[TroubleshootingStep]:
    node = await _knowledge_node_for_fault(db, fault_type)
    if not node:
        return build_fallback_troubleshooting_steps(fault_type, insights)

    root_causes = _knowledge_text(node.root_causes or ())
    solutions = _knowledge_text(node.solutions or (), ("action", "summary", "name"))
    spare_parts = _knowledge_text(node.spare_parts or (), ("name", "action", "summary"))
    top_signal = insights[0].sensor_name if insights else "最高贡献信号"

    return [
        TroubleshootingStep(
            order=1,
            title="确认异常数据",
            action=f"复核{top_signal}的原始采样、时间戳和传感器状态，并与知识库症状记录交叉核对。",
            expected_effect="确认诊断输入可信，避免把数据质量问题误判为设备故障。",
        ),
        TroubleshootingStep(
            order=2,
            title="核对知识库根因",
            action="优先排查：" + "；".join(root_causes[:3]) if root_causes else "按知识库记录复核故障根因，必要时补充现场检测记录。",
            expected_effect="将故障定位过程收敛到已沉淀的知识库根因范围。",
        ),
        TroubleshootingStep(
            order=3,
            title="执行推荐处置",
            action="建议处置：" + "；".join(solutions[:3]) if solutions else "根据知识库推荐方案制定维修动作和停机窗口。",
            expected_effect="形成可执行的维修方案，并可流转为工单任务。",
        ),
        TroubleshootingStep(
            order=4,
            title="准备备件与闭环验证",
            action=(
                "备件关注：" + "；".join(spare_parts[:3]) + "。处理后持续观察24小时HI、RMS、温度和功率偏差趋势。"
                if spare_parts
                else "处理后持续观察24小时HI、RMS、温度和功率偏差趋势，并更新故障状态。"
            ),
            expected_effect="验证处理效果，降低重复告警和二次故障风险。",
        ),
    ]


async def run_auto_fault_identification(
    db: AsyncSession,
    request: AutoFaultDetectionRequest,
) -> AutoFaultDetectionResponse:
    result = await db.execute(
        select(Fault)
        .where(Fault.turbine_id == request.turbine_id)
        .order_by(Fault.detected_at.desc())
        .limit(1)
    )
    fault = result.scalar_one_or_none()

    if fault:
        signal_result = await db.execute(
            select(FaultSignal)
            .where(FaultSignal.fault_id == fault.id)
            .order_by(FaultSignal.contribution_score.desc())
        )
        signals = build_signal_insights(signal_result.scalars().all(), fault.fault_type, request.turbine_id)
        fault_type = fault.fault_type
        confidence = round(float(fault.confidence), 2)
        status = "suspected_fault"
        message = "已完成前后端诊断控制链路，当前结果来自数据库最近故障记录；真实频谱模型待接入。"
    else:
        fault_type = "no_fault_detected"
        confidence = 0.62
        status = "no_fault_detected"
        signals = _fallback_insights(fault_type, request.turbine_id)
        message = "未找到该风机历史故障记录；控制链路已就绪，真实自动识别算法待接入。"

    return AutoFaultDetectionResponse(
        turbine_id=request.turbine_id,
        component=request.component,
        analysis_window_hours=request.window_hours,
        status=status,
        fault_type=fault_type,
        confidence=confidence,
        confidence_interval=_confidence_interval(confidence),
        algorithm_status="stub_pending_external_model",
        message=message,
        generated_at=datetime.now(timezone.utc),
        signals=signals,
        troubleshooting_steps=await build_troubleshooting_steps(db, fault_type, signals),
    )


async def run_batch_auto_fault_identification(
    db: AsyncSession,
    request: BatchAutoFaultDetectionRequest,
) -> BatchAutoFaultDetectionResponse:
    q = select(Turbine)
    if request.turbine_ids:
        q = q.where(Turbine.id.in_(request.turbine_ids))
    if request.region:
        q = q.where(Turbine.region == request.region)
    if request.status:
        q = q.where(Turbine.status == request.status)
    q = q.order_by(Turbine.region.asc(), Turbine.name.asc())

    result = await db.execute(q)
    turbines = result.scalars().all()
    generated_at = datetime.now(timezone.utc)
    records: list[BatchAutoFaultRecord] = []
    group_summary: dict[str, int] = {}

    for turbine in turbines:
        detection = await run_auto_fault_identification(
            db,
            AutoFaultDetectionRequest(
                turbine_id=turbine.id,
                component=request.component,
                window_hours=request.window_hours,
                data_source=request.data_source,
            ),
        )
        group_key = turbine.region or "未分组"
        group_summary[group_key] = group_summary.get(group_key, 0) + 1
        records.append(
            BatchAutoFaultRecord(
                record_id=f"{turbine.id}-{generated_at.strftime('%Y%m%d%H%M%S')}",
                turbine_id=turbine.id,
                turbine_name=turbine.name,
                region=group_key,
                turbine_status=turbine.status,
                component=detection.component,
                analysis_window_hours=detection.analysis_window_hours,
                status=detection.status,
                fault_type=detection.fault_type,
                confidence=detection.confidence,
                confidence_interval=detection.confidence_interval,
                algorithm_status=detection.algorithm_status,
                message=detection.message,
                generated_at=detection.generated_at,
                group_key=group_key,
                signals=detection.signals,
                troubleshooting_steps=detection.troubleshooting_steps,
            )
        )

    return BatchAutoFaultDetectionResponse(
        success=bool(records),
        total=len(records),
        generated_at=generated_at,
        records=records,
        group_summary=group_summary,
        message="分组实时监测已同步，结果来自当前自动故障识别控制链路。"
        if records
        else "没有找到符合条件的风机，未生成分组监测记录。",
    )


def run_blade_image_diagnosis(turbine_id: int, image_path: str) -> BladeDiagnosisResponse:
    results = blade_simulator.generate_inspection(turbine_id, num_images=1)
    result = results[0]
    damage_type = result["damage_type"] or "no_damage"
    bbox = result["damage_bbox"]
    confidence = round(float(result["confidence"]), 2)
    regions = []
    if bbox:
        regions.append(
            {
                "label": _fault_label(damage_type),
                "bbox": bbox,
                "confidence": confidence,
            }
        )

    insights = _fallback_insights("blade_leading_edge_erosion")
    return BladeDiagnosisResponse(
        turbine_id=turbine_id,
        damage_type=damage_type,
        confidence=confidence,
        damage_bbox=bbox,
        image_path=image_path or result["image_path"],
        algorithm_status="stub_pending_external_model",
        message="叶片图像诊断前后端控制链路已完成；当前为占位结果，待接入真实CV模型接口。",
        damage_regions=regions,
        troubleshooting_steps=build_fallback_troubleshooting_steps(damage_type, insights),
    )


def get_vibration_preview(
    turbine_id: int,
    component: str,
    fault_type: str | None,
) -> VibrationPreviewResponse:
    data = vibration_loader.generate_waveform(
        turbine_id=turbine_id,
        component=component,
        fault_type=fault_type,
    )
    return VibrationPreviewResponse(
        turbine_id=turbine_id,
        component=component,
        timestamp=datetime.fromisoformat(data["timestamp"]),
        duration_seconds=data["duration_seconds"],
        sample_rate_hz=data["sample_rate_hz"],
        rms=data["rms"],
        waveform=data["waveform"],
        spectrum=data["spectrum"],
        peak_frequencies=data["peak_frequencies"],
        fault_detected=data["fault_detected"],
        algorithm_status="demo_waveform_only",
        message="振动算法暂未实现；当前仅提供前端波形展示用模拟数据和RMS占位值。",
    )
