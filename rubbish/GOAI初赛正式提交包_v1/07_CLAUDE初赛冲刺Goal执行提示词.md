# CLAUDE CODE 初赛冲刺 Goal 执行提示词

将下面整段提示词复制给 Claude Code。执行前请确认它位于：

```text
G:\code\code_vscode\rjcx\feng
```

---

## 可直接复制的 Prompt

你现在是“风调预顺 WindOps ProofLoop”项目的全栈负责人、测试负责人和 GOAI 初赛交付负责人。请创建并持续执行一个 Goal，不要只给建议，不要只写计划，不要在完成一两个文件后停止。

### Goal

在 `codex/goai-wind-ops` 分支上，把一个核心 Incident 闭环提升到：

> 页面可演示、接口可验证、测试全绿、材料不夸大、他人可复现。

最终目标是完成 GOAI 无界应用—AI+工业制造初赛提交，而不是继续无边界堆功能。

### 必读文件

先完整阅读以下文件，再检查当前 Git、代码和测试。文档只是审核快照；如果代码已经变化，以当前代码和可复现测试为准，并更新文档。

```text
G:\code\code_vscode\rjcx\参加比赛要求\GOAI参赛手册全文.txt
G:\code\code_vscode\rjcx\参加比赛要求\比赛要求.txt

G:\code\code_vscode\rjcx\feng\docx\GOAI初赛正式提交包_v1\README_提交说明.md
G:\code\code_vscode\rjcx\feng\docx\GOAI初赛正式提交包_v1\01_作品简介_500字正式稿.md
G:\code\code_vscode\rjcx\feng\docx\GOAI初赛正式提交包_v1\02_方案PPT逐页正式内容稿.md
G:\code\code_vscode\rjcx\feng\docx\GOAI初赛正式提交包_v1\03_Demo视频脚本与镜头验收.md
G:\code\code_vscode\rjcx\feng\docx\GOAI初赛正式提交包_v1\04_数据合规安全与开源披露.md
G:\code\code_vscode\rjcx\feng\docx\GOAI初赛正式提交包_v1\05_当前问题复核与Claude迭代清单.md
G:\code\code_vscode\rjcx\feng\docx\GOAI初赛正式提交包_v1\06_评分映射提交计划与验收门槛.md
```

### 工作边界

1. 先执行 `git branch --show-current`、`git status --short`、`git log -10 --oneline`。
2. 必须在 `codex/goai-wind-ops` 分支。
3. 当前工作区可能有用户或其他 Agent 的未提交修改，禁止丢弃、覆盖或清理。
4. 不允许使用 `git reset --hard`、`git checkout -- .`、大范围删除或覆盖。
5. 每次只提交与当前阶段有关的文件。
6. 不修改已清洗数据，不重新做数据工程。
7. 不新增宏大模块；优先修复黄金闭环、测试、材料和复现。
8. 不得用硬编码、固定成功响应或前端动画假装算法完成。
9. 不得把模拟 OPC、多模态、联邦知识说成真实生产能力。
10. 不得把大模型输出直接用于高风险业务状态或设备控制。

### Phase 1：修复黄金路径 UI

必须先复现并修复：

1. `IncidentPage.tsx` 调查结果被 `selectIncident` 清空；
2. transition / verify 后 selected 仍是旧对象；
3. Evidence completeness 不随新证据刷新；
4. 审批、执行、恢复验证按钮不按状态机显示；
5. 后端错误被 `.catch(() => {})` 静默吞掉；
6. 页面需要清楚展示 loading、error、degraded、insufficient_data。

验收：

- 创建/选择 Incident；
- 启动调查；
- 证据刷新；
- 生成决策；
- 提交审批；
- 执行；
- 恢复验证；
- 状态和 Trace 全部即时刷新；
- 浏览器刷新后仍能从服务端恢复。

### Phase 2：统一后端闭环合同

1. 合并或废弃 `/decision-sandbox` 与 `/generate-plans` 的重复实现；
2. 业务层只保留一个 DecisionTwinService 入口；
3. 保留数据来源、算法版本、随机种子、数据质量和不可行原因；
4. 新增持久化 RecoveryCertificate 和指标表，包含证书 ID、状态、窗口、指标、算法版本、证据哈希、创建时间；
5. 恢复验证未通过或数据不足时，后端必须拒绝 resolved；
6. 正向闭环必须先满足证据、审批、执行和恢复条件。

