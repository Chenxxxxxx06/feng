# 风调AI智能体操作引擎 — 设计规格书

> 日期: 2026-06-11 | 版本: v1.0 | 状态: Draft

---

## 1. 概述

### 1.1 目标

在现有 Copilot FAB 中内置一个"AI Agent 操作引擎"。用户用自然语言输入命令（如"给李工派一个巡检陕北3号风机的工单"），Agent 自动：

1. **解析意图** — 理解用户要做什么
2. **规划链路** — 拆解成操作步骤序列
3. **执行操作** — 在浏览器中执行切页面/点按钮/填表单
4. **反馈结果** — 在 Copilot 面板实时展示进度

### 1.2 核心洞察

**不做视觉识别。Agent 直接读取前端源码来理解页面结构。**

```
传统做法:  截图 → OCR → 猜按钮位置 → 模拟鼠标点击  ❌ 慢、脆、受分辨率影响
我们的做法: 读代码 → 知道确切DOM/路由 → 程序化执行  ✅ 快、稳、精准
```

---

## 2. 架构设计

### 2.1 整体数据流

```
用户输入 "给李工派巡检陕北3号风机的工单"
        │
        ▼
┌──────────────────────────────────────────┐
│         IntentParser (LLM)               │  ← 后端
│  自然语言 → 结构化意图 + 实体提取          │
│  输出: {intent:"create_workorder",        │
│         entities:{assignee:"李工",...}}    │
└──────────────────┬───────────────────────┘
                   ▼
┌──────────────────────────────────────────┐
│       PageManifest (源码知识库)           │  ← 前端构建时生成
│  每页面的路由/能力/表单/操作入口 JSON       │
│  例: /workorders → [create,edit,search]  │
└──────────────────┬───────────────────────┘
                   ▼
┌──────────────────────────────────────────┐
│          Planner (LLM)                   │  ← 后端
│  intent + manifest → Step[] 操作序列      │
│  [{step:1, action:"navigate",            │
│    target:"/workorders"},                │
│   {step:2, action:"click",               │
│    target:"[data-action='create']"},...]  │
└──────────────────┬───────────────────────┘
                   ▼
┌──────────────────────────────────────────┐
│       AgentExecutor (浏览器内)            │  ← 前端
│  逐个执行 Step: navigate→click→fill→     │
│  submit, 每步截图+状态反馈到Copilot        │
└──────────────────┬───────────────────────┘
                   ▼
┌──────────────────────────────────────────┐
│        CopilotFAB 步骤进度面板             │  ← 前端
│  ✅ 切换页面  ✅ 填表  ⏳ 提交...          │
└──────────────────────────────────────────┘
```

### 2.2 组件职责

| 组件 | 运行位置 | 职责 |
|------|----------|------|
| IntentParser | 后端 | LLM 解析自然语言 → 结构化意图 |
| PageManifest | 构建时 | 扫描 React 源码 → 页面能力 JSON |
| Planner | 后端 | LLM 结合意图+Manifest → 操作步骤 |
| AgentExecutor | 前端 | 浏览器内执行步骤，DOM 操作 |
| ProgressPanel | 前端 (CopilotFAB) | 展示步骤进度 + 截图确认 |

---

## 3. 详细设计

### 3.1 PageManifest — 源码知识库

#### 构建脚本: `scripts/generate-page-manifest.ts`

每次 `npm run build` 或 `npm run dev` 前执行，扫描 `frontend/src/pages/` 目录，提取每个页面的结构化信息。

#### 输出示例

