# 风电故障知识图谱 & 百科 — 设计规格书

> 日期: 2026-06-11 | 版本: v2.0 | 状态: Draft
> v2.0 更新: 新增多 Agent 协作诊断架构 (Orchestrator → Data Agent + Knowledge Agent → Synthesizer)

---

## 1. 概述

### 1.1 目标

两个目标联动：

**A. 故障百科页面** — 在侧边栏新增页面。结构化风电故障知识图谱（故障类型 → 症状 → 根因 → 解决方案 → 历史案例 → 备件），支持搜索、可视化浏览。

**B. 多 Agent 协作诊断** — 现有 Copilot 悬浮窗接驳多 Agent 架构。用户自然语言提问，Orchestrator 调度 Data Agent（查实时数据库）+ Knowledge Agent（查知识图谱），Synthesizer 汇总输出诊断报告。

### 1.2 页面位置

```
侧边栏 (AppLayout.tsx):
  风场监控      /dashboard
  故障诊断      /diagnosis
  预测决策      /prediction
  维修工单      /workorder
→ 故障百科      /knowledge     ← 新增
  系统设置      /settings
```

---

## 2. 多 Agent 协作诊断架构

### 2.1 核心思路

用户通过 CopilotFAB 悬浮窗提问 → 不再是单一 LLM 回答，而是**四个 Agent 协作**：

```
┌──────────────────────────────────────────────────────────────┐
│                    CopilotFAB 悬浮窗                          │
│  "3号风机振动RMS超标到15.2，齿轮箱温度85°C，是什么问题？"       │
└────────────────────────┬─────────────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────────────┐
│              ① Orchestrator Agent (调度器)                    │
│                                                              │
│  职责: 理解意图 → 判断需要什么数据 → 并行调度子Agent            │
│                                                              │
│  输入: "3号风机振动RMS超标到15.2，齿轮箱温度85°C，什么问题?"     │
│  输出:                                                       │
│    intent: "fault_diagnosis"                                 │
│    entities: {turbine_id:3, symptoms:["振动超标","温度高"]}     │
│    dispatch: [                                               │
│      {agent:"data_agent",    query:"3号风机实时SCADA+历史故障"}, │
│      {agent:"knowledge_agent", query:"振动超标+齿轮箱高温→哪些故障"} │
│    ]                                                        │
└─────────────┬───────────────────────────┬───────────────────┘
              │                           │
    ┌─────────▼──────────┐     ┌──────────▼─────────────────┐
    │ ② Data Agent       │     │ ③ Knowledge Agent          │
    │  (数据智能体)        │     │  (知识图谱智能体)            │
    │                    │     │                            │
    │ 数据源:             │     │ 数据源:                     │
    │ • SCADA 实时数据    │     │ • fault-kb.json / DB       │
    │ • 历史故障表        │     │ • 故障症状/根因/方案/案例    │
    │ • RUL 预测          │     │                            │
    │ • 振动频谱          │     │ 能力:                      │
    │                    │     │ • 语义匹配症状→故障          │
    │ 能力:               │     │ • 检索关联故障              │
    │ • SQL 查询生成      │     │ • 推荐方案+备件             │
    │ • 时序异常检测      │     │ • 引用历史案例              │
    │ • 阈值对比          │     │                            │
    └─────────┬──────────┘     └──────────┬─────────────────┘
              │                           │
              └───────────┬───────────────┘
                          ▼
┌──────────────────────────────────────────────────────────────┐
│              ④ Synthesizer Agent (汇总输出)                    │
│                                                              │
│  职责: 接收 Data Agent + Knowledge Agent 的输出 → 综合诊断报告  │
│                                                              │
│  输入:                                                       │
│    data_result: {                                            │
│      turbine: "陕北3号",                                      │
│      current_rms: 15.2 (阈值:12),                            │
│      gearbox_temp: 85°C (阈值:80),                           │
│      rul: 14天,                                              │
│      history: ["2025-01 轴承更换", "2025-06 齿轮箱油液异常"]   │
│    }                                                         │
│    knowledge_result: {                                       │
│      top_match: "齿轮箱点蚀 (置信度78%)",                      │
│      symptoms_matched: ["振动RMS>12","温度>85°C"],            │
│      solutions: ["激光熔覆","更换齿轮油"],                      │
│      similar_case: "2025.03 陕北2号 (修复后正常)",             │
│      related_risk: "轴承磨损 (伴生60%)"                        │
│    }                                                         │
│                                                              │
│  输出: 结构化诊断报告（见下方示例）                               │
└────────────────────────┬─────────────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────────────┐
│              CopilotFAB 展示最终回复                           │
│                                                              │
│  🔍 诊断报告: 3号风机疑似齿轮箱点蚀                             │
│                                                              │
│  📊 实时数据 (Data Agent):                                    │
│    振动RMS: 15.2 mm/s (⚠️超标26%)                             │
│    齿轮箱温度: 85°C (⚠️超标6%)                                │
│    RUL预测: 剩余14天                                          │
│    历史: 2025-01轴承更换 / 2025-06齿轮箱油液异常                │
│                                                              │
│  📚 知识匹配 (Knowledge Agent):                               │
│    最可能: 齿轮箱点蚀 (匹配置信度 78%)                           │
│    匹配症状: ✅振动RMS超标 ✅温度超标 ⚠️油液分析待确认           │
│    推荐方案: ①换油+清洗油路(8h) ②激光熔覆(48h) ③换齿轮(72h)     │
│    相似案例: 2025.03 陕北2号风机 — 激光熔覆后运行正常             │
│    ⚠️ 关联风险: 轴承磨损 (伴生60%)                              │
│                                                              │
│  💡 建议: 立即安排停机检查，优先做油液金属颗粒分析确认诊断。        │
│     如果确认点蚀，建议48h激光熔覆，预计成本¥35K。                 │
│                                                              │
│  [📋 一键创建工单]  [📊 查看SCADA趋势]                         │
└──────────────────────────────────────────────────────────────┘
```