不要为了让旧测试通过而绕开策略。

### Phase 3：测试与 Demo 环境

1. 修复 7 个 async 测试，使默认 pytest 不再失败；
2. 把真实外部模型测试标为 integration，并提供可控降级或 mock；
3. 修复 `backend/tests/e2e_test_incident_closed_loop.py` 的旧合同；
4. 修复 Playwright：
   - API 为 `http://127.0.0.1:8000/api`
   - 不能把服务器不可达当作 skip 后通过
   - 登录格式与真实 API 一致
   - 至少一个场景真正操作浏览器 UI，而不是只用 request API
5. 建立独立 Demo 数据库和 reset/seed 命令；
6. Demo 连续运行 3 次，不产生重复副作用。

每次报告：

```text
命令
passed
failed
skipped
warnings
运行时长
```

不得只报告 ship-gate 的过滤结果。

### Phase 4：安全、合规和开源

1. 修正 CARE、NREL、DTU、ERA5 的来源和许可；
2. 更新本地 dataset inventory 状态；
3. 确定代码许可证，补 `LICENSE`、`NOTICE`、`THIRD_PARTY_NOTICES.md`；
4. 区分代码、模型、数据、文档许可；
5. 不能再分发的数据只保留下载脚本、来源和校验和；
6. Demo 配置独立 Ed25519 测试密钥，密钥不入库；
7. 如果签名没有启用，UI 与文档只能写“哈希链已验证”；
8. 扫描 Key、Token、密码、邮箱、数据库和日志；
9. 默认账号必须明确只用于本地 Demo。

### Phase 5：最小产品化增量

在核心闭环稳定后，只从下面选择最能提高评审分数的两个接入 Incident 页面：

1. 携证维修任务包；
2. 合规检查；
3. What-if 分叉重演。

优先级建议：任务包 > 合规检查 > What-if。

OPC UA、多模态、联邦知识、故障基因、因果发现等暂时保留 API 或路线图，除非核心闭环已经全绿且材料完成。

### Phase 6：材料和视频

1. 以正式提交包为源稿制作 12 页 PPT/PDF；
2. 必须使用真实界面截图和测试证据；
3. 所有能力标记为“已实现 / 原型验证 / 计划接入”；
4. 删除无来源的行业金额、效率比例、固定告警数、固定审计区块数；
5. 作品简介最终仍需小于 500 字；
6. 参赛成员最多 3 人，其他人列贡献者/致谢；
7. 按 4 分钟脚本录制视频；
8. 上传前对 PDF 字体、链接权限、视频清晰度和敏感信息做回验。

### 强制验收

在 Goal 完成前，以下项目必须全部满足：

```text
[ ] git 工作区没有误伤用户文件
[ ] 默认后端测试 0 failed
[ ] 前端 production build 通过
[ ] Alembic at head
[ ] Playwright UI 黄金路径通过
[ ] 策略拒绝负例通过
[ ] 数据不足负例通过
[ ] Demo 连续 3 次通过
[ ] 主闭环不依赖外部 LLM 也能安全降级
[ ] README 从零可启动
[ ] LICENSE 与第三方清单完整
[ ] 作品简介 < 500 字
[ ] PPT、视频、README 与代码状态一致
[ ] 所有模拟能力明确标注
```

### 提交策略

每完成一个 Phase：

1. 先运行该阶段测试；
2. 检查 `git diff --check`；
3. 输出修改文件、实现证据、测试结果、剩余风险；
4. 创建一个小而清晰的 commit；
5. 更新执行台账；
6. 继续下一阶段，不要等待用户逐项催促。

如果遇到阻塞：

- 先尝试安全降级或缩小实现；
- 连续三次确认同一外部阻塞后才标记 blocked；
- 不允许用假数据、静态结果或跳过测试伪装完成。

最终交付时给出：

1. 最终 commit 列表；
2. 全量测试和 E2E 结果；
3. Demo 三次运行证据；
4. PPT/PDF/视频/作品简介路径；
5. 当前实现、原型和计划能力表；
6. 仍未关闭的风险；
7. 提交前用户只需填写的队名、成员、单位、链接和邮箱。

