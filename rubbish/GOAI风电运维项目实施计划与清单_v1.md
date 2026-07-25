# 风调预顺：现有代码问题完整清单

> 审核日期：2026-07-24  
> 审核分支：`codex/goai-wind-ops`  
> 审核范围：前端、后端、Agent、算法实现、权限安全、测试、性能、工程化与交互。  
> 明确排除：数据清洗质量、数据完整度、数据规模、数据集准备和数据导入工作。本文默认现有业务数据已经清洗完成且满足项目使用要求。  
> 当前阶段：只记录问题，不修改业务代码。后续应按编号逐项修复、测试和验收。

## 1. 审核结论

项目不是“不能运行”，而是“可以演示，但还没有达到工业应用和高分参赛作品应有的可信程度”。

已验证的工程基线：

- 前端 `npm run build` 成功，TypeScript 编译通过。
- 前端构建仍出现两个超过 500 kB 的大包警告：约 962.58 kB 和 1,034.94 kB。
- 后端排除 3 个会破坏 pytest 输出捕获的 Agent 脚本后，测试结果为：`72 passed / 9 failed / 3 errors`。
- `test_agent_chain.py`、`test_mixed_intent.py`、`test_refined_agent.py` 在模块导入阶段替换 `sys.stdout`，无法作为正常 pytest 测试运行。
- SQLAlchemy 映射检查确认 `Fault` 当前只映射 `id、turbine_id、detected_at、fault_type、confidence、status、details` 等字段；路由中使用的 `priority、processing_status、handler、closed_at` 等字段没有映射。

问题优先级：

- `P0`：可能导致越权、结果错误、状态未保存、重复执行或比赛核心流程失真，必须首先修复。
- `P1`：影响可靠性、技术深度、性能、产品体验和后续扩展。
- `P2`：维护性和规范性问题，可在 P0/P1 稳定后处理。

置信度：

- `已验证`：通过实际运行、测试输出或代码路径直接确认。
- `高`：代码证据明确，但尚未专门构造运行案例。
- `中`：属于高概率风险，需要通过专项测试最终确认。

## 2. P0：必须优先修复的问题