### 2.2 Agent 职责矩阵

| Agent | 运行位置 | LLM | 数据接入 | 输出 |
|-------|----------|-----|----------|------|
| **Orchestrator** | 后端 | Qwen/gpt-4 | 无(纯逻辑) | intent + dispatch plan |
| **Data Agent** | 后端 | Qwen/gpt-4 | DB API (SCADA/故障/RUL/振动) | 结构化数据摘要 |
| **Knowledge Agent** | 后端 | Qwen/gpt-4 | fault-kb.json → API → DB | 故障匹配 + 方案推荐 |
| **Synthesizer** | 后端 | Qwen/gpt-4 | Data output + Knowledge output | 综合诊断报告 |

### 2.3 调用链路

```
CopilotFAB → POST /api/agent/diagnose
                │
                ▼
            OrchestratorAgent.run(user_message, context)
                │
                ├─ parse_intent()      → Intent
                ├─ plan_dispatch()     → [{agent, query}]
                │
                ├─ async parallel:
                │   ├─ DataAgent.run(query, db_session)
                │   │   ├─ generate_sql()       → 查询语句
                │   │   ├─ execute_query()      → 原始数据
                │   │   └─ summarize_data()     → 数据摘要
                │   │
                │   └─ KnowledgeAgent.run(query)
                │       ├─ semantic_search()    → 匹配故障节点
                │       ├─ match_symptoms()     → 症状置信度
                │       └─ enrich_with_cases()  → 历史案例
                │
                └─ SynthesizerAgent.run(data_result, knowledge_result)
                    ├─ cross_validate()    → 交叉验证
                    ├─ generate_report()   → 诊断报告
                    └─ suggest_actions()   → 建议行动
                        │
                        ▼
                  返回给 CopilotFAB
```

---

## 3. 数据架构

### 3.1 双数据源

```
故障百科页面:
  1. 先读 fault-kb.json → 即时渲染
  2. 再调 GET /api/knowledge-base → 覆盖更新
  3. API 超时 → 继续用 JSON

Agent 诊断:
  Data Agent    → DB 直查 (SCADA / faults / rul / turbines)
  Knowledge Agent → /api/knowledge-base (可 fallback JSON)
```

### 3.2 预设数据 JSON

（以下保留 3 个完整示例节点，实际扩展到 15+）

