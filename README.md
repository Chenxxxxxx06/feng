# 🌪️ 风调预顺 WindOps ProofLoop — 可验证闭环工业 Agent

> 不只是预测哪里可能坏，而是把一次设备异常自动组织成**可解释、可审批、可执行、可验证、可复盘**的运维事件。

> Unit tests passing | Integration tests (requires API key) | E2E ready | Alembic migrations

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11-3776AB?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/FastAPI-0.115-009688?style=for-the-badge&logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/React-18-61DAFB?style=for-the-badge&logo=react&logoColor=black" />
  <img src="https://img.shields.io/badge/TypeScript-5.6-3178C6?style=for-the-badge&logo=typescript&logoColor=white" />
  <img src="https://img.shields.io/badge/Three.js-0.170-000000?style=for-the-badge&logo=threedotjs&logoColor=white" />
  <img src="https://img.shields.io/badge/ECharts-5.5-AA344D?style=for-the-badge&logo=apacheecharts&logoColor=white" />
  <img src="https://img.shields.io/badge/Tailwind-3.4-06B6D4?style=for-the-badge&logo=tailwindcss&logoColor=white" />
  <img src="https://img.shields.io/badge/Qwen-Plus-FF6A00?style=for-the-badge&logo=openai&logoColor=white" />
</p>

<p align="center">
  <b>风电设备健康管理 · 故障智能诊断 · 预测性维护 · 知识图谱 · 多Agent协作 · 3D数字孪生</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-2.1-blue" />
  <img src="https://img.shields.io/badge/status-active-success" />
  <img src="https://img.shields.io/badge/license-Apache%202.0-blue" />
  <img src="https://img.shields.io/badge/commits-90+-brightgreen" />
</p>

---

## 📋 项目简介

**风调预顺**是面向风电行业的**预测性健康管理 (Prognostics and Health Management)** 平台，面向风电场提供从实时监控、故障诊断、预测维护、工单管理到无人机巡检的**全链路智能化运维方案**（Demo/原型验证阶段，非生产部署）。

### 🎯 核心功能模块

| 模块 | 核心能力 | 技术亮点 |
|------|----------|----------|
| 🗺️ **风场监控** | 30台风机实时地图 + SCADA监测 | ECharts 多维可视化 + 健康指数评分 |
| 🔍 **故障诊断** | 自动故障检测 + 批量诊断 | 实时诊断工作台 + 振动频谱分析 + YOLOv8叶片检测 |
| 📈 **预测决策** | RUL 剩余寿命 + 维修成本对比 | 维修时机优化 + 经济效益分析 + 维护日历 |
| 🛸 **无人机调度** | 3D数字孪生风场 + 巡检路径规划 | Three.js 三维渲染 + VRP多机分区 + A*3D航迹 |
| 📋 **工单管理** | 全生命周期流转 + 邮件通知 | 优先级管理 + 人员指派 + 处理追踪 |
| 📚 **故障百科** | 21种故障知识节点 + 9大分类 | 双视图知识图谱 (运维拓扑 / 知识网络) |
| 🤖 **AI 助手** | Copilot 悬浮对话 + 截图识图 | Qwen多模型可切换 + 预设提示词 |
| 🧠 **多Agent诊断** | 智能调度诊断 | Orchestrator → Data Agent + Knowledge Agent → Synthesizer |
| 🌱 **知识自增长** | 对话 → 知识自动提取入库 | QualityGate → Extract → Dedup → Auto-Ingest |
| ⚙️ **系统管理** | 阈值/数据源/人员/API密钥 | 个人AI模型配置 + 邮件告警设置 |

---

## 🏗️ 技术架构

