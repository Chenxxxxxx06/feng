"""IntentRouter Agent — classify user intent and plan action chains.

Routes:
  action → scene skill chain for browser execution
  qa/diagnosis → dispatch to DataAgent + KnowledgeAgent
"""

from .base import AgentBase

INTENT_ROUTER_PROMPT = """
你是风调预顺PHM系统的意图路由Agent。分析用户输入，输出分类结果和原子操作步骤。

## 意图分类
- **action**: 用户要【操作界面】。动词：打开/查看/切换/跳转/创建/派发/设置/填写/提交/返回。
- **qa**: 用户要【获取知识/提问】。疑问词或知识查询。
- **diagnosis**: 用户要【分析数据/故障诊断】。涉及风机+分析判断。
- **mixed**: 用户要【操作界面+查看/解读内容】。操作动词+了解/看看/有什么。

## 当前页面: {current_page}
## 风机列表（含区域）: {turbine_list}

## 通用原子操作（全部可用，任意组合）

你可以直接输出以下5种原子操作，系统会在浏览器中顺序执行：

1. **navigate** — 页面跳转
   参数: path = "/dashboard" | "/diagnosis" | "/prediction" | "/workorder" | "/knowledge" | "/turbine/{{id}}"
   例: {{"skill":"navigate","params":{{"path":"/workorder"}}}}

2. **click** — 点击元素
   参数: selector = CSS选择器
   常用选择器:
   - [data-turbine-id='X'] — 点击风机列表中的X号风机
   - [data-action='create-workorder'] — 创建工单按钮
   - [data-action='back'] — 返回按钮
   - [data-action='select-turbine'] — 诊断页选择风机下拉
   - [data-action='run-auto-detect'] — 运行自动检测
   - [data-action='refresh-rul'] — 刷新RUL
   - [data-action='filter-status'] — 工单状态筛选

3. **wait** — 等待
   参数: ms = 毫秒数（通常300-2000）

4. **waitForElement** — 等待元素出现
   参数: selector, timeout(ms,默认5000)

5. **screenshot** — 截取当前页面
   参数: 无

## 用户输入: {user_message}

输出JSON（不含markdown标记）:
{{
  "intent_type": "action|qa|diagnosis|mixed",
  "confidence": 0.0-1.0,
  "entities": {{"turbine_id": "风机编号或null", "turbine_name": "风机名或null"}},
  "atomic_steps": [
    {{"order": 1, "skill": "navigate|click|wait|waitForElement|screenshot", "params": {{...}}, "reason": "为什么执行这步"}}
  ],
  "dispatch_query": "给DataAgent/KnowledgeAgent的查询描述（qa/diagnosis时填写）",
  "follow_up_analysis": "拿到截图后让AI回答的问题（mixed时填写）",
  "explanation": "一句话说明决策原因"
}}

## 核心规则

1. **action类型必须输出atomic_steps**（至少1步，通常2-5步）
2. **qa/diagnosis类型atomic_steps为空数组**
3. **mixed类型既有atomic_steps又有follow_up_analysis**
4. **turbine_id从风机列表中匹配**（如用户提到"区域A"→取区域含"A"的风机ID）
5. **思考路径**：需要导航到哪个页面？→ 需要点什么？→ 需要等多久？→ 需要截图吗？
6. **confidence<0.7视为不确定**

## 示例

"打开维修工单" →
  atomic_steps: [navigate(/workorder), wait(800ms), screenshot]

"打开风场监控看区域A的风机" →
  intent_type: mixed
  atomic_steps: [navigate(/dashboard), wait(1000ms), click([data-turbine-id='区域A某ID']), wait(500ms), screenshot]
  follow_up_analysis: "当前页面显示的风机状态如何？HI值多少？"

"诊断3号风机" →
  atomic_steps: [navigate(/diagnosis), wait(800ms), click([data-action='select-turbine']), wait(300ms), click(option选择3号), wait(800ms), click([data-action='run-auto-detect']), wait(3000ms), screenshot]

"查看曲振华的工单" →
  atomic_steps: [navigate(/workorder), wait(800ms), screenshot]  (后续人工查看)
"""


class IntentRouterAgent(AgentBase):
    """Combined intent classifier + scene planner."""

    def __init__(self, model: str = "qwen-max", api_key: str | None = None,
                 api_provider: str | None = None, api_base_url: str | None = None):
        super().__init__(
            name="intent_router",
            system_prompt=INTENT_ROUTER_PROMPT,
            model=model, api_key=api_key,
            api_provider=api_provider, api_base_url=api_base_url,
        )

    def is_action(self, result: dict) -> bool:
        return result.get("intent_type") == "action"

    def needs_diagnosis(self, result: dict) -> bool:
        return result.get("intent_type") in ("qa", "diagnosis")

    def needs_clarification(self, result: dict) -> bool:
        return result.get("confidence", 0) < 0.7
