# 风调预顺 WindOps ProofLoop｜当前问题复核与 Claude 迭代清单

> 审核快照：`4673d1b`，2026-07-24  
> 范围：比赛符合度、主闭环、前端、后端、测试、可复现性、材料真实性  
> 原则：本清单只列问题和验收，不在本轮修改业务代码。

## 1. 结论

项目已经从“PHM 大屏 + AI 助手”进化为有明确 Incident 主线的工业 Agent 原型，核心创意和工程量足以支撑初赛；但当前最大风险不是“功能少”，而是：

1. 主闭环页面存在会影响现场演示的状态刷新 Bug；
2. 文档对部分模拟能力、测试状态和开源状态表述过度；
3. 浏览器 E2E 配置错误，尚不能证明真实页面闭环稳定；
4. 后端存在新旧两套决策/策略路径，算法口径可能分裂；
5. 很多创新只有 API，没有产品入口，评委看不到；
6. 数据许可和参赛团队信息存在提交级冲突。

当前建议自评约 **77/100**；完成 P0 后具备进入 **88–91/100 竞争区间**的条件，但最终成绩取决于 Demo 稳定性、真实验证证据和现场表达。

## 2. P0：提交前必须修复

### P0-01｜自主调查结果会被立即清空

- **位置**：`frontend/src/pages/Incident/IncidentPage.tsx:110-115`
- **证据**：`startInvestigation(...).then(setInvestigation).then(() => selectIncident(selected))`；而 `selectIncident` 在第 85 行执行 `setInvestigation(null)`。
- **影响**：点击“自主调查”后结果可能瞬间消失，核心 Demo 断裂。
- **修复要求**：调查完成后以接口返回更新 `investigation`，单独刷新事件、证据和 Trace，不得调用会清空详情状态的初始化函数。
- **验收**：连续 3 次点击后调查面板保持展示；刷新页面后能从服务端恢复工作流摘要。

### P0-02｜事件状态和验证状态使用旧对象，页面不刷新

- **位置**：`IncidentPage.tsx:123-135`
- **证据**：恢复验证或状态转换后调用 `selectIncident(selected)`，但没有 `fetchIncident`，也没有使用 transition 返回的新 Incident 更新 `selected`。
- **影响**：后端已经进入新阶段，页面头部仍显示旧阶段；评委会误以为闭环失败。
- **修复要求**：所有写操作后使用返回对象或 `fetchIncident(id)` 原子刷新 selected，并刷新相应 Tab 数据。
- **验收**：状态转换后 1 秒内更新；浏览器刷新前后状态一致。

### P0-03｜证据完整度在同一 Incident 内不会自动刷新

- **位置**：`IncidentPage.tsx:328-332`
- **证据**：完整度只依赖 `incidentId`，调查新增 Evidence 后 ID 不变，Effect 不再执行。
- **影响**：调查完成后仍显示旧完整度。
- **修复要求**：引入刷新版本或统一 query cache；调查完成、新增证据、恢复验证后重新请求。
- **验收**：新增 Evidence 后完整度与缺失清单实时变化。

### P0-04｜浏览器 E2E 端口和 API 前缀错误

- **位置**：`frontend/e2e/incident-closed-loop.spec.ts`
- **证据**：测试使用 `http://localhost:8080/auth/login` 和 `/incidents`；当前启动器运行 `127.0.0.1:8000`，后端路由前缀为 `/api`。
- **影响**：所谓 Playwright E2E 无法验证真实系统。
- **修复要求**：统一 `E2E_API_BASE=http://127.0.0.1:8000/api`；从环境变量读取；登录请求格式与真实 API 一致。
- **验收**：三场景在干净 Demo 数据库上全部通过，CI 不允许“服务器不可达就 skip”。

### P0-05｜全量测试仍有 7 个失败，ship-gate 通过口径有遮蔽

- **位置**：
  - `backend/tests/test_agent_chain.py`
  - `backend/tests/test_mixed_intent.py`
  - `backend/tests/test_refined_agent.py`
  - `backend/tests/test_ship_gate.py`