```
┌──────────────────────────────────────────────────────────────────────┐
│                         🌐 Nginx 反向代理                             │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌───────────────────────────────┐  ┌──────────────────────────────┐ │
│  │     🖥️ 前端 (React 18 + Vite)   │  │    ⚡ 后端 (FastAPI)          │ │
│  │                               │  │                              │ │
│  │  📄 9 个页面                   │  │  📡 10 个 API 模块            │ │
│  │  🧩 30+ 组件                   │  │  🗄️ 12 个数据表               │ │
│  │  🎨 Tailwind CSS + ECharts    │  │  🔐 JWT 鉴权                 │ │
│  │  🗺️ Leaflet 2D 地图           │  │  🤖 4 Agent 协作              │ │
│  │  🎮 Three.js 3D 数字孪生       │  │  📊 SCADA/气象数据管道         │ │
│  │  📚 知识图谱 (Force Graph)     │  │  ✉️ 邮件通知服务              │ │
│  │  🗃️ Zustand 状态管理           │  │  🧪 YOLOv8 叶片缺陷检测        │ │
│  │                               │  │                              │ │
│  └───────────────┬───────────────┘  └──────────────┬───────────────┘ │
│                  │                                  │                 │
│                  └────────────┬─────────────────────┘                 │
│                               │                                       │
│  ┌────────────────────────────▼────────────────────────────────────┐ │
│  │                         🗄️ 数据层                                │ │
│  │  SQLite (开发) / PostgreSQL (生产) · SQLAlchemy 2.0 async         │ │
│  │  AI: Qwen-Plus (百炼) / OpenAI 兼容 / 可扩展Ollama本地            │ │
│  └─────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
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
| 数据库 | SQLite (开发) / PostgreSQL (生产) | — | 持久化存储 |
| 鉴权 | JWT + passlib + bcrypt | — | 用户认证 |
| 数据处理 | pandas + numpy + scipy | 2.2 + 1.26 + 1.14 | 科学计算 |
| 叶片检测 | ultralytics (YOLOv8) | 8.2 | 叶片缺陷视觉检测 |
| 图像处理 | opencv + Pillow | 4.10 + 10.4 | 图像预处理 |
| 气象数据 | xarray + netCDF4 | 2024.9 + 1.7 | ERA5 再分析数据 |
| AI/LLM | openai + dashscope | 1.55 + 1.20 | Qwen/OpenAI 调用 |
| 邮件 | aiosmtplib | 3.0 | 异步邮件发送 |
| 日志 | structlog | 24.1 | 结构化日志 |
| 文档解析 | python-docx + openpyxl + PyPDF2 | — | 知识库导入 |
| 模板 | Jinja2 | 3.1 | 报告渲染 |
| 测试 | pytest + pytest-asyncio | 8.4 | 单元/集成测试 |

---

## 🧠 AI 智能体架构

```
用户提问 "3号风机振动超标是什么原因?"
        │
        ▼
   ┌──────────────────────┐
   │ ① Orchestrator Agent │  意图解析 → 并行派发
   └──────┬───────┬───────┘
          │       │
    ┌─────▼──┐ ┌──▼──────┐
    │② Data  │ │③ Knowl. │   Data Agent: 查 SCADA/RUL/故障历史
    │ Agent  │ │ Agent   │   Knowl Agent: 查 21节点知识图谱
    └────┬───┘ └──┬──────┘
         │        │
         └───┬────┘
             ▼
   ┌──────────────────────┐
   │ ④ Synthesizer Agent  │  交叉验证 → 置信度 → 诊断报告
   └──────────────────────┘
             │
             ▼
   📊 Copilot 面板展示诊断报告 + 建议行动
```

### 知识自增长闭环

```
Copilot 诊断对话 → QualityGate → Extract (LLM) → Dedup (LLM) → Auto-Ingest
                                                                     │
                                                                     ▼
                                                         📚 知识图谱自动更新
                                                         🤖 AI提取标签 + 置信度
                                                         [确认] [删除] 审核入口