| 编号 | 置信度 | 问题 | 代码位置/证据 | 实际后果 | 修复方向 | 验收条件 |
|---|---|---|---|---|---|---|
| P0-01 | 已验证 | 故障处理字段没有被 SQLAlchemy 映射 | `backend/app/models/__init__.py` 的 `Fault`；`backend/app/api/diagnosis.py` 的创建、更新和状态接口 | `priority、processing_status、handler、closed_at、failed_at、status_note` 等只是临时 Python 属性，提交后不会可靠持久化；接口可能返回成功但刷新后丢失 | 把真实业务字段正式加入 `Fault` 模型和迁移；删除启动时动态补列；补持久化回读测试 | 创建/更新/关闭故障后重新建立 Session 查询，所有字段仍保持一致 |
| P0-02 | 已验证 | 用户注册可以由客户端指定角色 | `backend/app/schemas/__init__.py: UserRegister.role`；`backend/app/api/auth.py: role=data.role` | 用户可直接注册成 `admin` 或其他高权限角色 | 公共注册固定为 `viewer`；角色变更只能由管理员接口完成 | 注册请求传入 `admin` 时被拒绝或忽略，数据库角色仍为 `viewer` |
| P0-03 | 已验证 | 大多数业务写接口只有登录校验，没有服务端 RBAC | `diagnosis.py`、`workorders.py`、`knowledge.py`、`personnel.py`、`settings.py` 等路由主要只依赖 `get_current_user` | Viewer 可以绕开界面直接创建、删除、关闭故障和工单，修改人员或知识 | 建立统一权限依赖；按资源和动作定义 Viewer、Technician、Admin 权限矩阵 | 对每个写接口至少有 Viewer 拒绝、合法角色通过的测试 |
| P0-04 | 已验证 | 停用账号仍能登录和继续使用 Token | `backend/app/api/auth.py` 的 `login()`、`get_current_user()` 未检查 `is_active` | 已停用人员仍可访问系统和执行操作 | 登录和每次鉴权都检查 `is_active`；停用后立即拒绝旧 Token | 停用用户登录返回 403；旧 Token 调用业务接口同样返回 403 |
| P0-05 | 已验证 | API Key 明文保存并可能通过用户接口返回 | `User.api_key`、`AIProviderConfig.api_key`；`UserResponse.api_key`；`frontend/src/services/authStore.ts` | 密钥会进入 API 响应、浏览器状态和本地存储，泄露面过大 | 后端加密保存或改用环境/密钥服务；响应只返回 `has_api_key`；日志强制脱敏 | API、日志、浏览器存储和导出内容中均搜索不到完整 Key |
| P0-06 | 已验证 | “管理员密码解锁人员管理”只是前端状态，不是权限切换 | `SettingsPage.tsx` 的 `unlockPersonnel()` 只验证 admin 密码并 `setUnlocked(true)`；后续请求仍使用当前用户 Token | 界面制造了安全假象；普通用户可被前端解锁，服务端又没有完整 RBAC | 删除二次输入管理员密码的方式；使用当前用户角色和服务端授权，必要时做正式再认证 Token | 普通用户即使知道管理员密码也不能以自身 Token 修改人员 |
| P0-07 | 已验证 | 默认 JWT 密钥固定且生产环境不强制替换 | `backend/app/config.py: SECRET_KEY="fengdiao-phm-dev-secret-key-change-in-production"` | 若部署时忘记配置，攻击者可伪造 Token | 生产模式启动时检测默认密钥并拒绝启动；开发密钥仅限本地 | `ENV=production` 且使用默认密钥时启动失败并给出明确错误 |
| P0-08 | 已验证 | RUL 低功率判断单位错误 | `backend/app/services/prediction_service.py` 中 `if pwr < 0.10`，注释却写“低于额定功率 10%” | 0.1 kW 与额定功率 10% 完全不同，会直接扭曲退化率和 RUL | 使用风机额定功率换算阈值；统一 kW/MW；写边界测试 | 不同额定功率风机都按 `rated_power_kw × 10%` 判定 |
| P0-09 | 已验证 | 维修紧急度插值方向反了 | `backend/app/services/maintenance_planner.py` 的 `_score_rul()`、`_score_hi()` | 同一区间内可能出现 RUL 越长越紧急、HI 越高越紧急，排序违背常识 | 重写分段函数，明确区间端点和方向；加入性质测试 | 任意采样下：RUL 减少时紧急度不下降，HI 降低时紧急度不下降 |
| P0-10 | 已验证 | 排程容量没有按人数工时计算 | `backend/app/services/maintenance_scheduler.py` 只累加 `downtime_hours`，没有使用 `crew_size × downtime_hours` | 需要多人执行的任务会被低估资源，生成不可执行的日程 | 使用人员工时和实际班组容量；分别约束并行班组数、人员数、时段 | 2 人×8 小时任务占用 16 人时；超容量任务必须溢出或改期 |
| P0-11 | 高 | 工单状态可以跳转，缺少正式状态机 | `workorders.py` 只检查目标状态是否属于集合，没有校验当前状态到目标状态是否合法 | `pending` 可以直接变 `closed`；已取消工单可能被重新完成；审计链失真 | 建立显式状态转换表和领域服务，所有 API/Agent 共用 | 非法转换返回 409；合法转换记录操作者、原因和前后状态 |
| P0-12 | 已验证 | 工单“完成/关闭”没有结果验证条件 | `update_workorder()` 和 Agent 工单状态动作可直接把状态写为 `completed/closed` | 系统不能证明维修有效，核心任务闭环停在“做过”而不是“解决了” | 增加验证状态或验收记录；关闭前检查必要验证结论 | 无验收记录时不能进入 `closed`；失败验证必须进入复查/升级 |
| P0-13 | 高 | Agent 确认接口存在并发重复执行风险 | `confirm_agent_action()` 先读取 pending，再执行，未见行锁、原子状态抢占或唯一幂等约束 | 双击、重试或并发请求可能重复创建工单、重复派发或重复更新 | 数据库原子地将 `pending` 改为 `executing`；增加幂等键和唯一约束 | 同一 `request_id` 并发确认 10 次，只产生一次业务副作用 |
| P0-14 | 已验证 | 后端测试基线为红色 | 当前结果 `72 passed / 9 failed / 3 errors` | 无法判断后续修改是否引入回归，比赛现场风险不可控 | 先修测试基础设施，再判断是代码错误还是过期断言 | 主测试命令零失败、零错误，并进入每次提交检查 |
| P0-15 | 已验证 | 三个 Agent 测试文件破坏 pytest 全局输出 | `test_agent_chain.py`、`test_mixed_intent.py`、`test_refined_agent.py` 在导入时重绑 `sys.stdout` | 完整测试收集可能崩溃，测试结果不可信 | 删除模块级 stdout 修改；使用 pytest capture、日志或局部编码处理 | 执行整个 `backend/tests` 不需要 `--ignore` |
| P0-16 | 已验证 | 测试数据库 Session 与 API Session 隔离错误 | `backend/tests/conftest.py` 的内存 SQLite 使用方式导致 fixture 写入与 API 请求不在同一连接状态 | 测试创建了风机/故障，但接口返回空列表；多项测试是假失败或假通过 | 使用 `StaticPool` 或测试文件库；统一覆盖 `get_db` | fixture 写入后，API 请求能在同一测试中读取；测试间完全隔离 |

