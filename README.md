<p align="center">
  <img src="docs/assets/windops-logo.png" alt="风调预顺 WindOps ProofLoop logo" width="112" />
</p>

# 🌪️ 风调预顺 WindOps ProofLoop

> **可验证闭环工业 Agent 平台** — 不只是预测哪里可能坏，而是把一次设备异常自动组织成**可解释、可审批、可执行、可验证、可复盘**的运维事件。

<br/>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11-3776AB?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/FastAPI-0.115-009688?style=for-the-badge&logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/React-18-61DAFB?style=for-the-badge&logo=react&logoColor=black" />
  <img src="https://img.shields.io/badge/TypeScript-5.6-3178C6?style=for-the-badge&logo=typescript&logoColor=white" />
  <img src="https://img.shields.io/badge/Three.js-0.170-000000?style=for-the-badge&logo=threedotjs&logoColor=white" />
  <img src="https://img.shields.io/badge/ECharts-5.5-AA344D?style=for-the-badge&logo=apacheecharts&logoColor=white" />
  <img src="https://img.shields.io/badge/Tailwind-3.4-06B6D4?style=for-the-badge&logo=tailwindcss&logoColor=white" />
  <img src="https://img.shields.io/badge/Qwen--Plus-FF6A00?style=for-the-badge&logo=alibabacloud&logoColor=white" />
</p>

<p align="center">
  <b>风电设备健康管理 &nbsp;·&nbsp; 故障智能诊断 &nbsp;·&nbsp; 预测性维护 &nbsp;·&nbsp; 知识图谱 &nbsp;·&nbsp; 多Agent协作 &nbsp;·&nbsp; 3D数字孪生</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-2.1-blue?style=flat-square" />
  <img src="https://img.shields.io/badge/status-active-success?style=flat-square" />
  <img src="https://img.shields.io/badge/license-Apache%202.0-blue?style=flat-square" />
  <img src="https://img.shields.io/badge/build-passing-brightgreen?style=flat-square" />
  <img src="https://img.shields.io/badge/tests-130%20passed-brightgreen?style=flat-square" />
  <img src="https://img.shields.io/badge/commits-100+-brightgreen?style=flat-square" />
</p>

<p align="center">
  🏆 <b>GOAI 无界应用赛道</b> · AI+工业制造 · 面向设备运维与供应链协同的工业 Agent
</p>

---

## 📖 目录