```json
{
  "version": "1.0",
  "generated_at": "2026-06-11T22:00:00Z",
  "pages": {
    "/workorders": {
      "component": "WorkOrderPage",
      "capabilities": ["list", "create", "edit", "search", "filter", "delete"],
      "actions": [
        {"name": "新建工单", "trigger": "click", "selector": "[data-action='create-workorder']"},
        {"name": "提交工单", "trigger": "click", "selector": "[data-action='submit-workorder']"},
        {"name": "搜索",     "trigger": "click", "selector": "[data-action='search']"}
      ],
      "forms": {
        "WorkOrderCreate": {
          "fields": [
            {"name": "title",       "type": "text",          "label": "工单标题", "required": true},
            {"name": "assignee",    "type": "select-personnel","label": "负责人",   "required": true, "dataSource": "/api/personnel"},
            {"name": "turbine_id",  "type": "select-turbine", "label": "关联风机", "required": true, "dataSource": "/api/turbines"},
            {"name": "priority",    "type": "select",         "label": "优先级",   "options": ["low","medium","high"]},
            {"name": "due_date",    "type": "date",           "label": "截止日期"},
            {"name": "description", "type": "textarea",       "label": "描述"}
          ]
        }
      }
    },
    "/turbines/:id": {
      "component": "TurbineDetailPage",
      "capabilities": ["view", "diagnose", "predict"],
      "actions": [
        {"name": "发起诊断", "trigger": "click", "selector": "[data-action='start-diagnosis']"},
        {"name": "查看SCADA", "trigger": "click", "selector": "[data-action='view-scada']"}
      ]
    },
    "/diagnosis": {
      "component": "DiagnosisPage",
      "capabilities": ["view", "auto-detect", "batch-detect", "vibration-preview"],
      "actions": [
        {"name": "自动检测", "trigger": "click", "selector": "[data-action='auto-detect']"},
        {"name": "批量检测", "trigger": "click", "selector": "[data-action='batch-detect']"}
      ]
    },
    "/settings": {
      "component": "SettingsPage",
      "capabilities": ["view", "edit-threshold", "manage-datasource", "manage-personnel", "edit-profile"],
      "actions": [
        {"name": "添加人员", "trigger": "click", "selector": "[data-action='add-personnel']"}
      ],
      "forms": {
        "PersonnelCreate": {
          "fields": [
            {"name": "name",   "type": "text",  "label": "姓名", "required": true},
            {"name": "email",  "type": "text",  "label": "邮箱", "required": true},
            {"name": "skills", "type": "tags",  "label": "技能"},
            {"name": "region", "type": "select","label": "区域", "options": ["陕北","关中","陕南"]}
          ]
        }
      }
    }
  },
  "globalDataSources": {
    "personnel": "/api/personnel",
    "turbines": "/api/turbines",
    "faults": "/api/diagnosis/faults"
  }
}
```

#### 提取方式

脚本通过 AST 解析 + 约定式属性来提取信息：

1. **路由表**: 解析 `react-router` 配置或 `App.tsx` 的 `<Route>` 定义
2. **页面能力**: 扫描页面组件中的 `data-action` 属性
3. **表单字段**: 扫描 `data-field` 属性 + TypeScript 类型定义
4. **数据源**: `data-source` 属性 + `useEffect`/`useQuery` 中的 API 调用

### 3.2 页面埋点规范 — `data-*` 属性

给每个可交互元素加标准化属性。**渐进式添加，不影响现有功能。**

```tsx
// 按钮
<Button
  data-action="create-workorder"
  data-section="toolbar"
  onClick={handleCreate}
>
  新建工单
</Button>

// 表单
<Form data-action="workorder-form">
  <Input
    data-field="title"
    placeholder="工单标题"
    value={form.title}
    onChange={...}
  />
  <Select
    data-field="assignee"
    data-source="/api/personnel"
    data-label-field="name"
    data-value-field="id"
  />
  <DatePicker data-field="due_date" />
  <Button
    data-action="submit-workorder"
    data-confirm="确定要提交此工单吗？"
    onClick={handleSubmit}
  >
    提交
  </Button>
</Form>

// 导航链接
<NavLink data-action="navigate" data-target="/workorders">
  工单管理
</NavLink>
```

#### 属性规范

| 属性 | 说明 | 示例 |
|------|------|------|
| `data-action` | 操作类型 | `create-workorder`, `submit`, `search`, `delete` |
| `data-section` | 所属区域 | `toolbar`, `sidebar`, `form` |
| `data-field` | 表单字段名 | `title`, `assignee`, `turbine_id` |
| `data-source` | 数据来源 API | `/api/personnel` |
| `data-confirm` | 确认提示文案 | `"确定要提交吗？"` |
| `data-target` | 导航目标 | `/workorders` |
| `data-label-field` | 下拉选项的显示字段 | `name` |
| `data-value-field` | 下拉选项的值字段 | `id` |

### 3.3 IntentParser + Planner (后端)

#### 新增端点

```python
# backend/app/api/agent.py

@router.post("/agent/execute")
async def execute_agent_command(
    request: AgentCommandRequest,
    current_user: User = Depends(get_current_user),
):
    """
    接收自然语言命令，返回操作计划。
    前端拿到 plan 后由 AgentExecutor 逐步执行。
    """
    # 1. 加载 PageManifest
    manifest = load_page_manifest()

    # 2. Intent 解析 (LLM)
    intent = await parse_intent(
        command=request.command,
        manifest=manifest,
        user_context={"role": current_user.role, "username": current_user.username}
    )

    # 3. 链路规划 (LLM)
    plan = await generate_plan(
        intent=intent,
        manifest=manifest,
        page_context=request.current_page  # 用户当前所在页面
    )

    return AgentPlanResponse(intent=intent, steps=plan.steps, explanation=plan.explanation)
```

#### Intent 结构