## 3. P1：重要可靠性、Agent 与工程问题

### 3.1 Agent 架构与安全

| 编号 | 置信度 | 问题 | 代码位置/证据 | 修复与验收 |
|---|---|---|---|---|
| P1-01 | 已验证 | 存在多套重叠的 Agent 入口 | `/api/agent/diagnose`、`/api/agent/execute`、`/api/ai/copilot/stream`、`/api/agent-tasks/plan`、`/api/agent-actions/*` | 确定唯一主入口；旧入口标记废弃并删除重复逻辑；前端、测试和文档只指向一套链路 |
| P1-02 | 已验证 | 旧的浏览器 Agent 执行器没有接入主流程 | `frontend/src/services/agent/AgentExecutor.ts` 和 `SkillRegistry.ts` 无实际调用；`/agent/execute` 前端也未使用 | 删除死代码或正式纳入统一编排，不能在答辩中把未接入代码描述为现有能力 |
| P1-03 | 已验证 | “多 Agent 诊断”不是当前助手主路径 | 前端主要调用 `/api/ai/copilot/stream` 和 `/api/agent-tasks/plan`，未调用 `/api/agent/diagnose` | 若保留多 Agent 卖点，必须把其接入唯一主链并展示可观测分工；否则调整宣传口径 |
| P1-04 | 高 | Agent 计划和输出缺少严格类型白名单 | `AgentAtomicStep.skill`、`intent_type`、大量 `status` 使用自由字符串和 `dict` | 使用 `Literal/Enum` 和判别联合；未知动作、参数、路径在服务端拒绝；错误输入有稳定错误码 |
| P1-05 | 高 | LLM 上下文缺少最小化和出站隐私过滤 | `AICopilotRequest.page_context/messages/screenshot` 可直接进入远端模型调用 | 建立字段白名单、敏感字段扫描、出站预览和用户确认；记录模型、目的和发送字段，不记录秘密 |
| P1-06 | 已验证 | AI 请求体缺少整体大小限制 | `AICopilotRequest.messages/page_context/screenshot` 没有数量和大小上限 | 限制消息数、单条长度、上下文深度、截图字节数和总 Token 预算；超限返回 413/422 |
| P1-07 | 高 | 缺少 Prompt Injection 隔离 | 页面上下文、知识内容和用户消息共同进入 Prompt，未形成“数据不可执行指令”的结构化边界 | 给外部内容加不可执行标记；工具调用只接受已注册 Playbook；加入恶意知识和恶意页面文本测试 |
| P1-08 | 已验证 | 不同模块的振动阈值口径冲突 | `health_index.py` 使用 2/4；`agents/data_agent.py` Prompt 使用 12，且单位描述也不一致 | 建立唯一指标/单位注册表，算法、Prompt、UI、文档全部引用同一来源 |
| P1-09 | 高 | Agent Trace 只有局部耗时，不是可复盘链路 | 当前主要返回 `orchestrator_ms` 等简单字段 | 每次任务生成 `trace_id`；记录计划、检索、工具、审批、结果和错误；敏感值脱敏；支持回放 |
| P1-10 | 高 | 远端模型调用没有用户级限流、预算和熔断 | 登录后可反复调用总结、截图、多 Agent 和流式接口 | 增加用户/接口速率限制、并发限制、Token/费用预算、超时、重试上限和熔断状态 |
| P1-11 | 中 | 知识自动沉淀可能把错误输出写回知识库 | `knowledge_extractor.py` 在对话后后台提取，依赖模型判断 | 所有 AI 生成知识默认为 `pending_review`；显示来源和证据；禁止自动覆盖已验证知识 |