```json
{
  "version": "1.0",
  "nodes": [
    {
      "id": "gearbox_pitting",
      "fault_type": "齿轮箱点蚀",
      "category": "齿轮箱",
      "icon": "⚙️",
      "severity": "high",
      "symptoms": [
        {"indicator": "振动RMS", "threshold": ">12 mm/s", "unit": "mm/s"},
        {"indicator": "油液金属颗粒", "threshold": ">200 ppm", "unit": "ppm"},
        {"indicator": "齿轮箱温度", "threshold": ">85°C", "unit": "°C"}
      ],
      "root_causes": [
        "润滑不足或润滑油变质",
        "长期过载运行",
        "齿轮材料制造缺陷",
        "齿面接触应力过大"
      ],
      "solutions": [
        {"action": "更换齿轮油并清洗油路", "difficulty": "medium", "downtime_hours": 8},
        {"action": "齿面修复（激光熔覆）", "difficulty": "high", "downtime_hours": 48},
        {"action": "更换齿轮副", "difficulty": "high", "downtime_hours": 72}
      ],
      "related_faults": [
        {"id": "bearing_wear", "name": "轴承磨损", "probability": 0.6},
        {"id": "shaft_misalignment", "name": "轴对中不良", "probability": 0.3}
      ],
      "spare_parts": [
        {"name": "SKF-32222 圆锥滚子轴承", "quantity": 2, "est_cost": 8000},
        {"name": "Shell Omala S4 GX 320 齿轮油", "quantity": 200, "est_cost": 3000}
      ],
      "cases": [
        {
          "turbine": "陕北2号风机",
          "date": "2025-03-15",
          "summary": "振动RMS突增至15.2 mm/s，油液分析发现金属颗粒浓度超标。停机检查确认齿轮箱二级齿轮齿面点蚀。激光熔覆修复后恢复正常，至今运行良好。",
          "resolution": "激光熔覆齿面修复",
          "total_cost": 35000,
          "downtime_days": 3
        }
      ]
    },
    {
      "id": "bearing_wear",
      "fault_type": "轴承磨损",
      "category": "轴承",
      "icon": "🔩",
      "severity": "medium",
      "symptoms": [
        {"indicator": "振动高频分量", "threshold": ">5 kHz 峰值突增", "unit": ""},
        {"indicator": "轴承温度", "threshold": ">75°C", "unit": "°C"},
        {"indicator": "包络谱特征频率", "threshold": "匹配BPFO/BPFI", "unit": ""}
      ],
      "root_causes": [
        "润滑脂不足或污染",
        "安装不当导致偏载",
        "电蚀（轴电流）",
        "疲劳剥落"
      ],
      "solutions": [
        {"action": "补充/更换润滑脂", "difficulty": "easy", "downtime_hours": 4},
        {"action": "更换轴承", "difficulty": "medium", "downtime_hours": 16},
        {"action": "检查并消除轴电流", "difficulty": "hard", "downtime_hours": 24}
      ],
      "related_faults": [
        {"id": "gearbox_pitting", "name": "齿轮箱点蚀", "probability": 0.5},
        {"id": "shaft_misalignment", "name": "轴对中不良", "probability": 0.4}
      ],
      "spare_parts": [
        {"name": "SKF-32222 圆锥滚子轴承", "quantity": 2, "est_cost": 8000},
        {"name": "SKF LGHP 2 高温润滑脂", "quantity": 5, "est_cost": 500}
      ],
      "cases": [
        {
          "turbine": "陕北5号风机",
          "date": "2025-01-20",
          "summary": "巡检发现发电机驱动端轴承温度持续升高，包络分析确认轴承内圈故障特征频率。更换轴承后恢复正常。",
          "resolution": "更换发电机驱动端轴承",
          "total_cost": 12000,
          "downtime_days": 1
        }
      ]
    },
    {
      "id": "blade_erosion",
      "fault_type": "叶片前缘侵蚀",
      "category": "叶片",
      "icon": "🪶",
      "severity": "medium",
      "symptoms": [
        {"indicator": "功率曲线偏离", "threshold": ">5% 同风速下功率下降", "unit": "%"},
        {"indicator": "叶片图像", "threshold": "前缘可见粗糙/凹坑", "unit": ""},
        {"indicator": "振动低频异常", "threshold": "<1 Hz 分量增大", "unit": ""}
      ],
      "root_causes": [
        "风沙/雨滴长期冲蚀",
        "叶片涂层老化失效",
        "雷击损伤",
        "安装运输过程中的磕碰"
      ],
      "solutions": [
        {"action": "叶片前缘修复贴膜", "difficulty": "medium", "downtime_hours": 24},
        {"action": "重新涂装保护涂层", "difficulty": "medium", "downtime_hours": 48},
        {"action": "更换叶片", "difficulty": "high", "downtime_hours": 120}
      ],
      "related_faults": [
        {"id": "blade_crack", "name": "叶片裂纹", "probability": 0.3},
        {"id": "imbalance", "name": "转子不平衡", "probability": 0.5}
      ],
      "spare_parts": [
        {"name": "3M 风电叶片保护膜 W8607", "quantity": 1, "est_cost": 15000},
        {"name": "PPG PSX 700 聚硅氧烷涂料", "quantity": 50, "est_cost": 8000}
      ],
      "cases": [
        {
          "turbine": "关中1号风机",
          "date": "2024-11-08",
          "summary": "SCADA功率曲线分析发现同风速下输出下降约8%，无人机巡检确认叶片前缘有明显冲蚀痕迹。贴膜修复后功率恢复。",
          "resolution": "叶片前缘贴膜修复",
          "total_cost": 22000,
          "downtime_days": 2
        }
      ]
    }
  ]
}
```