```python
class AgentIntent(BaseModel):
    intent_type: str        # "create_workorder" | "view_turbine" | "run_diagnosis" | ...
    entities: dict          # {assignee: "李工", turbine: "陕北3号", task: "巡检"}
    confidence: float       # 0.0 - 1.0
    clarification: Optional[str]  # 如果 confidence < 0.7，反问用户确认

class AgentStep(BaseModel):
    order: int
    action: str             # "navigate" | "click" | "fill" | "submit" | "wait" | "confirm"
    target: Optional[str]   # selector 或路由路径
    fields: Optional[list[FieldValue]]  # fill 时用
    reason: str             # 为什么要做这步（展示给用户）
    fallback: Optional[str] # 如果失败，备选方案

class AgentPlanResponse(BaseModel):
    intent: AgentIntent
    steps: list[AgentStep]
    explanation: str        # 人类可读的执行摘要
```

#### LLM Prompt 设计

```
System: 你是风调PHM系统的操作助手。用户用中文描述需求，你生成操作步骤。

可用页面:
- /workorders: 工单管理 (创建/编辑/搜索/筛选)
  表单: title(标题), assignee(负责人-需从人员列表选),
        turbine_id(风机-需从风机列表选), priority(优先级:low/medium/high),
        description(描述), due_date(截止日期)
- /turbines/:id: 风机详情 (查看/诊断/SCADA)
- /diagnosis: 诊断工作台 (自动检测/批量检测/振动预览)
- /settings: 系统设置 (阈值/数据源/人员/个人信息)

当前页面: {current_page}
人员列表: {personnel_from_api}
风机列表: {turbines_from_api}

用户说: "{command}"

请输出:
1. intent: 意图类型 + 提取的实体
2. steps: 具体操作步骤序列
3. explanation: 一句话解释你要做什么
```

### 3.4 AgentExecutor (前端)

#### 核心类

```typescript
// frontend/src/services/agent/AgentExecutor.ts

interface ExecutorSkill {
  name: string;
  execute: (params: any) => Promise<SkillResult>;
}

class AgentExecutor {
  private skills: Map<string, ExecutorSkill>;

  constructor(private router: Router, private onProgress: ProgressCallback) {
    this.skills = new Map([
      ['navigate', this.navigateSkill],
      ['click', this.clickSkill],
      ['fill', this.fillSkill],
      ['submit', this.submitSkill],
      ['wait', this.waitSkill],
      ['confirm', this.confirmSkill],
      ['screenshot', this.screenshotSkill],
    ]);
  }

  // 执行整个计划
  async executePlan(steps: AgentStep[]): Promise<ExecutionResult> {
    for (const step of steps) {
      this.onProgress({ status: 'running', step });

      try {
        const result = await this.executeStep(step);
        this.onProgress({ status: 'done', step, result });
      } catch (error) {
        this.onProgress({ status: 'failed', step, error });
        const retry = await this.askUser(`步骤 ${step.order} 失败: ${error.message}。重试?`);
        if (!retry) throw new ExecutionAbortedError(step, error);
      }

      // 步骤间等待页面稳定
      await this.wait(500);
    }

    return { success: true, message: '所有步骤已完成' };
  }

  // --- Skills ---

  private navigateSkill: ExecutorSkill = {
    name: 'navigate',
    execute: async ({ path }: { path: string }) => {
      this.router.navigate(path);
      await this.waitForPageReady();
      const screenshot = await captureScreenshot();
      return { screenshot, message: `已切换到 ${path}` };
    }
  };

  private clickSkill: ExecutorSkill = {
    name: 'click',
    execute: async ({ selector }: { selector: string }) => {
      const el = await this.waitForElement(selector, 5000);
      if (!el) throw new Error(`未找到元素: ${selector}`);

      // 检查 confirm 属性
      const confirmMsg = el.getAttribute('data-confirm');
      if (confirmMsg) {
        const confirmed = await this.askUser(confirmMsg);
        if (!confirmed) throw new Error('用户取消了操作');
      }

      el.click();
      await this.waitForPageReady();
      const screenshot = await captureScreenshot();
      return { screenshot, message: `已点击 ${selector}` };
    }
  };

  private fillSkill: ExecutorSkill = {
    name: 'fill',
    execute: async ({ fields }: { fields: FieldDef[] }) => {
      for (const field of fields) {
        const el = document.querySelector(`[data-field="${field.name}"]`);
        if (!el) throw new Error(`未找到字段: ${field.name}`);

        if (field.source) {
          // 智能解析: "李工" → 查 API → "张工(id:2)"
          const resolved = await this.resolveEntity(field.name, field.value, field.source);
          field.value = resolved.id;
        }

        this.setFormValue(el, field.value);
      }
      return { message: `已填入 ${fields.length} 个字段` };
    }
  };

  // 智能实体解析
  private async resolveEntity(fieldName: string, value: string, source: string) {
    const response = await fetch(source);
    const data = await response.json();

    // 模糊匹配: "李工" → {id: 2, name: "李工"}
    const match = fuzzyMatch(data, value, ['name', 'username', 'title']);
    if (!match) throw new Error(`在 ${source} 中未找到 "${value}"`);

    return match;
  }

  // 等待页面渲染完成
  private async waitForPageReady(): Promise<void> {
    return new Promise(resolve => {
      const check = () => {
        if (document.readyState === 'complete') {
          // 额外等待 React 渲染
          setTimeout(resolve, 300);
        } else {
          requestAnimationFrame(check);
        }
      };
      check();
    });
  }

  // 等待元素出现
  private async waitForElement(selector: string, timeout: number): Promise<Element | null> {
    const start = Date.now();
    while (Date.now() - start < timeout) {
      const el = document.querySelector(selector);
      if (el) return el;
      await this.wait(100);
    }
    return null;
  }
}

// 辅助函数
function fuzzyMatch(items: any[], query: string, fields: string[]): any {
  const q = query.toLowerCase();
  for (const item of items) {
    for (const field of fields) {
      if (String(item[field] || '').toLowerCase().includes(q)) {
        return item;
      }
    }
  }
  return null;
}
```