### 3.2 API、状态与安全

| 编号 | 置信度 | 问题 | 代码位置/证据 | 修复与验收 |
|---|---|---|---|---|
| P1-12 | 已验证 | 全局异常响应仍返回内部异常文本 | `backend/app/main.py` 返回 `message: str(exc)`；部分路由直接 `detail=str(exc)` | 对外只返回错误码和安全消息；详细堆栈仅进入脱敏日志 |
| P1-13 | 已验证 | 没有登录防爆破和接口限流 | 登录、AI、诊断和上传接口均未见 rate limit | 登录按账号/IP 限流并短期锁定；高成本接口单独配置额度 |
| P1-14 | 已验证 | Token 存在 localStorage，缺少刷新和撤销机制 | `frontend/src/services/authStore.ts`、`api.ts` | 比赛版本至少缩短生命周期并支持服务端失效；正式部署优先 HttpOnly Cookie + CSRF 防护 |
| P1-15 | 已验证 | 图片上传只检查扩展名，不限制大小、MIME、像素和文件生命周期 | `diagnosis.py: /blade-diagnosis/upload` | 验证 MIME 和文件签名；流式限制大小；限制像素；推理后按策略删除；异常文件有测试 |
| P1-16 | 已验证 | Pydantic Validator 被同名覆盖 | `schemas/__init__.py` 中 `validate_email_address` 定义两次；测试产生明确警告 | 合并验证器；清除所有 Pydantic 警告 |
| P1-17 | 高 | 多个 Schema 使用可变默认值 | `schemas/__init__.py` 中多处 `=[]`、`={}` | 全部改为 `Field(default_factory=list/dict)`；添加实例隔离测试 |
| P1-18 | 已验证 | 状态枚举分散且定义不一致 | Fault 活跃状态在 `knowledge.py`、`agent_data_tools.py`、`agent_workflows` 等处分别定义；工单状态也有多套集合 | 建立领域 Enum 和唯一状态机；API、Agent、UI 和统计共用 |
| P1-19 | 高 | 更新接口没有乐观锁，可能覆盖他人修改 | 工单和故障更新没有 `version` 或 `updated_at` 条件 | 加版本号/ETag；冲突返回 409；两人同时编辑不得静默覆盖 |
| P1-20 | 已验证 | API 契约和测试已经漂移 | 测试出现 `/diagnosis/vibration` 404、成本接口预期 404 实际 422、AI Provider 返回契约不一致 | 先确定正确契约，再同步 OpenAPI、前端类型和测试；禁止只改测试迎合错误实现 |
| P1-21 | 高 | 自称支持 PostgreSQL，但核心聚合包含 SQLite 专用 SQL | `turbines.py` 使用 `strftime` 等 SQLite 语法；启动迁移逻辑又维护两套 SQL | 要么明确比赛版本只支持 SQLite，要么用 SQLAlchemy/数据库适配层消除方言耦合，并在 PostgreSQL CI 验证 |
| P1-22 | 已验证 | 没有正式迁移系统 | `main.py` 启动时执行大量 `ALTER TABLE`；requirements 中 Alembic 被注释 | 引入 Alembic；每次模型变化有向前迁移；新库和旧库都通过升级测试 |