### 3.3 后端 Model

```python
# backend/app/models/__init__.py 新增

class FaultKnowledgeNode(Base):
    __tablename__ = "fault_knowledge"
    id = Column(Integer, primary_key=True, index=True)
    fault_type = Column(String(128), unique=True, nullable=False, index=True)
    category = Column(String(64), nullable=False, index=True)
    icon = Column(String(8), default="⚠️")
    severity = Column(String(16), default="medium")
    symptoms = Column(JSON, default=list)
    root_causes = Column(JSON, default=list)
    solutions = Column(JSON, default=list)
    related_faults = Column(JSON, default=list)
    spare_parts = Column(JSON, default=list)
    cases = Column(JSON, default=list)
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
```

### 3.4 后端 API

```python
# backend/app/api/knowledge.py (新建)

router = APIRouter(prefix="/api/knowledge-base", tags=["故障百科"])

@router.get("")
async def list_all(category: Optional[str] = None, severity: Optional[str] = None)

@router.get("/search")
async def search(q: str)

@router.get("/{node_id}")
async def get_detail(node_id: int)

@router.get("/categories")
async def get_categories()
```

---

## 4. 四个 Agent — Prompt 设计

### 4.1 Orchestrator Agent Prompt

```
System: 你是风调预顺PHM系统的调度智能体(Orchestrator)。你的职责是理解用户意图，然后分派任务给两个专业Agent。

可用子Agent:
1. data_agent: 查询风机实时数据(SCADA、历史故障、RUL预测、振动数据)
   输入: turbine_id, 需要的数据类型(scada/faults/rul/vibration)
   输出: 结构化数据摘要

2. knowledge_agent: 查询风电故障知识图谱
   输入: 症状描述或故障关键词
   输出: 匹配的故障类型、症状、根因、方案、案例

判断规则:
- 用户提到具体风机号/名称 → 必须调用 data_agent
- 用户描述症状/故障现象 → 必须调用 knowledge_agent
- 用户问"什么原因"/"怎么修"/"需要什么备件" → 两个都调用
- 用户问通用故障知识(不涉及具体风机) → 只调用 knowledge_agent
- 用户查数据(不涉及故障诊断) → 只调用 data_agent

输出 JSON 格式:
{
  "intent_type": "fault_diagnosis" | "knowledge_query" | "data_query" | "general_chat",
  "entities": {"turbine_id": 3, "symptoms": ["振动超标", "温度高"], ...},
  "dispatch": [
    {"agent": "data_agent", "priority": 1, "query": "查询3号风机当前SCADA数据、历史故障、RUL"},
    {"agent": "knowledge_agent", "priority": 1, "query": "振动超标+齿轮箱温度高→匹配故障类型+方案"}
  ],
  "explanation": "用户提到3号风机和振动/温度异常症状，需要实时数据+知识库匹配"
}

当前可用风机列表: {turbine_list}

用户消息: {user_message}
```

### 4.2 Data Agent Prompt

