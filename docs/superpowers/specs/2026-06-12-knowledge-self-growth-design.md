# AI 对话 → 知识图谱自增长 — 设计规格书

> 日期: 2026-06-12 | 版本: v1.0 | 状态: Draft

---

## 1. 概述

### 1.1 问题

故障百科初始只有 6 个预设节点，覆盖面有限。现实中风电故障类型远不止这些。每次用户通过 Copilot 诊断出一个真实问题，其中包含宝贵的故障知识，但这些知识从未被沉淀。

### 1.2 目标

**Copilot 每次成功诊断 → 自动提取结构化知识 → 自动加入知识图谱 → 知识库越用越丰富。**

```
第1天: 6 个种子节点
第10天: 累积 15 个节点 (含 AI 提取)
第30天: 累积 30+ 个节点 (含案例经验)
```

---

## 2. 整体流程

```
用户对话结束 (对话 > 4轮 且 含诊断结论)
        │
        ▼
┌─────────────────────────────────────────────────────┐
│ ① QualityGate: 对话质量检测                           │
│   检查: 轮数/诊断结论/用户确认/去重                      │
│   不满足 → 跳过 (静默，不打扰用户)                       │
└────────────────────┬────────────────────────────────┘
                     ▼
┌─────────────────────────────────────────────────────┐
│ ② KnowledgeExtractor (LLM)                          │
│   输入: 完整对话历史                                   │
│   → 提取故障类型 + 症状 + 根因 + 方案 + 案例            │
│   → 输出结构化 JSON + 置信度分数                        │
└────────────────────┬────────────────────────────────┘
                     ▼
┌─────────────────────────────────────────────────────┐
│ ③ Dedup Engine (语义去重)                             │
│   LLM 对比提取结果 vs 已有知识节点                       │
│   相似 → 合并 (追加案例/补全症状)                        │
│   不相似 → 新建节点                                    │
└────────────────────┬────────────────────────────────┘
                     ▼
┌─────────────────────────────────────────────────────┐
│ ④ Auto-Ingest: 写入数据库                             │
│   INSERT / UPDATE fault_knowledge                    │
│   标记: source="ai_extracted", verified=False         │
│   置信度 ≥ 0.8 → 前端正常展示                           │
│   置信度 0.5~0.8 → 展示 + ⚠️ 待验证标签                 │
│   置信度 < 0.5 → 仅后台可见 (不入图谱)                    │
└────────────────────┬────────────────────────────────┘
                     ▼
┌─────────────────────────────────────────────────────┐
│ ⑤ 前端展示: 卡片标注 AI 来源                            │
│   🤖 AI提取 · 置信度82% · [确认] [修正] [删除]         │
└─────────────────────────────────────────────────────┘
```

---

## 3. 数据结构扩展

### 3.1 Model 新增字段

```python
# backend/app/models/__init__.py — FaultKnowledgeNode 新增

source = Column(String(32), default="manual")
# "manual" — 人工录入
# "seed" — 预设种子数据
# "ai_extracted" — AI 对话提取

confidence = Column(Float, default=1.0)
# AI 提取的置信度 0.0~1.0
# 人工录入始终为 1.0

verified = Column(Boolean, default=True)
# 是否经过人工确认
# AI 提取默认 False

extracted_from = Column(Text, nullable=True)
# 原始对话摘要，用于溯源:
# "2026-06-12 用户admin诊断3号风机振动异常 → 确认齿轮箱点蚀"
```

### 3.2 迁移

字段均为可空 + 有默认值，不需要迁移脚本。`create_all()` 自动新增列。

---

## 4. 各组件详细设计

### 4.1 QualityGate — 对话质量检测

```python
# backend/app/services/knowledge_extractor.py

class QualityGate:
    MIN_TURNS = 4                     # 最少4轮对话
    CONCLUSION_KEYWORDS = [
        "故障", "诊断", "原因", "方案", "修复",
        "建议", "更换", "检查", "维修", "停机",
    ]
    USER_CONFIRM_KEYWORDS = [
        "好的", "谢谢", "明白了", "就这个", "对",
        "确认", "可以", "行", "OK", "是的",
    ]
    USER_REJECT_KEYWORDS = [
        "不对", "不是", "重新", "换个", "错了",
        "不行", "再试", "不确定",
    ]

    def should_extract(self, messages: list[dict]) -> bool:
        if len(messages) < self.MIN_TURNS:
            return False

        assistant_msgs = [m for m in messages if m["role"] == "assistant"]
        if not assistant_msgs:
            return False

        last_reply = assistant_msgs[-1]["content"]
        if not any(kw in last_reply for kw in self.CONCLUSION_KEYWORDS):
            return False

        user_msgs = [m for m in messages if m["role"] == "user"]
        if user_msgs:
            last_user = user_msgs[-1]["content"]
            if any(kw in last_user for kw in self.USER_REJECT_KEYWORDS):
                return False

        return True
```