```

---

## 🛸 3D 数字孪生 (新增)

基于 **Three.js** 的无人机巡检三维仿真系统：

- 🏔️ **地形渲染**: 程序化地形生成 + 噪声模拟
- 🌬️ **风机模型**: 30台3D风机 (含glb模型) + 叶尖/叶根/前缘/后缘/轮毂/机舱 6部位标注
- 🛸 **无人机模拟**: 多机编队起飞 → 巡检航点 → 返航全流程
- 🛣️ **路径规划**: VRP 多机分区 + A* 3D 最短路径 + 禁飞区绕行
- 📹 **HUD 信息**: 实时飞行数据叠加 (高度/速度/电池/拍摄计数)
- 🔄 **双视图**: Overview 总览 / Detail 单风机特写镜头切换

---

## 📁 项目结构

```
feng/
├── backend/
│   ├── app/
│   │   ├── api/                        # 10 个 API 路由模块
│   │   │   ├── agent.py                # 多Agent诊断接口
│   │   │   ├── agent_actions.py        # Agent操作接口
│   │   │   ├── agent_tasks.py          # Agent任务管理
│   │   │   ├── agent_tools.py          # Agent工具注册
│   │   │   ├── ai.py                   # AI 服务 (summary/analyze/copilot)
│   │   │   ├── auth.py                 # 认证 (register/login/me)
│   │   │   ├── diagnosis.py            # 故障诊断 + 实时诊断工作台
│   │   │   ├── knowledge.py            # 故障百科 CRUD + 图谱数据
│   │   │   ├── personnel.py            # 人员管理
│   │   │   ├── prediction.py           # RUL 预测 + 成本对比
│   │   │   ├── settings.py             # 系统设置 + 阈值/数据源
│   │   │   ├── turbines.py             # 风机管理 + 监测指标
│   │   │   └── workorders.py           # 工单生命周期 + 邮件通知
│   │   ├── models/__init__.py          # 12 个 SQLAlchemy 数据模型
│   │   ├── schemas/__init__.py         # Pydantic 请求/响应模式
│   │   ├── services/
│   │   │   ├── agent_data_tools.py     # 数据Agent工具集
│   │   │   ├── agent_llm_planner.py    # LLM任务规划器
│   │   │   ├── agent_read_tasks.py     # Agent读取任务
│   │   │   ├── agent_slot_extractor.py # 槽位提取器
│   │   │   ├── agent_task_planner.py   # Agent任务编排
│   │   │   ├── blade_yolo_service.py   # YOLOv8 叶片缺陷检测
│   │   │   ├── care_monitoring_metrics.py # 监测指标计算
│   │   │   ├── copilot_context.py      # Copilot上下文管理
│   │   │   ├── data_registry.py        # 数据注册表
│   │   │   ├── diagnosis_orchestrator.py # 诊断编排引擎
│   │   │   ├── email_service.py        # 邮件发送服务
│   │   │   ├── health_index.py         # 健康指数计算
│   │   │   ├── knowledge_extractor.py  # 知识提取 (对话→知识)
│   │   │   ├── maintenance_planner.py  # 维护计划生成
│   │   │   ├── maintenance_scheduler.py # 维护排程
│   │   │   ├── prediction_service.py   # 预测模型服务
│   │   │   └── qwen_client.py          # Qwen/OpenAI 统一客户端
│   │   ├── core/security.py            # JWT + 密码哈希
│   │   ├── config.py                   # 多源配置管理
│   │   ├── database.py                 # SQLite/PostgreSQL 双引擎
│   │   └── main.py                     # FastAPI 应用入口
│   ├── scripts/                        # 14 个数据管理脚本
│   │   ├── seed_data.py                # 数据库初始化 + 种子数据
│   │   ├── manage_db.py                # 数据库管理工具
│   │   └── ...                         # 数据集导入/处理/验证
│   ├── tests/                          # 14 个测试文件
│   └── requirements.txt                # Python 依赖清单
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Dashboard/              # 风场监控 (地图+KPI+SCADA)
│   │   │   ├── Diagnosis/              # 故障诊断 (实时工作台+批量)
│   │   │   ├── DroneScheduler/         # 🆕 无人机调度 (3D数字孪生)
│   │   │   ├── Knowledge/              # 故障百科 (21节点+双视图图谱)
│   │   │   ├── Prediction/             # 预测决策 (RUL+成本+维护日历)
│   │   │   ├── Settings/               # 系统设置 (阈值+数据源+AI密钥)
│   │   │   ├── TurbineDetail/          # 风机详情 (SCADA趋势+振动)
│   │   │   ├── WorkOrder/              # 工单管理 (生命周期+邮件)
│   │   │   └── Login/                  # 登录注册
│   │   ├── components/
│   │   │   ├── AIAssistant/            # CopilotFAB + AIPanel
│   │   │   ├── Common/                 # ErrorBoundary, FilterPanel, ResizableDivider
│   │   │   ├── Layout/                 # AppLayout (侧边栏+顶栏)
│   │   │   └── Map/                    # 2D地图 (TurbineMap, DroneMap)
│   │   │       └── three/              # 🆕 3D组件 (10个Three.js模块)
│   │   ├── services/
│   │   │   ├── agent/                  # Agent执行器 + 技能注册
│   │   │   ├── api.ts                  # Axios 实例
│   │   │   ├── authStore.ts            # 认证状态
│   │   │   ├── copilotStore.ts         # AI对话状态
│   │   │   ├── drone3dStore.ts         # 🆕 3D无人机状态管理
│   │   │   └── predictionService.ts    # 预测数据服务
│   │   ├── utils/
│   │   │   ├── aStar3DPathPlanner.ts   # 🆕 A* 3D航迹规划
│   │   │   ├── coordinateTransform.ts  # 🆕 坐标转换工具
│   │   │   ├── dronePathPlanner.ts     # 🆕 VRP/TSP 路径优化
│   │   │   ├── droneSimulator.ts       # 🆕 无人机飞行仿真
│   │   │   └── terrainGenerator.ts     # 🆕 程序化地形生成
│   │   └── types/index.ts             # TypeScript 类型定义
│   ├── package.json
│   ├── vite.config.ts
│   └── tailwind.config.js
├── .env.example                         # 环境变量模板
├── .gitignore                           # Git 忽略规则
├── start.ps1                            # 一键启动脚本 (PowerShell)
├── SETUP_REQUIREMENTS.txt               # 环境配置说明
└── README.md
```

---

## 🚀 快速开始

### 环境要求

| 依赖 | 版本 | 说明 |
|------|------|------|
| Python | 3.10+ (推荐 3.11) | conda 环境推荐 |
| Node.js | 18+ | 前端构建 |
| (可选) 阿里百炼 API Key | — | [免费申请](https://dashscope.aliyun.com/) |

### 3 分钟启动

```bash
# === 后端 ===
cd backend

