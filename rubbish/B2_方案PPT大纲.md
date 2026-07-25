# 风调预顺 WindOps ProofLoop — 方案PPT大纲 (B2)

## Slide 1: 封面
- 标题: 风调预顺 WindOps ProofLoop — 面向风电运维的可验证闭环工业Agent
- 副标题: GOAI Boundless Agents — AI+工业制造赛道
- 一句话: 不只是预测故障，而是证明每个判断、每次决策、每次修复

## Slide 2: 场景与痛点
- 30+台风机的风电场，每天数十条告警
- 痛点1: 告警风暴 — 运维人员被淹没
- 痛点2: 决策困难 — 人员/备件/天气约束下的最优方案
- 痛点3: 闭环缺失 — 修完无法验证效果
- 痛点4: 知识流失 — 每次事故经验无法复用
- 数据: 某风场年均非计划停机损失 ¥200万+

## Slide 3: 产品方案 — 8步闭环
```
异常进入 → 告警压缩 → Agent调查 → 证据契约
→ 决策孪生 → 策略审批 → 维修执行 → 恢复验证 → 知识沉淀
```
- 每个步骤: 可解释 + 可追溯 + 可验证
- 核心创新: Proof-Carrying Maintenance (携带证明的维修)

## Slide 4: 4大核心创新
1. **自主调查编排器**: 10步可恢复工作流，LLM降级→规则引擎
2. **证据契约系统**: 8类型化证据，缺证据不能确诊
3. **资源约束决策孪生**: MCDM+蒙特卡洛，无固定模板
4. **策略强制执行网关**: 直接调用API也无法绕过

## Slide 5: 技术架构
- 后端: FastAPI + SQLAlchemy 2.0 (async) + Alembic
- 前端: React 18 + TypeScript + Tailwind CSS
- 算法: 加权图聚类/MCDM/Beta-Bernoulli/Gower距离/Granger检验
- 工业: OPC UA数字影子 (8风机模拟服务器)
- 安全: SHA-256审计链 + Ed25519签名 + RBAC

## Slide 6: Demo演示路径 (5分钟)
1. OPC触发振动异常 → 27条告警涌入
2. 告警压缩为1个Incident → 经济数字开始跳动
3. Agent自动调查10步 → 证据图自动生成
4. 决策孪生3方案对比 → 推荐降载36小时
5. 用户尝试直接关闭 → 策略引擎拒绝
6. 审批→执行→恢复验证→签发恢复证明
7. 审计链34区块全绿 → 验证通过
8. 分叉重演: "如果选了立即停机..."

## Slide 7: 安全与合规
- 10条合规规则 (Blocker/Critical/Warning/Info)
- 红队测试8场景 (传感器离线/LLM超时/告警风暴...)
- 禁止直接控制物理设备 (REG-003/REG-008)
- AI建议仅辅助参考 (REG-005)
- 审计链可检测篡改 (不是区块链)

## Slide 8: 开放与复用
- 开放PHM API规范 (OpenAPI 3.0)
- Python SDK模板
- 3行业适配模板 (光伏/水泵/压缩机)
- 联邦知识共享 (3风场，不交换原始SCADA)
- 差分隐私 (Laplace/Gaussian机制)

## Slide 9: 数据来源与合规
- CARE Dataset (NREL, CC BY 4.0)
- ERA5气象 + Open-Meteo天气
- YOLO自训练叶片检测
- 模拟数据明确标注 `simulated`
- 无PII，无真实风场运营数据
- 商业API使用披露 (通义千问)

## Slide 10: 团队与致谢
- 技术栈: Python/FastAPI/React/TypeScript/SQLite
- 开源许可证: Apache 2.0
- 10次提交，20+服务模块，129测试
- 感谢GOAI组委会