### 3.3 算法与业务逻辑

| 编号 | 置信度 | 问题 | 代码位置/证据 | 修复与验收 |
|---|---|---|---|---|
| P1-23 | 已验证 | HI 缺少输入时默认给较高健康分 | `health_index.py` 无输入时给 80–90 分 | 缺失应显示 `unknown` 和置信度，不应伪装成健康；只对可用维度重新归一或直接拒绝计算 |
| P1-24 | 已验证 | HI 趋势不是时间序列趋势 | `_trend_score()` 用 `(100-current_hi)/距维修天数` 推断退化 | 用历史 HI/指标时间序列拟合；没有历史时标记不可计算 |
| P1-25 | 高 | 振动单位和行业阈值含义不清 | `health_index.py` 写 `mm/s²`，阈值数值更像速度类阈值；其他模块口径不同 | 明确 RMS 是速度还是加速度；单位、采样处理和阈值来源统一 |
| P1-26 | 已验证 | RUL 为每台风机加载全部时间戳 | `_estimate_linear_degradation()` 查询所有 timestamp 后在 Python 中取首尾 | 数据库直接查询 `MIN/MAX/COUNT`；窗口聚合在数据库完成 |
| P1-27 | 已验证 | RUL 窗口抽样没有排序 | 每个窗口 `.limit(30)` 前没有 `order_by` | 明确按时间或均匀采样；同一输入多次执行结果必须一致 |
| P1-28 | 已验证 | RUL 置信区间是启发式宽度，不是校准结果 | `spread_pct` 由固定公式构造 | UI 改称“估计区间”或通过回测校准；报告覆盖率和 MAE |
| P1-29 | 高 | 季节天气回退看起来像预测结果 | `_seasonal_fallback()` 用日期计算确定性变化，返回 `source=seasonal_model` | UI 明确标注“规则估计/非预报”，不得与真实天气窗口混用 |
| P1-30 | 已验证 | Dashboard 聚合缓存没有把查询条件作为 Key | `turbines.py` 的 `_agg_cache` 只有一份 `data/ts` | 缓存键包含所有过滤条件；增加跨条件串扰测试 |
| P1-31 | 高 | 缓存是进程内全局变量，多 Worker 结果不一致 | `_agg_cache`、Pipeline State 等模块级状态 | 单机 Demo 可保留但必须明确；正式实现改为带版本的共享缓存或不缓存 |
| P1-32 | 高 | 维修成本和优先级中的固定经验参数没有版本信息 | `maintenance_planner.py` 存在默认基价、倍数和阈值 | 参数集中配置，记录版本和来源；每次推荐返回使用的规则版本 |
| P1-33 | 高 | 关闭故障、关闭工单、更新时间等逻辑分散 | `diagnosis.py`、`workorders.py`、`agent_actions/workorder.py` 都在操作状态 | 提取领域服务，HTTP API 和 Agent 只能调用领域服务，防止规则不一致 |

### 3.4 前端、交互与性能