```
System: 你是风调预顺PHM系统的数据分析智能体(Data Agent)。你可以查询以下数据库表，将原始数据转化为人类可读的摘要。

数据库 Schema:
- turbines: id, name, model, power_mw, region, status, hi_value, last_maintenance, source_dataset
- scada_records: turbine_id, timestamp, power_kw, wind_speed_ms, rotor_rpm, gen_temperature_c, gearbox_temperature_c, bearing_temperature_c, pitch_angle_deg, vibration_rms
- faults: turbine_id, detected_at, fault_type, confidence, status, details
- vibration_data: turbine_id, timestamp, component, rms, peak_freq_hz
- rul_predictions: turbine_id, component, remaining_life_days, confidence_lower, confidence_upper

你的能力:
1. 生成 SQL 查询或 ORM 调用
2. 识别异常数据(对比阈值: 振动RMS>12, 温度>80°C, 功率低于额定30%+)
3. 时间序列分析(趋势上升/下降/突变)
4. 关联历史故障模式

输出 JSON 格式:
{
  "turbine_info": {"id":3, "name":"陕北3号", "status":"normal", "region":"陕北", "power_mw":2.0},
  "current_scada": {
    "vibration_rms": {"value":15.2, "threshold":12, "status":"anomaly", "trend":"rising_3d"},
    "gearbox_temp": {"value":85, "threshold":80, "status":"anomaly"},
    "bearing_temp": {"value":68, "threshold":75, "status":"normal"},
    "power_kw": {"value":1850, "rated":2000, "status":"normal"}
  },
  "rul_status": {"component":"gearbox", "remaining_days":14, "urgency":"watch"},
  "recent_faults": [
    {"date":"2025-06-01", "type":"gearbox_oil_abnormal", "status":"resolved"},
    {"date":"2025-01-15", "type":"bearing_replace", "status":"resolved"}
  ],
  "anomaly_summary": "3号风机振动RMS(15.2)和齿轮箱温度(85°C)均超标，振动呈3日上升趋势。RUL预测齿轮箱剩余14天寿命。最近一次故障是6月的齿轮箱油液异常。",
  "raw_queries": ["SELECT * FROM scada_records WHERE turbine_id=3 ORDER BY timestamp DESC LIMIT 100", ...]
}

查询任务: {query}
```

### 4.3 Knowledge Agent Prompt

```
System: 你是风调预顺PHM系统的知识图谱智能体(Knowledge Agent)。你可以检索风电故障知识图谱，将症状映射到故障类型，并推荐方案。

知识图谱结构:
每个故障节点包含:
- fault_type: 故障名称
- category: 分类(齿轮箱/轴承/叶片/发电机/电气/塔筒)
- severity: 严重度(low/medium/high/critical)
- symptoms: [{indicator, threshold, unit}]
- root_causes: [原因列表]
- solutions: [{action, difficulty, downtime_hours}]
- related_faults: [{id, name, probability}]
- spare_parts: [{name, quantity, est_cost}]
- cases: [{turbine, date, summary, resolution, total_cost, downtime_days}]

你的能力:
1. 语义匹配: 用户描述的症状 → 匹配知识图谱中的故障类型
2. 症状覆盖度计算: 匹配了几项/还有哪些待确认
3. 方案推荐: 按难度+停机时间排序
4. 关联故障预警: 概率>30%的关联故障
5. 历史案例引用

输出 JSON 格式:
{
  "matches": [
    {
      "fault_type": "齿轮箱点蚀",
      "category": "齿轮箱",
      "severity": "high",
      "confidence": 0.78,
      "symptoms_matched": [
        {"indicator":"振动RMS", "user_observed":"振动超标到15.2", "kb_threshold":">12 mm/s", "match":true},
        {"indicator":"齿轮箱温度", "user_observed":"齿轮箱温度85°C", "kb_threshold":">85°C", "match":true},
        {"indicator":"油液金属颗粒", "user_observed":"未提及", "kb_threshold":">200 ppm", "match":false}
      ],
      "recommended_solutions": [
        {"action":"更换齿轮油并清洗油路", "difficulty":"medium", "downtime_hours":8, "priority":1},
        {"action":"齿面修复(激光熔覆)", "difficulty":"hard", "downtime_hours":48, "priority":2}
      ],
      "related_risks": [
        {"name":"轴承磨损", "probability":0.6, "reason":"齿轮箱点蚀产生的金属颗粒会加速轴承磨损"}
      ],
      "best_case": {"turbine":"陕北2号风机", "date":"2025-03", "resolution":"激光熔覆", "result":"运行正常至今"}
    }
  ],
  "recommend_next": "建议确认油液金属颗粒浓度，以区分齿轮箱点蚀和一般性润滑油老化"
}

知识图谱数据: {knowledge_context}
查询任务: {query}
```