- **真实结果**：`129 passed, 7 failed, 3 skipped, 15 warnings`。
- **原因**：7 个 async 函数缺少正确的 pytest-asyncio 标记/fixture 规范；ship-gate 直接忽略三个文件后报告 129 通过。
- **影响**：README 和 PPT 如果写“全量 129 通过、0 失败”会失实。
- **修复要求**：把脚本式测试改成正式 pytest；外部模型测试应标记 integration 并提供可控 mock/fallback；ship-gate 分开报告 unit/integration/e2e。
- **验收**：默认测试 0 failed；被跳过项目有明确原因和数量。

### P0-06｜旧闭环 E2E 与新安全策略冲突

- **位置**：`backend/tests/e2e_test_incident_closed_loop.py:176`
- **证据**：测试没有生成有效恢复证明就期望 resolved=200；当前服务器正确返回 403。
- **影响**：测试合同落后于产品安全规则。
- **修复要求**：重写黄金路径，先验证恢复并满足关闭条件；保留一个负例验证 403。
- **验收**：正向闭环和策略拒绝两个场景均通过。

### P0-07｜Demo 脚本宣称 UI 尚未提供的能力

- **涉及**：OPC 触发、告警压缩动态图、任务包、分叉重演、合规、红队、多模态。
- **证据**：Incident 页面当前只有总览、证据、决策、经济、审计、追溯六个 Tab；其他接口虽存在，但没有稳定演示入口。
- **影响**：视频脚本无法照稿录制。
- **修复要求**：初赛只展示主闭环；复赛再接任务包/合规/what-if。若初赛必须展示，用 Swagger 真实调用并明确“接口原型”。
- **验收**：视频每个镜头都能在当前版本稳定完成。

### P0-08｜数据许可说明存在事实错误

- **位置**：`docx/B4_数据来源与合规说明.md`
- **问题**：
  - CARE to Compare 不是 NREL 数据，来源是 Fraunhofer IEE / Zenodo；
  - CARE 许可为 CC BY-SA 4.0，不是 CC BY 4.0；
  - DTU 数据为 CC BY-NC 3.0，不应只写“学术使用”；
  - 本地 inventory 状态与实际提取文件不一致。
- **影响**：命中赛事数据和 License 红线。
- **修复要求**：以 `real_dataset_sources.json` 为主，逐项对齐 DOI、许可、再分发限制和本地状态。
- **验收**：代码、README、PPT、合规文档四处一致。

### P0-09｜开源许可证口径冲突

- **证据**：
  - 根目录没有 `LICENSE`；
  - README 写“仅供学习和研究使用”；
  - 初版 B2 写“Apache 2.0”。
- **影响**：开放复用 5% 直接失分，并产生第三方许可风险。
- **修复要求**：确定代码许可证；增加 LICENSE/NOTICE/第三方清单；数据单独披露。
- **验收**：仓库可明确回答“哪些可开源、采用什么许可、哪些数据不可再分发”。

### P0-10｜团队人数与赛事规则冲突

- **证据**：赛事手册规定团队不超过 3 人；README 团队表超过 3 人。
- **影响**：报名有效性风险。
- **修复要求**：确认正式参赛成员最多 3 人；其他贡献者放致谢，不放参赛成员栏。
- **验收**：报名表、PPT、README 的参赛成员一致。

### P0-11｜初版材料包含无来源数字和互相冲突的数量

- **位置**：`docx/B2_方案PPT大纲.md`、`docx/B3_Demo视频脚本_5分钟.md`
- **示例**：
  - “某风场年均非计划停机损失 ¥200 万+”无来源；
  - 一处写 3 个方案，一处写 4 个方案；
  - 固定写 27 条告警、34 个审计区块、75% 完整度；
  - 写“129 测试”但未说明忽略项。
- **修复要求**：固定数字改为“样例响应值”或录制时动态口播；价值改为计算公式。
- **验收**：每个数字能回答来源、时间、样本和计算方式。

### P0-12｜审计签名当前没有配置