# conda 环境 (推荐)
conda create -n phm python=3.11 -y && conda activate phm

# 安装依赖
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 初始化数据库 (种子数据 + 21个故障知识节点)
python -m scripts.seed_data

# 启动后端 → http://localhost:8000
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# === 前端 (新终端) ===
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173

# === 一键启动 (PowerShell) ===
.\start.ps1
```

> **默认登录**: `admin` / `admin123`  
> **API 文档**: http://127.0.0.1:8000/api/docs

---

## 📡 API 端点概览

| 端点 | 方法 | 说明 | 鉴权 |
|------|------|------|:--:|
| `/api/auth/register` | POST | 用户注册 | - |
| `/api/auth/login` | POST | 用户登录 → JWT | - |
| `/api/auth/me` | GET | 当前用户信息 | 🔐 |
| `/api/turbines/` | GET | 风机列表 + 统计指标 | 🔐 |
| `/api/turbines/monitoring-metrics` | GET | 监测指标 (MTBF/可用率/健康指数) | 🔐 |
| `/api/turbines/{id}` | GET | 风机详情 + SCADA 时序 | 🔐 |
| `/api/diagnosis/faults` | GET | 故障列表 | 🔐 |
| `/api/diagnosis/auto-fault-detection` | POST | 自动故障检测 | 🔐 |
| `/api/prediction/rul` | GET | RUL 剩余寿命预测 | 🔐 |
| `/api/prediction/cost-comparison` | POST | 维修成本对比 | 🔐 |
| `/api/workorders/` | GET/POST | 工单列表/创建 | 🔐 |
| `/api/workorders/{id}` | PUT/DELETE | 工单更新/删除 | 🔐 |
| `/api/workorders/{id}/send-email` | POST | 发送工单邮件 | 🔐 |
| `/api/knowledge-base` | GET | 故障知识列表 | 🔐 |
| `/api/knowledge-base/search?q=` | GET | 知识搜索 | 🔐 |
| `/api/knowledge-base/{id}` | GET | 知识节点详情 | 🔐 |
| `/api/knowledge-base/{id}/verify` | PATCH | 确认AI提取知识 | 🔐 |
| `/api/knowledge-graph` | GET | 知识图谱 (节点+边) | 🔐 |
| `/api/agent/diagnose` | POST | 多Agent诊断 | 🔐 |
| `/api/ai/summary` | POST | AI 页面总结 | 🔐 |
| `/api/ai/analyze-fault` | POST | AI 故障分析 | 🔐 |
| `/api/ai/copilot` | POST | AI 对话 + 知识提取 | 🔐 |
| `/api/personnel/` | GET/POST | 人员管理 | 🔐 |
| `/api/settings/` | GET/PUT | 系统设置 | 🔐 |

---

## 👥 开发团队

| 姓名 | 角色 |
|------|------|
| **陈曦** | 技术负责人 — 全栈架构 + AI Agent + 知识图谱 + 3D数字孪生 |
| **牛中义** | 前端开发 — 风场监控 + 故障诊断 |
| **王红娟** | 前端开发 — 工单管理 + 系统设置 |
| **张文仿** | 后端开发 — 预测决策 + 数据管道 |
| **逄晋** | 前端开发 — 故障百科 + 知识图谱可视化 |
| **战心悦** | 后端开发 — 无人机调度 + 路径规划算法 |
| **朱彤浩** | 后端开发 — 邮件通知 + 人员管理 |
| **徐韵涵** | 前端开发 — AI助手 + Copilot 交互 |

> 西北工业大学 · 软件架构设计课程 · 第十五组 · 2026

---

## 📈 版本历史

### v2.1 (2026-06-17)
- ✅ **3D 数字孪生**: Three.js 风场三维可视化
- ✅ **无人机巡检**: 多机编队 + VRP分区 + A*航迹 + 禁飞区绕行
- ✅ **巡检航点**: 6部位标注 (叶尖/叶根/前缘/后缘/轮毂/机舱)
- ✅ **系统设置增强**: 邮件告警配置 + 阈值管理
- ✅ **双视图图谱**: 运维拓扑 + 知识网络

### v2.0 (2026-06-12)
- ✅ **故障百科**: 21 节点知识图谱 + 9 大分类
- ✅ **多 Agent 诊断**: Orchestrator → Data + Knowledge → Synthesizer
- ✅ **知识自增长**: Copilot 对话 → LLM 提取 → 自动入库
- ✅ **API Key 全链路贯通**: 用户密钥 → 所有 LLM 调用

### v1.5 (2026-06-11)
- ✅ 实时诊断工作台 (diagnosis_orchestrator)
- ✅ AI 助手预设定 + 可拖动 + 截图识图
- ✅ 工单邮件通知 + 优化
- ✅ 离线数据库支持

### v1.0 (2026-05)
- 🎉 初始版本: 8 个核心模块 + AI 助手 + 数据管道

---

## 🔧 开发规范

### 分支管理

```
master    ← 纯代码 (核心源码)
dev       ← 开发主线 (代码 + README)
feature/* ← 各成员功能分支
```

- 从 `dev` 拉取最新代码，创建 `feature/xxx` 分支
- 开发完成后合并至 `dev`，由技术负责人审核
- `dev` 稳定后提取核心代码推送至 `master`

### 代码规范

- **后端**: FastAPI 异步路由 + Pydantic 类型校验 + SQLAlchemy 2.0 async session
- **前端**: React Hooks + TypeScript strict + Tailwind 原子化 + Zustand 状态管理
- **AI调用**: 统一通过 `qwen_client.py` → 支持 Qwen / OpenAI / 自定义 endpoint
- **数据库**: SQLite 开发 / PostgreSQL 生产，通过 `DATABASE_URL` 环境变量切换

---

## 📄 许可证

本项目为**西北工业大学软件架构设计课程**项目，仅供学习和研究使用。

---

<p align="center">
  <sub>⚡ 风调预顺 — 预知风云变幻，守护每一度清洁能源 ⚡</sub>
</p>