### 4.4 Synthesizer Agent Prompt

```
System: 你是风调预顺PHM系统的诊断汇总智能体(Synthesizer)。你接收Data Agent和Knowledge Agent的输出，综合生成一份完整的诊断报告。

你的能力:
1. 交叉验证: Data Agent的实时数据 ↔ Knowledge Agent的故障模板
2. 置信度计算: 综合数据异常度 + 症状匹配度
3. 生成诊断报告: 结构化、可操作
4. 建议下一步行动

输出格式 (Markdown，直接展示给用户):

## 🔍 诊断报告

**风机**: {turbine_name} | **诊断时间**: {now}

### 📊 实时数据
| 指标 | 当前值 | 阈值 | 状态 |
|------|--------|------|------|
| 振动RMS | 15.2 mm/s | 12 mm/s | ⚠️ 超标 |
...

**异常摘要**: {anomaly_summary}

### 📚 故障匹配
**最可能**: {fault_type} (置信度 {confidence}%)
- 匹配症状: {matched}
- 待确认: {unmatched}

### 💡 建议方案
1. [优先级1] {action} (难度:{difficulty}, 停机:{hours}h)
2. ...

### ⚠️ 关联风险
- {related_fault} (伴生概率 {probability}%)

### 📖 相似案例
- {date} {turbine} — {summary} → {resolution}

### 🎯 建议行动
{actionable_next_steps}

---

要求:
1. 报告要简洁，控制在 300 字以内
2. 紧急项(severity=high/critical)用 ⚠️ 标记
3. 如果两个Agent结论矛盾，标注差异并给出你的判断
4. 始终给出明确的下一步行动建议
5. 如果数据不足以确定诊断，诚实说明"建议补充以下检查"

Data Agent 输出: {data_result}
Knowledge Agent 输出: {knowledge_result}
```

---

## 5. CopilotFAB 接驳方式

### 5.1 后端新增 API

```python
# backend/app/api/agent.py (扩展现有，新增诊断端点)

@router.post("/agent/diagnose")
async def multi_agent_diagnose(
    request: DiagnoseRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    多Agent协作诊断入口。
    CopilotFAB 发来用户消息 → 四个Agent协作 → 返回诊断报告。
    """
    # 1. Orchestrator 解析意图
    intent = await orchestrator.run(
        user_message=request.message,
        turbine_list=await get_turbine_list(db),
    )

    # 2. 并行调度 Data Agent + Knowledge Agent
    async with asyncio.TaskGroup() as tg:
        if intent.needs("data_agent"):
            data_task = tg.create_task(data_agent.run(
                query=intent.dispatch["data_agent"].query,
                db=db,
            ))
        if intent.needs("knowledge_agent"):
            knowledge_task = tg.create_task(knowledge_agent.run(
                query=intent.dispatch["knowledge_agent"].query,
                kb_data=load_knowledge_base(),
            ))

    # 3. Synthesizer 汇总
    report = await synthesizer.run(
        data_result=data_task.result() if intent.needs("data_agent") else None,
        knowledge_result=knowledge_task.result() if intent.needs("knowledge_agent") else None,
    )

    return {
        "intent": intent.dict(),
        "report": report,
        "trace": {  # Debug: 每个Agent的耗时
            "orchestrator_ms": intent.duration_ms,
            "data_agent_ms": data_task.duration_ms if data_task else 0,
            "knowledge_agent_ms": knowledge_task.duration_ms if knowledge_task else 0,
        }
    }
```

### 5.2 前端调用

```typescript
// CopilotFAB.tsx — 发送消息时自动走多Agent诊断

const handleSendMessage = async (text: string) => {
  // 判断是否触发诊断模式
  const isDiagnosisQuery = detectDiagnosisIntent(text);
  // 关键词: 风机/振动/温度/故障/异常/什么原因/怎么修/怎么办

  if (isDiagnosisQuery) {
    const { report, trace } = await api.post('/api/agent/diagnose', { message: text });
    // 展示 Markdown 格式的诊断报告
    appendMessage({ role: 'assistant', content: report, type: 'diagnosis_report', trace });
  } else {
    // 普通对话走原有 qwen_client
    const reply = await api.post('/api/ai/copilot', { messages, ... });
    appendMessage({ role: 'assistant', content: reply, type: 'chat' });
  }
};
```

---

## 6. 前端设计 (故障百科页面)