| 编号 | 置信度 | 问题 | 代码位置/证据 | 修复与验收 |
|---|---|---|---|---|
| P1-34 | 已验证 | 前端没有测试和 Lint 命令 | `frontend/package.json` 只有 dev/build/preview | 增加 ESLint、Vitest、React Testing Library 和一条主链 Playwright E2E |
| P1-35 | 已验证 | 页面和组件过大 | `SettingsPage.tsx` 2014 行、`DiagnosisPage.tsx` 1930 行、`CopilotFAB.tsx` 1691 行等 | 按业务区域、状态 Hook、API Service 拆分；单文件不再继续增长 |
| P1-36 | 已验证 | 构建产物存在超大 Chunk | `DroneSchedulerPage` 约 962.58 kB；共享包约 1,034.94 kB | Three.js、地图、ECharts、截图工具单独分包；设置性能预算 |
| P1-37 | 已验证 | 表单缺少明确可访问名称 | 工单、知识库、人员管理等大量表单仅依赖 placeholder | 所有输入使用关联 `label` 或 `aria-label`；错误信息关联到字段 |
| P1-38 | 已验证 | 部分交互只有鼠标点击 | `MaintenanceCalendar.tsx` 用可点击 `div`；多个遮罩层依赖 `onClick` | 使用 `button/dialog` 语义；支持 Enter/Space/Escape；设置焦点圈 |
| P1-39 | 已验证 | 弹窗和抽屉缺少完整焦点管理 | `WorkOrderPage.tsx` 多个自制遮罩/抽屉 | 打开后焦点进入，Tab 不逃逸，Esc 关闭，关闭后焦点返回触发按钮 |
| P1-40 | 已验证 | 图片缺少替代文本 | `frontend/src/components/Map/DroneMap.tsx` 的 `<img>` 无 `alt` | 装饰图片用空 alt；有含义的图片给出准确说明 |
| P1-41 | 高 | 流式 AI 请求绕开统一 Axios 错误处理 | `CopilotFAB.tsx` 直接 `fetch('/api/ai/copilot/stream')` | 建立统一鉴权、超时、取消、401 和错误解析封装 |
| P1-42 | 中 | 缺少统一“事故/任务”产品状态 | 页面分别围绕诊断、预测、工单和知识组织 | 增加统一 Incident ID 和跨页面状态；避免同一事件在多页变成互不关联的记录 |
| P1-43 | 中 | 部分初始化请求失败后缺少完整错误状态 | Settings 等页面并行调用多个加载函数，部分只清空列表或静默失败 | 每个关键区域提供 loading/empty/error/retry；不能把失败显示成“没有内容” |

### 3.5 可维护性、复现与开放工程

| 编号 | 置信度 | 问题 | 代码位置/证据 | 修复与验收 |
|---|---|---|---|---|
| P1-44 | 已验证 | Agent 写动作文件达到 6147 行、约 160 个函数 | `backend/app/services/agent_actions/workorder.py` | 按工单、故障、人员、设置、知识、预测动作域拆分；共享确认框架独立 |
| P1-45 | 已验证 | Schema 和 Model 集中在单个大文件 | `schemas/__init__.py` 716 行；`models/__init__.py` 330 行 | 按领域拆分并保留稳定导出，降低冲突和误覆盖 |
| P1-46 | 高 | 业务函数大量使用无结构 `dict` | Agent、算法、API 返回值中普遍存在 | 核心领域对象改用 Pydantic/dataclass；内部和外部契约分别建模 |
| P1-47 | 已验证 | 没有 CI 配置 | 仓库未发现持续集成工作流 | 每次提交运行后端测试、前端类型检查、Lint、构建和密钥扫描 |
| P1-48 | 已验证 | 没有正式容器化和健康依赖检查 | 未发现 Dockerfile/Compose；当前依赖本机环境和启动脚本 | 提供可选 Docker Compose 或明确的一键本机启动；健康检查包含 DB、模型和外部服务状态 |
| P1-49 | 已验证 | 缺少正式 LICENSE | 仓库未发现 LICENSE | 选择与第三方依赖兼容的开源许可证，并在 README 明确可复用范围 |
| P1-50 | 高 | 日志结构不统一，缺少关联 ID | 同时使用基础 logging、部分临时状态和简化 Trace | 统一结构化日志；HTTP、Agent、工单和故障共享 `trace_id/incident_id/user_id` |
| P1-51 | 高 | 列表接口普遍缺少稳定分页和排序契约 | 风机、故障等接口直接 `.all()` 或固定 limit | 明确 `page/page_size/sort`；排序字段白名单；响应包含 total 和 next |
| P1-52 | 中 | 邮件发送在请求内逐个串行执行 | `workorders.py` 循环 `await send_email()` | 小规模 Demo 可接受；正式版本应进入可靠任务队列，具有重试和幂等 |