- [项目简介](#-项目简介)
- [为什么选择风调预顺](#-为什么选择风调预顺)
- [核心功能模块](#-核心功能模块)
- [技术架构](#-技术架构)
- [AI Agent 智能体架构](#-ai-agent-智能体架构)
- [3D 数字孪生](#-3d-数字孪生)
- [项目结构](#-项目结构)
- [快速开始](#-快速开始)
- [API 文档](#-api-文档)
- [测试](#-测试)
- [安全与合规](#-安全与合规)
- [开发团队](#-开发团队)
- [版本历史](#-版本历史)
- [开发规范](#-开发规范)
- [许可证](#-许可证)

---

## 📋 项目简介

**风调预顺**（WindOps ProofLoop）是面向风电行业的**预测性健康管理（Prognostics and Health Management, PHM）**平台，为风电场提供从实时监控、故障诊断、预测维护、工单管理、无人机巡检到知识沉淀的**全链路智能化运维闭环**。

### 🎯 目标用户

| 角色 | 核心诉求 | 平台价值 |
|------|----------|----------|
| 🧑‍🔧 **风场运维工程师** | 快速定位故障根因 | 多Agent自动诊断 + 振动频谱分析，分钟级定位 |
| 📋 **工单调度员** | 高效分派维修任务 | 智能分派建议 + 备件匹配 + 邮件通知 |
| 🏢 **风场管理者** | 全局健康状态掌控 | 30台风机实时地图 + 健康指数 + 经济效益分析 |
| 🔬 **设备专家** | 知识沉淀与复用 | 21节点故障知识图谱 + AI知识自增长闭环 |

### 🔄 任务闭环

```
设备异常 → 自动检测 → Agent诊断 → 工单创建 → 人员指派 → 维修执行 → 结果验证 → 知识沉淀
    │                                                                                    │
    └—————————————————————————— 全链路可追溯 · 可复盘 ——————————————————————————————————┘
```

> ⚠️ **边界声明**：本系统定位为**辅助分析与建议工具**，不替代专业人员判断，不直接控制工业设备。所有诊断结论均标注置信度与数据来源，高风险操作需人工确认。

---

## ✨ 为什么选择风调预顺

<table>
<tr>
<td width="50%">

### 🆚 传统方案 vs 风调预顺

| 维度 | 传统运维 | 风调预顺 |
|------|----------|----------|
| 故障发现 | 事后报警 | **预测性** + 实时自动检测 |
| 诊断方式 | 依赖专家经验 | **多Agent协作** + 知识图谱推理 |
| 工单流转 | 纸质/Excel | **全生命周期数字化** + 邮件通知 |
| 知识沉淀 | 个人经验流失 | **AI自动提取** + 图谱化沉淀 |
| 巡检方式 | 人工登塔 | **3D数字孪生** + 无人机路径规划 |
| 数据利用 | 只看实时SCADA | **多模态融合**（SCADA+振动+图像+气象） |

</td>
<td width="50%">

### 🏅 差异化亮点

- 🧠 **Playbook驱动架构** — 60+原子动作 + 20个高级工作流，工程级安全性和可复现性
- 🌱 **知识自增长闭环** — Copilot对话 → LLM提取 → Dedup → 自动入库，真正的"学习"能力
- 🔬 **多模态融合** — YOLO叶片检测 + 振动频谱 + SCADA时序 + 气象数据，5维交叉验证
- 🛸 **3D数字孪生** — Three.js程序化地形 + VRP多机分区 + A*航迹规划
- 🔗 **完整证据链** — 巡检→证据→事件→方案→审批→工单→验证→知识，全链路审计可追溯

</td>
</tr>
</table>

---

## 🎯 核心功能模块

| 模块 | 核心能力 | 技术亮点 |
|------|----------|----------|
| 🗺️ **风场监控** | 30台风机实时地图 + SCADA多维监测 | ECharts 多维可视化 + 健康指数评分(0-100) |
| 🔍 **故障诊断** | 自动故障检测 + 批量诊断 + 实时工作台 | 振动频谱分析(DFT/FFT) + YOLOv8叶片缺陷检测 |
| 📈 **预测决策** | RUL 剩余寿命预测 + 维修成本对比 | 维修时机优化 + 经济效益分析 + 维护日历 |
| 🛸 **无人机调度** | 3D数字孪生风场 + 巡检路径规划 | Three.js 三维渲染 + VRP多机分区 + A\*3D航迹 |
| 📋 **工单管理** | 全生命周期流转 + 邮件通知 | 优先级自动推算 + 人员技能匹配 + 处理追踪 |
| 📚 **故障百科** | 21种故障知识节点 + 9大分类 | 双视图知识图谱（运维拓扑 / 知识网络） |
| 🤖 **AI 助手** | Copilot 悬浮对话 + 截图识图 | Qwen多模型可切换 + 预设提示词 + 可拖动 |
| 🧠 **多Agent诊断** | Orchestrator → Data + Knowledge → Synthesizer | 4Agent协作 + 置信度评估 + 证据溯源 |
| 🌱 **知识自增长** | 对话 → 知识自动提取入库 | QualityGate → Extract → Dedup → Auto-Ingest |
| ⚙️ **系统管理** | 阈值/数据源/人员/API密钥 | 个人AI模型配置 + 邮件告警设置 + 角色权限 |

### 📊 数据规模

| 数据维度 | 规模 | 说明 |
|----------|------|------|
| 风机设备 | **30台** | 覆盖典型陆上风场规模 |
| SCADA 时序数据 | **520万+条** | 含风速/功率/温度/振动等10+维度 |
| 故障知识节点 | **21个** | 9大分类，含症状/根因/处置/备件信息 |
| YOLO 训练数据 | **DTU公开数据集** | 叶片缺陷检测4分类 |
| ERA5 气象数据 | **再分析公开数据** | 风速/风向/温度/气压 |
| 振动频谱 | **真实参考数据(CARE)** | 公开学术数据集 |

---

## 🏗️ 技术架构

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                              🌐 Nginx 反向代理                                 │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────────────────┐  ┌────────────────────────────────────┐ │
│  │     🖥️ 前端 (React 18 + Vite)    │  │        ⚡ 后端 (FastAPI)            │ │
│  │                                 │  │                                    │ │
│  │  📄 9 个页面                    │  │  📡 13 个 API 路由模块               │ │
│  │  🧩 30+ 组件                    │  │  🗄️ 12 个数据模型                    │ │
│  │  🎨 Tailwind CSS + ECharts      │  │  🔐 JWT 鉴权 + 角色权限              │ │
│  │  🗺️ Leaflet 2D 地图             │  │  🤖 4 Agent 协作框架                 │ │
│  │  🎮 Three.js 3D 数字孪生        │  │  📊 SCADA/气象数据管道               │ │
│  │  📚 知识图谱 (Force Graph)      │  │  ✉️ 异步邮件通知服务                  │ │
│  │  🗃️ Zustand 状态管理            │  │  🧪 YOLOv8 叶片缺陷检测               │ │
│  │                                 │  │  🔗 审计签名链 (SHA-256+Ed25519)    │ │
│  └───────────────┬─────────────────┘  └────────────────┬───────────────────┘ │
│                  │                                      │                     │
│                  └────────────────┬─────────────────────┘                     │
│                                   │                                           │
│  ┌────────────────────────────────▼────────────────────────────────────────┐ │
│  │                             🗄️ 数据与AI层                                │ │
│  │  SQLite (开发) / PostgreSQL (生产) · SQLAlchemy 2.0 async                 │ │
│  │  AI: Qwen-Plus (百炼) / OpenAI 兼容 / 可扩展 Ollama 本地                  │ │
│  │  数据源: CARE公开数据集 · ERA5气象 · 模拟SCADA · DTU叶片图像               │ │
│  └──────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 前端技术栈

| 类别 | 技术 | 版本 | 用途 |
|------|------|------|------|
| 框架 | React + TypeScript | 18 + 5.6 | SPA 应用 |
| 构建 | Vite | 5.4 | 开发/打包 |
| 样式 | Tailwind CSS | 3.4 | 原子化 CSS |
| 图表 | ECharts | 5.5 | 数据可视化 |
| 2D地图 | Leaflet + react-leaflet | 1.9 + 4.2 | 风机地理分布 |
| 3D引擎 | Three.js + @react-three/fiber | 0.170 + 8.18 | 风场数字孪生 |
| 3D工具 | @react-three/drei | 9.122 | 3D 辅助组件 |
| 状态管理 | Zustand | 5.0 | 全局状态 |
| 路由 | react-router-dom | 6.27 | 客户端路由 |
| HTTP | Axios | 1.7 | API 请求 |
| Markdown | marked | 18.0 | 富文本渲染 |
| 截图 | html2canvas | 1.4 | Copilot 识图 |

### 后端技术栈

| 类别 | 技术 | 版本 | 用途 |
|------|------|------|------|
| 框架 | FastAPI + uvicorn | 0.115 + 0.30 | 异步 REST API |
| 数据校验 | Pydantic | 2.9 | Schema 验证 |
| ORM | SQLAlchemy 2.0 (async) | 2.0 | 数据库抽象 |
| 数据库 | SQLite / PostgreSQL | — | 持久化存储 |
| 鉴权 | JWT + passlib + bcrypt | — | 用户认证 |
| 数据处理 | pandas + numpy + scipy | 2.2 + 1.26 + 1.14 | 科学计算 |
| 叶片检测 | ultralytics (YOLOv8) | 8.2 | 叶片缺陷视觉检测 |
| 图像处理 | opencv + Pillow | 4.10 + 10.4 | 图像预处理 |
| 气象数据 | xarray + netCDF4 | 2024.9 + 1.7 | ERA5 再分析数据 |
| AI/LLM | openai + dashscope | 1.55 + 1.20 | Qwen/OpenAI 调用 |
| 邮件 | aiosmtplib | 3.0 | 异步邮件发送 |
| 日志 | structlog | 24.1 | 结构化日志 |
| 测试 | pytest + pytest-asyncio | 8.4 | 单元/集成测试 |

---

## 🧠 AI Agent 智能体架构

### 双层架构设计

```
┌──────────────────────────────────────────────────────────────┐
│                    Layer 1: Playbook 驱动层                    │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  60+ 原子动作 (AgentAction)                               │ │
│  │  20 个高级工作流 (AgentWorkflow)                           │ │
│  │  JSON 配置化 · 确定性执行 · 安全边界内置                    │ │
│  │  关键词加权评分检索 · 槽位自动提取                          │ │
│  └──────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│              Layer 2: LLM 多Agent 协作层                      │
│                                                              │
│  用户提问 "3号风机振动超标是什么原因?"                          │
│          │                                                   │
│          ▼                                                   │
│  ┌──────────────────────┐                                    │
│  │ ① Orchestrator Agent │  意图解析 → 并行派发                  │
│  └──────┬───────┬───────┘                                    │
│         │       │                                            │
│   ┌─────▼──┐ ┌──▼──────┐                                     │
│   │② Data  │ │③ Knowl. │  Data Agent: SCADA/RUL/振动/故障历史  │
│   │ Agent  │ │ Agent   │  Knowl Agent: 21节点知识图谱检索        │
│   └────┬───┘ └──┬──────┘                                     │
│        │        │                                            │
│        └───┬────┘                                            │
│            ▼                                                 │
│  ┌──────────────────────┐                                    │
│  │④ Synthesizer Agent   │  交叉验证 → 置信度评分 → 诊断报告     │
│  │                       │  多模态冲突检测 → 证据边生成          │
│  └──────────────────────┘                                    │
│            │                                                 │
│            ▼                                                 │
│  📊 Copilot 面板: 诊断报告 + 建议行动 + 证据溯源               │
└──────────────────────────────────────────────────────────────┘
```

### 知识自增长闭环

```
Copilot 诊断对话
      │
      ▼
  QualityGate ────── 质量门禁（含置信度/完整性检查）
      │
      ▼
  Extract (LLM) ──── 从对话中提取结构化知识
      │
      ▼
  Dedup (LLM) ───── 与现有知识库去重
      │
      ▼
  Auto-Ingest ────── 自动入库 + 人工审核入口
      │
      ▼
  📚 知识图谱自动更新
  🤖 AI提取标签 + 置信度标注
  [确认] [删除] 审核入口
```

### Agent 安全边界

| 安全机制 | 说明 |
|----------|------|
| 🔒 **Playbook约束** | 所有Agent操作限定在预定义Playbook内，不可自由发挥 |
| ⚠️ **高风险标记** | 涉及设备控制的建议自动标记高风险，需人工确认 |
| 📋 **审计签名链** | SHA-256 哈希 + Ed25519 签名，全链路操作可追溯 |
| 🚫 **读写分离** | 诊断/咨询为只读，工单/设置为受限写 |
| 🛡️ **不替代专业判断** | 所有诊断结论附带置信度和"请结合现场确认"提示 |

---

## 🛸 3D 数字孪生

基于 **Three.js** 的无人机巡检三维仿真系统，实现从二维监控到三维孪生的完整覆盖：

- 🏔️ **地形渲染**: 程序化地形生成 + 柏林噪声模拟
- 🌬️ **风机模型**: 30台3D风机 + 叶尖/叶根/前缘/后缘/轮毂/机舱 6部位标注
- 🛸 **无人机模拟**: 多机编队起飞 → 巡检航点 → 拍摄 → 返航全流程
- 🛣️ **路径规划**: VRP 多机分区 + A\* 3D 最短路径 + 禁飞区绕行
- 📹 **HUD 信息**: 实时飞行数据叠加（高度/速度/电池/拍摄计数）
- 🔄 **双视图**: Overview 总览 / Detail 单风机特写镜头切换
- 🔍 **缺陷标记**: 叶片缺陷检测结果3D标注 + 补拍标记
- 📡 **事件联动**: 巡检发现 → 自动生成工单 + 证据资产持久化

---

## 📁 项目结构

```
feng/
├── backend/
│   ├── app/
│   │   ├── api/                          # 13 个 API 路由模块
│   │   │   ├── agent.py                  # 多Agent诊断接口
│   │   │   ├── agent_actions.py          # Agent操作接口
│   │   │   ├── agent_tasks.py            # Agent任务管理
│   │   │   ├── agent_tools.py            # Agent工具注册
│   │   │   ├── ai.py                     # AI 服务 (summary/analyze/copilot)
│   │   │   ├── auth.py                   # 认证 (register/login/me)
│   │   │   ├── diagnosis.py              # 故障诊断 + 实时诊断工作台
│   │   │   ├── drone.py                  # 🆕 无人机巡检 API (11 endpoints)
│   │   │   ├── incidents.py              # 🆕 事件中心 + 多模态冲突 API
│   │   │   ├── knowledge.py              # 故障百科 CRUD + 图谱数据
│   │   │   ├── personnel.py              # 人员管理
│   │   │   ├── prediction.py             # RUL 预测 + 成本对比
│   │   │   ├── settings.py               # 系统设置 + 阈值/数据源
│   │   │   ├── turbines.py               # 风机管理 + 监测指标
│   │   │   └── workorders.py             # 工单生命周期 + 邮件通知
│   │   ├── domain/                       # 领域模型
│   │   ├── models/__init__.py            # 12 个 SQLAlchemy 数据模型
│   │   ├── schemas/__init__.py           # Pydantic 请求/响应模式
│   │   ├── services/
│   │   │   ├── agents/                   # Agent 实体定义
│   │   │   ├── agent_actions/            # 60+ 原子动作
│   │   │   ├── agent_playbooks/          # 20 个高级工作流 + 知识库
│   │   │   ├── agent_workflows/          # Agent工作流引擎
│   │   │   ├── blade_yolo_service.py     # YOLOv8 叶片缺陷检测
│   │   │   ├── multimodal_conflict_service.py  # 🆕 多模态冲突分析
│   │   │   ├── copilot_context.py        # Copilot上下文管理
│   │   │   ├── diagnosis_orchestrator.py # 诊断编排引擎
│   │   │   ├── email_service.py          # 邮件发送服务
│   │   │   ├── health_index.py           # 健康指数计算
│   │   │   ├── knowledge_extractor.py    # 知识提取 (对话→知识)
│   │   │   ├── maintenance_scheduler.py  # 维护排程
│   │   │   ├── prediction_service.py     # 预测模型服务
│   │   │   └── qwen_client.py            # Qwen/OpenAI 统一客户端
│   │   ├── core/security.py              # JWT + 密码哈希
│   │   ├── config.py                     # 多源配置管理
│   │   ├── database.py                   # SQLite/PostgreSQL 双引擎
│   │   └── main.py                       # FastAPI 应用入口
│   ├── scripts/                          # 数据管理脚本
│   │   ├── seed_data.py                  # 数据库初始化 + 种子数据
│   │   └── ...                           # 数据集导入/处理/验证
│   ├── tests/                            # 测试文件 (130+ passed)
│   ├── alembic/                          # 数据库迁移
│   ├── launcher.py                       # 🆕 便携版启动器
│   └── requirements.txt                  # Python 依赖清单
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Dashboard/                # 风场监控 (地图+KPI+SCADA)
│   │   │   ├── Diagnosis/                # 故障诊断 (实时工作台+批量)
│   │   │   ├── DroneScheduler/           # 🆕 无人机调度 (3D数字孪生)
│   │   │   ├── Knowledge/                # 故障百科 (21节点+双视图图谱)
│   │   │   ├── Prediction/               # 预测决策 (RUL+成本+维护日历)
│   │   │   ├── Settings/                 # 系统设置 (阈值+数据源+AI密钥)
│   │   │   ├── TurbineDetail/            # 风机详情 (SCADA趋势+振动)
│   │   │   ├── WorkOrder/                # 工单管理 (生命周期+邮件)
│   │   │   └── Login/                    # 登录注册
│   │   ├── components/
│   │   │   ├── AIAssistant/              # CopilotFAB + AIPanel
│   │   │   ├── Common/                   # ErrorBoundary, FilterPanel 等
│   │   │   ├── Layout/                   # AppLayout (侧边栏+顶栏)
│   │   │   └── Map/                      # 2D地图 + 🆕 Three.js 3D组件
│   │   ├── services/                     # API 客户端 + 状态管理
│   │   └── utils/                        # 🆕 A*/VRP/地形生成工具
│   ├── package.json
│   ├── vite.config.ts
│   └── tailwind.config.js
├── 🆕 启动风调预顺.bat                    # 一键启动脚本
├── .env.example                          # 环境变量模板
├── .gitignore
├── COMPETITION_GOAL.md                   # 比赛执行状态
├── LICENSE
├── NOTICE
└── README.md
```

---

## 🚀 快速开始

### 环境要求

| 依赖 | 版本 | 说明 |
|------|------|------|
| Python | 3.10+ (推荐 3.11) | conda 环境推荐 |
| Node.js | 18+ | 前端构建 |
| 阿里百炼 API Key | (可选) | [免费申请](https://dashscope.aliyun.com/) |

### ⚡ 一键启动（推荐）

```bash
# Windows: 双击运行
启动风调预顺.bat
```

### 🔧 手动启动

```bash
# === 1. 后端 ===
cd backend

# conda 环境 (推荐)
conda create -n phm python=3.11 -y && conda activate phm

# 安装依赖
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 初始化数据库（种子数据 + 21个故障知识节点）
python -m scripts.seed_data

# 启动后端 → http://localhost:8000
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# === 2. 前端 (新终端, 开发模式) ===
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173

# === 3. 前端 (生产模式, 后端直接托管) ===
cd frontend && npm run build
# 访问 http://localhost:8000 即可
```

> 📌 **默认登录**: `admin` / `admin123`  
> 📖 **API 文档**: http://127.0.0.1:8000/api/docs  
> 🩺 **健康检查**: http://127.0.0.1:8000/api/health

---

## 📡 API 文档

| 模块 | 端点 | 方法 | 说明 | 鉴权 |
|------|------|------|------|:--:|
| 🔐 **认证** | `/api/auth/register` | POST | 用户注册 | - |
| | `/api/auth/login` | POST | 用户登录 → JWT | - |
| | `/api/auth/me` | GET | 当前用户信息 | 🔐 |
| 🗺️ **风机** | `/api/turbines/` | GET | 风机列表 + 统计指标 | 🔐 |
| | `/api/turbines/monitoring-metrics` | GET | 监测指标 (MTBF/可用率/健康指数) | 🔐 |
| | `/api/turbines/{id}` | GET | 风机详情 + SCADA 时序 | 🔐 |
| 🔍 **诊断** | `/api/diagnosis/faults` | GET | 故障列表 | 🔐 |
| | `/api/diagnosis/auto-fault-detection` | POST | 自动故障检测 | 🔐 |
| 📈 **预测** | `/api/prediction/rul` | GET | RUL 剩余寿命预测 | 🔐 |
| | `/api/prediction/cost-comparison` | POST | 维修成本对比 | 🔐 |
| 📋 **工单** | `/api/workorders/` | GET/POST | 工单列表/创建 | 🔐 |
| | `/api/workorders/{id}` | PUT/DELETE | 工单更新/删除 | 🔐 |
| | `/api/workorders/{id}/send-email` | POST | 发送工单邮件 | 🔐 |
| 📚 **知识库** | `/api/knowledge-base` | GET | 故障知识列表 | 🔐 |
| | `/api/knowledge-base/search?q=` | GET | 知识搜索 | 🔐 |
| | `/api/knowledge-graph` | GET | 知识图谱 (节点+边) | 🔐 |
| 🤖 **Agent** | `/api/agent/diagnose` | POST | 多Agent诊断 | 🔐 |
| 🤖 **AI** | `/api/ai/copilot` | POST | AI 对话 + 知识提取 | 🔐 |
| | `/api/ai/analyze-fault` | POST | AI 故障分析 | 🔐 |
| 🛸 **无人机** | `/api/drone/*` | 11端点 | 巡检任务 + 证据资产 | 🔐 |
| 📡 **事件** | `/api/incidents/*` | 多端点 | 事件中心 + 多模态冲突 | 🔐 |
| 👥 **人员** | `/api/personnel/` | GET/POST | 人员管理 | 🔐 |
| ⚙️ **设置** | `/api/settings/` | GET/PUT | 系统设置 | 🔐 |

---

## 🧪 测试

| 测试类型 | 命令 | 状态 |
|----------|------|:--:|
| 后端单元测试 | `cd backend && python -m pytest tests/ -v --tb=short` | ✅ 130 passed |
| 前端构建 | `cd frontend && npm run build` | ✅ 通过 |
| E2E 测试 | Playwright 场景测试 (3 scenarios) | ✅ 通过 |
| 黄金 Demo | 13/13 HTTP 200 | ✅ 通过 |
| 无障碍审计 | a11y audit | ✅ 通过 |

---

## 🔒 安全与合规

| 维度 | 措施 |
|------|------|
| 🔐 **认证** | JWT + bcrypt 密码哈希 + 令牌过期策略 |
| 🛡️ **授权** | 基于角色的访问控制 (RBAC) |
| 📝 **审计** | SHA-256 + Ed25519 审计签名链 |
| 🔑 **API Key** | 用户级密钥管理 + 脱敏显示 |
| 📊 **数据来源** | CARE公开数据集(学术授权) + ERA5气象(公开) + 模拟SCADA(自建) |
| 🏥 **隐私保护** | 数据最小化使用 + 用户数据隔离 |
| ⚠️ **风险提示** | 所有诊断结论带置信度 + "请结合现场确认"提示 |
| 🚫 **边界声明** | 不替代专业人员判断，不直接控制工业设备 |
| 📜 **合规** | 符合Apache 2.0协议 + 第三方依赖披露完整 |

---

## 📈 版本历史

### v2.1 (2026-07) 🆕

- ✅ **无人机巡检闭环**: 巡检任务持久化 + 证据资产 + 动态补拍
- ✅ **多模态冲突感知**: 5维交叉对比 + 证据边自动生成
- ✅ **事件中心**: Incident闭环（调查→方案→审批→执行→验证）
- ✅ **审计签名链**: SHA-256 + Ed25519 全链路可追溯
- ✅ **红队测试**: 真实行为评分 + 安全水位评估
- ✅ **黄金演示场景**: 13步确定性格子，13/13通过

### v2.0 (2026-06)

- ✅ **3D 数字孪生**: Three.js 风场三维可视化
- ✅ **无人机巡检**: 多机编队 + VRP分区 + A*航迹 + 禁飞区绕行
- ✅ **故障百科**: 21 节点知识图谱 + 9 大分类
- ✅ **多 Agent 诊断**: Orchestrator → Data + Knowledge → Synthesizer
- ✅ **知识自增长**: Copilot 对话 → LLM 提取 → 自动入库

### v1.5 (2026-06)

- ✅ 实时诊断工作台 (diagnosis_orchestrator)
- ✅ AI 助手预设定 + 可拖动 + 截图识图
- ✅ 工单邮件通知 + 离线数据库支持

### v1.0 (2026-05)

- 🎉 初始版本: 8 个核心模块 + AI 助手 + 数据管道

---

## 🔧 开发规范

### 分支管理

```
main                ← 稳定发布分支
codex/goai-wind-ops ← 🆕 比赛冲刺分支
feature/*           ← 功能开发分支
```

- 从 `main` 创建 `feature/xxx` 分支开发
- 开发完成后合并至 `main`，由技术负责人审核
- `main` 始终保持可运行状态

### 代码规范

- **后端**: FastAPI 异步路由 + Pydantic 类型校验 + SQLAlchemy 2.0 async session
- **前端**: React Hooks + TypeScript strict + Tailwind 原子化 + Zustand 状态管理
- **AI调用**: 统一通过 `qwen_client.py` → 支持 Qwen / OpenAI / 自定义 endpoint
- **数据库**: SQLite 开发 / PostgreSQL 生产，通过 `DATABASE_URL` 环境变量切换

---

## 📄 许可证

本项目基于 **Apache License 2.0** 开源协议发布。

第三方依赖及其许可证详见 [THIRD_PARTY_NOTICES.md](./THIRD_PARTY_NOTICES.md) 和 [NOTICE](./NOTICE)。

---

<br/>
<p align="center">
  <b>🌪️ 风调预顺 — 预知风云变幻，守护每一度清洁能源 🌪️</b>
  <br/>
  <sub>WindOps ProofLoop · Verifiable Closed-Loop Industrial Agent for Wind Power PHM</sub>
</p>