### 6.1 组件树

```
KnowledgeBasePage
├── PageHeader             — 标题 "故障百科" + 统计卡片
├── SearchAndFilterBar     — 搜索框 + 分类下拉 + 严重度筛选
├── FaultGraph             — ECharts 树图可视化
│   ├── 根节点: "风电故障"
│   ├── 一级: 齿轮箱 / 轴承 / 叶片 / 发电机 / 电气 / 塔筒
│   └── 二级: 具体故障节点 (可点击)
├── FaultCardGrid          — 卡片网格(视图切换: 图谱 / 列表)
│   └── FaultCard × N
└── FaultDetailDrawer      — 右侧滑出详情面板
    ├── SymptomTable / RootCauseList / SolutionTimeline
    ├── CaseCarousel / RelatedFaultLinks / SparePartTable
    └── DiagnoseButton     — "🤖 AI诊断此故障" → 打开 Copilot + 多Agent诊断
```

### 6.2 文件清单

| 文件 | 说明 |
|------|------|
| `frontend/src/pages/Knowledge/KnowledgeBasePage.tsx` | 主页面 |
| `frontend/src/pages/Knowledge/FaultGraph.tsx` | ECharts 树图 |
| `frontend/src/pages/Knowledge/FaultCard.tsx` | 故障卡片 |
| `frontend/src/pages/Knowledge/FaultDetailDrawer.tsx` | 详情侧边栏 |
| `frontend/src/data/fault-kb.json` | 预设数据 JSON |
| `frontend/src/services/knowledgeApi.ts` | API 客户端 |
| `frontend/src/types/knowledge.ts` | 类型定义 |
| `backend/app/api/knowledge.py` | 知识库 CRUD API |
| `backend/app/api/agent.py` | **多Agent诊断 API (扩展)** |
| `backend/app/services/agents/` | **新建目录: 四个Agent实现** |

### 6.3 路由注册

```tsx
// App.tsx
const KnowledgeBasePage = lazy(() => import('./pages/Knowledge/KnowledgeBasePage'));
<Route path="knowledge" element={<Suspense fallback={<PageLoader />}><KnowledgeBasePage /></Suspense>} />

// AppLayout.tsx (插入 workorder 与 settings 之间)
{ path: '/knowledge', icon: '📚', label: '故障百科' },
```

---

## 7. Agent 实现文件

```
backend/app/services/agents/
├── __init__.py
├── base.py              # AgentBase 基类 (LLM call + JSON parse + trace)
├── orchestrator.py      # OrchestratorAgent
├── data_agent.py        # DataAgent (DB query + summarize)
├── knowledge_agent.py   # KnowledgeAgent (KB search + match)
└── synthesizer.py       # SynthesizerAgent (merge + report)
```

### 7.1 Agent Base

```python
# base.py
class AgentBase:
    def __init__(self, name: str, system_prompt: str, model: str = "qwen-max"):
        self.name = name
        self.system_prompt = system_prompt
        self.model = model

    async def run(self, **kwargs) -> AgentResult:
        t0 = time.time()
        prompt = self.system_prompt.format(**kwargs)
        response = await self._call_llm(prompt)
        parsed = self._parse_json(response)
        return AgentResult(
            agent=self.name,
            data=parsed,
            duration_ms=int((time.time() - t0) * 1000),
        )

    async def _call_llm(self, prompt: str) -> str:
        # 调用 qwen_client 或 openai
        ...

    def _parse_json(self, text: str) -> dict:
        # 从 LLM 输出中提取 JSON
        ...
```

---

## 8. ECharts 树图配置

```typescript
// FaultGraph.tsx 核心配置

const graphOption: EChartsOption = {
  tooltip: {
    trigger: 'item',
    formatter: (params: any) => {
      if (params.data.type === 'fault') {
        return `<b>${params.name}</b><br/>
          严重度: ${params.data.severity}<br/>
          症状数: ${params.data.symptomCount}<br/>
          历史案例: ${params.data.caseCount} 起`;
      }
      return `<b>${params.name}</b><br/>${params.data.desc || ''}`;
    }
  },
  series: [{
    type: 'tree',
    data: [buildTreeData()],
    top: '5%', left: '8%', bottom: '5%', right: '20%',
    symbolSize: 10,
    orient: 'LR',
    label: { position: 'left', verticalAlign: 'middle', align: 'right', fontSize: 12 },
    leaves: {
      label: { position: 'right', verticalAlign: 'middle', align: 'left' }
    },
    expandAndCollapse: true,
    animationDuration: 550,
    animationDurationUpdate: 750,
  }]
};

function buildTreeData() {
  return {
    name: '风电故障',
    children: categories.map(cat => ({
      name: cat.name,
      desc: `${cat.count} 种故障`,
      children: cat.faults.map(f => ({
        name: f.fault_type,
        type: 'fault',
        severity: f.severity,
        symptomCount: f.symptoms.length,
        caseCount: f.cases.length,
        value: f.id,
      }))
    }))
  };
}
```