- **位置**：`audit_chain_service.py:78-108`
- **证据**：当前 `.env` 与 `backend/.env` 均未配置 `AUDIT_SIGNING_KEY` 或路径。
- **影响**：当前只能证明 SHA-256 链，不能证明 Ed25519 根签名已生效。
- **修复要求**：Demo 环境生成独立测试签名密钥并记录公钥；或者材料只讲“支持签名，当前未启用”。
- **验收**：API 返回 `signed=true` 且验证通过，或 PPT 删除“已签名”表述。

## 3. P1：建议初赛前完成

### P1-01｜新旧两套决策 API 并存

- **位置**：`incidents.py` 的 `/decision-sandbox` 与 `/generate-plans`
- **问题**：旧接口使用固定三方案和硬编码可用性；新接口使用 `DecisionTwinService` 生成四方案。
- **风险**：不同页面或测试得到不同口径。
- **建议**：废弃旧接口或让它委托新服务；只保留一个 Decision Contract。

### P1-02｜新决策孪生仍含明显占位与假设

- **位置**：`decision_twin_service.py`
- **事实**：
  - 天气窗口来源为 `placeholder`；
  - 备件来自知识库且状态为 `unknown`，不是库存；
  - 有历史工单时直接假设成功率 80%；
  - 经济归一化使用固定 500,000 元；
  - 天气缺失时仍假设可行。
- **建议**：至少把这些值外部配置化并在 UI 显示来源；真实库存/天气未接入前禁止写“已锁定备件/已确认天气窗口”。

### P1-03｜恢复证明没有独立持久化模型

- **证据**：`RecoveryVerificationService.verify()` 返回内存对象，Incident 只保存 `verification_status`。
- **风险**：证书 ID、指标、算法版本和证据哈希无法稳定历史查询。
- **建议**：新增 RecoveryCertificate / RecoveryMetric 表和迁移；证书不可被后续请求无痕覆盖。

### P1-04｜多模态会诊仍返回模拟缺陷

- **位置**：`multimodal_service.py:103-160`
- **证据**：模糊度、曝光、角度和 YOLO 缺陷结果为固定模拟值。
- **建议**：接入已有 `blade_yolo_service`；输出模型版本、图片哈希、推理时间和阈值；否则只标“交互原型”。

### P1-05｜OPC UA 不是实际协议服务器

- **位置**：`opc_ua_shadow_service.py`
- **事实**：当前为内存地址空间和随机 tick；文档也明确 `NOT production OPC UA`。
- **建议**：初赛称“OPC UA 数字影子原型”；复赛用 asyncua 建最小可运行服务器、订阅、断线重连和证书配置示例。

### P1-06｜联邦知识共享是内存模拟

- **位置**：`federated_knowledge_service.py`
- **事实**：三风场、回测和协调中心都在进程内模拟。
- **建议**：从主 PPT 核心创新移到路线图；若继续做，至少拆成三个进程并验证不交换原始数据。

### P1-07｜Incident API 文件过大且职责混杂

- **位置**：`backend/app/api/incidents.py`，约 2,000 行
- **问题**：Incident CRUD、旧算法、策略、审计、what-if、联邦、多模态全在一个路由文件。
- **建议**：按 incident-core / investigation / decision / assurance / extension 拆路由；服务层保持唯一入口。

### P1-08｜前端存在未使用状态和接口

- **位置**：`IncidentPage.tsx`
- **示例**：`cluster`、`policy`、`compressAlarms`、`checkPolicy`、`getWhatIfAnalysis`、`getTaskPackage`、`getComplianceCheck` 等未形成 UI 流程。
- **建议**：删除死代码或接成明确 Tab；TypeScript 开启 `noUnusedLocals`。

### P1-09｜审批与执行按钮没有状态导引

- **位置**：`IncidentPage.tsx:420-428`
- **问题**：页面同时提供“提交审批”和“开始执行”，用户可以从错误阶段点击执行，靠后端报错。
- **建议**：用状态机驱动按钮可见性，并展示“为什么当前不可执行”，而不是只隐藏。

### P1-10｜错误被静默吞掉