### 4.2 KnowledgeExtractor — LLM 提取

```python
EXTRACTOR_PROMPT = """
你是风电故障知识提取器。从以下用户与AI助手的对话中，提取结构化的故障知识。

对话历史:
{messages}

请提取为 JSON:
{{
  "fault_type": "故障名称 (如: 齿轮箱点蚀)",
  "category": "分类 (齿轮箱/轴承/叶片/发电机/偏航/传动/电气/塔筒/其他)",
  "severity": "严重度 (low/medium/high/critical)",
  "symptoms": [
    {{"indicator": "振动RMS", "threshold": ">12 mm/s", "unit": "mm/s"}}
  ],
  "root_causes": ["根因1", "根因2"],
  "solutions": [
    {{"action": "更换齿轮油", "difficulty": "medium", "downtime_hours": 8}}
  ],
  "spare_parts": [
    {{"name": "SKF轴承", "quantity": 2, "est_cost": 8000}}
  ],
  "case_summary": {{
    "turbine": "风机名称或编号",
    "summary": "1-2句话描述问题发现和解决过程",
    "resolution": "最终解决方案",
    "total_cost": 估算费用数字或null,
    "downtime_days": 估算停机天数或null
  }},
  "confidence": 0.0-1.0之间的数字,
  "reason": "简短说明为什么这个置信度"
}}

要求:
1. 只提取对话中**明确提到**的信息，不要编造
2. 没有提到的字段用 [] 或 null
3. confidence 评分: 症状+根因+方案都明确 → 0.8+; 只有症状 → 0.5-0.7; 推测 → <0.5
4. 如果对话中完全没有故障诊断内容，返回 {{"skip": true, "reason": "..."}}
"""
```

### 4.3 Dedup Engine — 语义去重

```python
DEDUP_PROMPT = """
判断以下两个风电故障是否指向**同一类故障**。

故障A (已有):
- 故障名: {existing.fault_type}
- 分类: {existing.category}
- 症状: {existing.symptoms_text}
- 根因: {existing.root_causes_text}

故障B (新提取):
- 故障名: {extracted.fault_type}
- 分类: {extracted.category}
- 症状: {extracted.symptoms_text}
- 根因: {extracted.root_causes_text}

输出 JSON:
{{
  "is_same": true/false,
  "similarity": 0.0-1.0,
  "reason": "一句话说明",
  "merge_suggestion": "如为同一故障，建议如何合并"
}}

判断标准:
- 故障名不同但本质相同 (如 "齿轮点蚀" vs "齿轮箱齿面点蚀") → 同一
- 症状高度重叠 (≥2个相同指标) + 分类相同 → 可能同一
- 分类不同 → 不同
"""
```

### 4.4 Auto-Ingest — 自动入库

```python
async def auto_ingest(extracted: dict, dedup_result: dict, messages: list[dict]):
    async with async_session() as db:
        if dedup_result["is_same"]:
            # 合并到已有节点: 追加案例 + 补全新症状/方案
            existing = await db.get(FaultKnowledgeNode, existing_id)
            existing.cases = (existing.cases or []) + [extracted["case_summary"]]
            if extracted["symptoms"]:
                existing.symptoms = _merge_unique(existing.symptoms or [], extracted["symptoms"])
            if extracted["solutions"]:
                existing.solutions = _merge_unique(existing.solutions or [], extracted["solutions"])
            if extracted["root_causes"]:
                existing.root_causes = _merge_unique(existing.root_causes or [], extracted["root_causes"])
            existing.confidence = max(existing.confidence, extracted["confidence"])
        else:
            # 新建节点
            node = FaultKnowledgeNode(
                fault_type=extracted["fault_type"],
                category=extracted.get("category", "其他"),
                icon=_pick_icon(extracted.get("category")),
                severity=extracted.get("severity", "medium"),
                symptoms=extracted.get("symptoms", []),
                root_causes=extracted.get("root_causes", []),
                solutions=extracted.get("solutions", []),
                spare_parts=extracted.get("spare_parts", []),
                cases=[extracted["case_summary"]] if extracted.get("case_summary") else [],
                source="ai_extracted",
                confidence=extracted["confidence"],
                verified=False,
                extracted_from=_build_extraction_summary(messages),
            )
            db.add(node)
        await db.commit()
```