---

## 9. Agent 操作 Skill 注册

```json
{
  "/knowledge": {
    "component": "KnowledgeBasePage",
    "capabilities": ["search", "browse", "view-detail", "ai-diagnose"],
    "actions": [
      {"name": "搜索故障", "trigger": "input", "selector": "[data-action='search-knowledge']"},
      {"name": "筛选分类", "trigger": "click", "selector": "[data-action='filter-category']"},
      {"name": "点击故障卡片", "trigger": "click", "selector": "[data-action='open-fault-detail']"},
      {"name": "切换视图", "trigger": "click", "selector": "[data-action='toggle-view']"},
      {"name": "AI诊断此故障", "trigger": "click", "selector": "[data-action='diagnose-fault']"}
    ],
    "search": {
      "fields": ["fault_type", "symptoms", "root_causes", "solutions"],
      "placeholder": "搜索故障名称、症状、根因..."
    },
    "detail_panel": {
      "sections": ["symptoms", "root_causes", "solutions", "cases", "related_faults", "spare_parts"],
      "copilot_ready": true,
      "multi_agent_diagnose": true
    }
  }
}
```

---

## 10. 实现计划

| 阶段 | 任务 | 文件 | 优先级 |
|------|------|------|--------|
| **Phase 1: 数据** | 创建 `fault-kb.json` (15+ 节点) | `src/data/fault-kb.json` | P0 |
| | TypeScript 类型定义 | `src/types/knowledge.ts` | P0 |
| | 后端 Model + seed | `models/__init__.py` + `seed_data.py` | P0 |
| **Phase 2: Agent** | AgentBase 基类 | `services/agents/base.py` | P0 |
| | Orchestrator Agent | `services/agents/orchestrator.py` | P0 |
| | Data Agent (DB查询) | `services/agents/data_agent.py` | P0 |
| | Knowledge Agent (KB检索) | `services/agents/knowledge_agent.py` | P0 |
| | Synthesizer Agent (汇总) | `services/agents/synthesizer.py` | P0 |
| | Agent 诊断 API 端点 | `api/agent.py` | P0 |
| **Phase 3: 前端** | 知识库 API 客户端 | `services/knowledgeApi.ts` | P1 |
| | 主页面 + 路由 + 侧边栏 | `KnowledgeBasePage` + `App.tsx` + `AppLayout.tsx` | P1 |
| | 搜索 + 卡片网格 | `SearchBar` + `FaultCard` | P1 |
| | ECharts 树图 | `FaultGraph.tsx` | P1 |
| | 详情侧边栏 + AI诊断按钮 | `FaultDetailDrawer.tsx` | P1 |
| **Phase 4: 集成** | CopilotFAB 接驳多Agent | `CopilotFAB.tsx` | P0 |
| | 诊断报告 Markdown 渲染 | 报告展示组件 | P1 |
| **Phase 5: 验收** | 搜索/筛选/树图/详情/AI诊断 | 全链路测试 | |

---

## 11. 风险 & 注意事项

| 风险 | 缓解 |
|------|------|
| LLM 输出 JSON 格式不稳定 | AgentBase 内置重试+格式修正；temperature=0.3 |
| Data Agent SQL 生成不准 | 预设常见查询模板，LLM 只填参数不写完整 SQL |
| 两个 Agent 结论矛盾 | Synthesizer 标注差异 + 给出综合置信度 |
| Agent 调用链超时 (多个 LLM 串行) | Orchestrator 调度 Data + Knowledge 并行；单 Agent 超时 10s |
| JSON / DB 数据不同步 | 启动时打印 diff；seed 脚本覆盖 JSON → DB |
| ECharts 大量节点卡顿 | 树图默认折叠二级；列表视图作为备选 |