### 3.5 CopilotFAB 集成

#### 入口切换

```
┌─────────────────────────────────────────────┐
│  💬 对话模式  │  🤖 Agent模式  (标签切换)     │
├─────────────────────────────────────────────┤
│                                             │
│  Agent 模式:                                │
│  ┌─────────────────────────────────────┐    │
│  │ 💬 给李工派巡检陕北3号风机的工单       │    │
│  └─────────────────────────────────────┘    │
│  建议: "查看所有风机状态" "创建本周巡检计划"    │
│                                             │
│  ── 执行进度 ──                             │
│  ✅ 步骤1: 切换到工单管理页                   │
│  ✅ 步骤2: 打开新建工单表单                    │
│  ✅ 步骤3: 填入字段 (title/assignee/turbine) │
│  ⏳ 步骤4: 提交工单...                       │
│  ┌─────────────────────────────────────┐    │
│  │         [当前页面截图]                 │    │
│  └─────────────────────────────────────┘    │
└─────────────────────────────────────────────┘
```

---

## 4. 实现路线

| 阶段 | 内容 | 产出 | 依赖 |
|------|------|------|------|
| **Phase 1: 埋点** | WorkOrderPage 加 data-* 属性 | 可操作的工单页 | 无 |
| **Phase 2: 知识库** | PageManifest 生成脚本 + WorkOrder manifest | 代码扫描工具 | Phase 1 |
| **Phase 3: 引擎** | AgentExecutor 核心类 + Skills | 浏览器内执行器 | Phase 2 |
| **Phase 4: LLM** | IntentParser + Planner 对接 Qwen | 智能链路规划 | Phase 2 |
| **Phase 5: 集成** | CopilotFAB Agent 模式 UI | 用户可用的完整功能 | Phase 3+4 |
| **Phase 6: 扩展** | 其他页面埋点 + 复杂多步任务 | 全部页面覆盖 | Phase 5 |

---

## 5. 文件清单

| 文件 | 类型 | 说明 |
|------|------|------|
| `frontend/src/services/agent/AgentExecutor.ts` | 新建 | 浏览器内执行引擎 |
| `frontend/src/services/agent/types.ts` | 新建 | AgentStep/AgentIntent 类型 |
| `frontend/src/services/agent/skills/` | 新建 | 各 Skill 实现 |
| `scripts/generate-page-manifest.ts` | 新建 | 源码扫描生成 manifest |
| `public/page-manifest.json` | 生成 | 页面能力知识库 |
| `backend/app/api/agent.py` | 新建 | Agent 解析 API |
| `frontend/src/components/AIAssistant/CopilotFAB.tsx` | 修改 | 加 Agent 模式 |
| `frontend/src/pages/WorkOrder/WorkOrderPage.tsx` | 修改 | 加 data-* 埋点 |
| 各页面组件 | 修改 | 渐进式加 data-* 埋点 |

---

## 6. 风险 & 注意事项

| 风险 | 缓解措施 |
|------|----------|
| LLM 生成的 selector 不准 | 约束 LLM 只引用 manifest 中的 selector，不自由发挥 |
| 页面加载慢导致步骤超时 | `waitForElement` 可配置超时 + 失败后自动重试 |
| 表单下拉数据变化 | Executor 执行前实时 fetch 数据源 |
| 用户中途打断 | 每个 dialog/popup 保留"取消"入口 |
| 多 tab 打开冲突 | 检测当前页面是否正确，不对则先 navigate |