## 4. P2：规范性问题

| 编号 | 问题 | 处理建议 |
|---|---|---|
| P2-01 | `config.py` 重复定义 PostgreSQL 连接池配置 | 删除重复字段，避免维护者误判 |
| P2-02 | Pydantic 仍使用旧式 `class Config` | 迁移为 `ConfigDict`，清除弃用警告 |
| P2-03 | 中英文错误信息和状态名称混用 | 建立错误码；前端负责本地化文案 |
| P2-04 | 大量魔法数字散落在算法、Prompt 和 UI | 建立版本化指标注册表与配置快照 |
| P2-05 | README 项目身份仍偏课程项目 | 修改为参赛项目定位、能力边界、运行说明和安全声明 |
| P2-06 | 未见架构决策记录 | 对 Agent 主入口、OPC 接入、权限模型、算法口径等建立 ADR |
| P2-07 | 缺少前后端契约自动生成 | 由 OpenAPI 生成 TypeScript 类型，减少 API 漂移 |
| P2-08 | 根路由没有明确的前端 404 页面 | 增加 NotFound 页面和返回入口 |

## 5. 建议逐项修复顺序

不要同时大改 UI、Agent 和算法。建议严格按照以下顺序：

### 第一批：先消除“接口成功但结果不可信”

1. `P0-01` Fault 模型字段映射和迁移。
2. `P0-14`、`P0-15`、`P0-16` 测试基础设施。
3. `P0-08`、`P0-09`、`P0-10` 算法确定性错误。
4. `P0-11`、`P0-12` 状态机和关闭条件。

退出条件：核心测试全绿；故障/工单刷新后状态不丢；算法性质测试通过。

### 第二批：建立真正的安全边界

1. `P0-02`、`P0-03`、`P0-04` 角色和账号状态。
2. `P0-05`、`P0-06` 密钥与伪解锁问题。
3. `P0-07`、`P1-12`、`P1-13`、`P1-14`、`P1-15`。
4. `P0-13` Agent 幂等和并发确认。

退出条件：越权测试、密钥扫描、重复确认和异常上传测试全部通过。

### 第三批：统一 Agent 主链

1. `P1-01`、`P1-02`、`P1-03` 选择唯一 Agent 入口。
2. `P1-04` 至 `P1-11` 完成契约、隐私、注入防护、Trace 和限额。
3. `P1-18`、`P1-33` 统一状态与领域服务。

退出条件：前端只调用一套 Agent 链路；每个步骤可观测；所有写动作经过服务端策略和幂等控制。

### 第四批：前端和工程完成度

1. `P1-34` 建立前端测试和 Lint。
2. `P1-35`、`P1-44`、`P1-45` 拆分巨型模块。
3. `P1-36` 至 `P1-43` 优化性能、可访问性和事故视角。
4. `P1-47` 至 `P1-52` 补 CI、复现、日志和开放工程。

退出条件：主链 E2E 稳定；构建无超预算 Chunk；全新环境可按文档启动；CI 全绿。

## 6. 每修一个问题时的统一记录模板

```markdown
### 修复编号：P0-XX

- 问题：
- 根因：
- 修改文件：
- 修改方案：
- 是否改变 API：
- 是否需要迁移：
- 新增测试：
- 测试结果：
- 回归影响：
- 截图/Trace：
- 完成日期：
- 审核结论：通过 / 退回
```

后续修复时，应一次选择 1–3 个存在依赖关系的问题，不要一次提交几十项混合修改。
