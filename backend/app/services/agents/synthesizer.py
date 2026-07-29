"""Synthesizer Agent — merges Data + Knowledge results into final report."""

from .base import AgentBase, AgentResult

SYNTHESIZER_PROMPT = """
你是风调预顺PHM诊断汇总专家。你收到两个Agent的输出，请综合生成诊断报告。

Data Agent 输出:
{data_result}

Knowledge Agent 输出:
{knowledge_result}

请用以下Markdown格式输出报告(简洁，300字以内):

## 🔍 诊断报告

**风机**: {{turbine_name}} | **诊断时间**: {{now}}

### 📊 当前可用数据（以响应中的数据来源和时间范围为准）
| 指标 | 当前值 | 阈值 | 状态 |
|------|--------|------|------|
(列出关键指标，异常标⚠️)

**异常摘要**: (一句话)

### 📚 故障匹配
**最可能**: {{fault_type}} (置信度 {{confidence}}%)
- ✅ 匹配症状: ...
- ⚠️ 待确认: ...

### 💡 建议方案
1. [P1] {{action}} ({{difficulty}}, 停机{{hours}}h)
2. [P2] ...

### ⚠️ 关联风险
- {{risk_name}} (伴生{{probability}}%)

### 📖 相似案例
- {{date}} {{turbine}} — {{summary}} → {{resolution}}

### 🎯 建议行动
(1-2句 actionable next step)

---

要求:
1. 两个Agent结论矛盾时，标注差异并给出综合判断
2. 没有任何异常时诚实写"当前运行正常"
3. 数据不足时写"建议补充XX检查"
4. 紧急问题(severity=high/critical)开头加⚠️
"""


class SynthesizerAgent(AgentBase):
    def __init__(self, model: str = "qwen-max", api_key: str | None = None, api_provider: str | None = None, api_base_url: str | None = None):
        super().__init__(name="synthesizer", system_prompt=SYNTHESIZER_PROMPT, model=model, api_key=api_key, api_provider=api_provider, api_base_url=api_base_url)

    async def run(self, **kwargs) -> AgentResult:
        """Override: synthesizer outputs Markdown, not JSON."""
        import time
        from .base import AgentResult
        t0 = time.time()
        try:
            prompt = self.system_prompt.format(**kwargs)
            # Synthesizer outputs Markdown report, skip JSON parsing
            response = await self._call_llm(prompt, override_system="你是专业的诊断报告撰写专家。请直接输出Markdown格式的诊断报告。")
            return AgentResult(agent=self.name, data={"reply": response}, duration_ms=int((time.time() - t0) * 1000))
        except Exception as e:
            return AgentResult(agent=self.name, data={}, duration_ms=int((time.time() - t0) * 1000), error=str(e))