---

## 5. 触发时机

```python
# backend/app/api/ai.py — 在现有 /ai/copilot 端点中追加

@router.post("/copilot")
async def copilot_chat(request: CopilotRequest, ...):
    # ... 现有 LLM 调用逻辑 ...
    reply = await qwen_client.chat(...)

    # 追加: 异步提取知识 (不阻塞响应)
    background_tasks.add_task(try_extract_knowledge, request.messages + [{"role": "assistant", "content": reply}])

    return {"reply": reply}
```

异步执行，用户无感知。提取失败不影响对话体验。

---

## 6. 前端改动

### 6.1 知识卡片标注

```tsx
// KnowledgeBasePage.tsx — 卡片新增来源标签
{node.source === 'ai_extracted' && (
  <span className={`px-1.5 py-0.5 rounded text-[9px] font-medium ${
    node.verified
      ? 'bg-accent-green/20 text-accent-green'
      : 'bg-accent-yellow/20 text-accent-yellow'
  }`}>
    🤖 AI · {Math.round(node.confidence * 100)}%{!node.verified && ' ⚠️'}
  </span>
)}
```

### 6.2 快速审核入口

卡片 hover 时显示：
```
[确认] [修正] [删除]
```
点击"确认" → `PATCH /api/knowledge-base/{id}/verify` → `verified: true`

---

## 7. API 新增端点

```python
# backend/app/api/knowledge.py 追加

@router.patch("/knowledge-base/{node_id}/verify")
async def verify_node(node_id: int, db: AsyncSession = Depends(get_db)):
    """人工确认 AI 提取的知识节点"""
    node = await db.get(FaultKnowledgeNode, node_id)
    if not node:
        raise HTTPException(404)
    node.verified = True
    node.confidence = 1.0
    await db.commit()
    return {"status": "verified"}

@router.delete("/knowledge-base/{node_id}")
async def delete_node(node_id: int, db: AsyncSession = Depends(get_db)):
    """删除知识节点 (AI提取的可直接删)"""
    node = await db.get(FaultKnowledgeNode, node_id)
    if not node:
        raise HTTPException(404)
    await db.delete(node)
    await db.commit()
    return {"status": "deleted"}
```

---

## 8. 图谱自动更新

知识图谱页面已经有 `useEffect` 拉取 `/knowledge-graph`。前端在 CopilotFAB 关闭后自动刷新图谱：

```typescript
// KnowledgeBasePage.tsx 新增
useEffect(() => {
  const handleFocus = () => {
    api.get('/knowledge-graph').then(({ data }) => setGraphData(data)).catch(() => {});
  };
  window.addEventListener('focus', handleFocus);
  return () => window.removeEventListener('focus', handleFocus);
}, []);
```

用户切回故障百科页面时自动拉取最新图谱数据。

---

## 9. 实现计划

| 阶段 | 内容 | 文件 |
|------|------|------|
| **Phase 1** | Model 加字段 (source/confidence/verified/extracted_from) | `models/__init__.py` |
| **Phase 2** | KnowledgeExtractor + QualityGate + Dedup | `services/knowledge_extractor.py` (新建) |
| **Phase 3** | Auto-Ingest 逻辑 | 同上 |
| **Phase 4** | Copilot 端点追加异步触发 | `api/ai.py` (修改) |
| **Phase 5** | 前端卡片标签 + 审核按钮 + 图谱自动刷新 | `KnowledgeBasePage.tsx` |
| **Phase 6** | verify/delete API | `api/knowledge.py` |

---

## 10. 风险

| 风险 | 缓解 |
|------|------|
| AI 提取出低质量/错误知识 | 置信度 < 0.5 不入库; 前端标注 ⚠️ 待验证; 管理员可一键删除 |
| LLM 调用成本 (提取 + 去重 = 2次 LLM) | 对话质量门控减少触发; 异步执行不阻塞用户 |
| 重复提取同一诊断 | 7天内去重缓存; 语义相似度 > 0.95 直接跳过 |
| 提取 Latency 影响 Copilot 响应 | `background_tasks.add_task` 异步执行 |