- **位置**：经济影响、Evidence、Trace 等多处 `.catch(() => {})`
- **风险**：后端失败时页面空白，现场演示难定位。
- **建议**：统一 Error State、Retry、降级标记和 Trace ID。

### P1-11｜可复现依赖未完全进入 requirements

- **问题**：
  - Alembic 已被 ship-gate 使用，但 requirements 中仍被注释；
  - asyncua、签名相关依赖和浏览器依赖需要明确 optional group；
  - README 启动脚本与当前实际文件不一致。
- **建议**：建立 `requirements-core.txt`、`requirements-ml.txt`、`requirements-industrial.txt` 或统一 pyproject lock。

### P1-12｜README 大量状态已过期

- **示例**：
  - 顶部写 129 tests passing，未说明忽略项；
  - 许可证为 Educational，与 PPT 冲突；
  - 启动脚本仍引用已删除的 `start.ps1`；
  - 服务、API 和页面数量已变化；
  - “为陕西省风场提供”容易被理解为真实生产部署。
- **建议**：以提交包状态表重写 README。

## 4. P2：复赛前完善

### P2-01｜前端大文件

- Settings 约 2,014 行；
- Diagnosis 约 1,930 行；
- CopilotFAB 约 1,691 行；
- Knowledge 约 1,391 行；
- TurbineDetail 约 1,334 行。

建议按领域组件和 hooks 拆分，增加 Storybook 或组件测试。

### P2-02｜生产构建包过大

当前构建告警：

- ECharts 约 1,035 kB；
- 无人机调度约 709 kB；
- Three.js vendor 约 688 kB。

建议按页面动态导入 ECharts 图表、拆无人机工具、压缩 3D 资源，并用 performance budget 阻止回归。

### P2-03｜A11y 测试不足

当前测试只判断页面有内容和按钮文字，未使用 axe，也未完成登录进入目标页面；即使被重定向到登录页，也可能通过。

建议引入 `@axe-core/playwright`，验证主 landmark、键盘焦点、对比度、ARIA 和表单错误。

### P2-04｜Demo 数据可重置能力

Demo runner 会创建 Incident，但没有明确的独立数据库重置和种子流程。

建议提供：

```text
make demo-reset
make demo-start
make demo-check
```

确保连续 3 次运行结果可预测且不会污染开发数据。

### P2-05｜指标和消融实验

建议形成最小评测集：

- 告警相关性：pairwise precision / recall、压缩率；
- Evidence Contract：缺失证据识别准确率、冲突检出率；
- 决策孪生：硬约束违规率、推荐稳定性；
- 策略网关：危险动作拦截率、误拦截率；
- 恢复验证：恢复判定一致率；
- Agent：任务成功率、工具调用正确率、降级成功率；
- 产品：VICR、平均调查时长、人工接管率。

## 5. Claude Code 建议执行顺序

```text
Goal:
让 WindOps ProofLoop 的一个核心 Incident 闭环达到
“页面可演示、接口可验证、测试全绿、材料不夸大”的初赛提交标准。

Phase 1 — 修复黄金路径 UI
P0-01 / P0-02 / P0-03 / P0-09

Phase 2 — 统一后端合同
P0-06 / P1-01 / P1-03

Phase 3 — 修复测试与 Demo 环境
P0-04 / P0-05 / P2-04

Phase 4 — 事实与合规对齐
P0-08 / P0-09 / P0-10 / P0-11 / P0-12 / P1-12

Phase 5 — 只接最值钱的前端能力
任务包 + 合规检查 + What-if 三选二；
其余能力保留 API 和路线图。
```

### 每阶段共同 Definition of Done

1. 先读当前代码和测试，禁止重写无关模块；
2. 每项修改给出问题证据、实现说明和测试；
3. 不以硬编码通过测试；
4. 不把模拟值包装成真实值；
5. 后端权限和策略不可只靠前端按钮；
6. 更新 README 和提交材料中的状态；
7. `git diff` 不包含用户未授权文件；
8. 输出测试命令、通过数、失败数、跳过数和警告数；
9. 浏览器 E2E 必须真正访问目标页面和 `/api`；
10. 主闭环连续执行 3 次通过后再进入下一阶段。

