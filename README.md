# 🌪️ 风调预顺 — PHM 预测性运维系统

> *"预知风云变幻，守护每一度清洁能源"*

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/FastAPI-0.115-009688?style=for-the-badge&logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/React-18-61DAFB?style=for-the-badge&logo=react&logoColor=black" />
  <img src="https://img.shields.io/badge/TypeScript-5.6-3178C6?style=for-the-badge&logo=typescript&logoColor=white" />
  <img src="https://img.shields.io/badge/ECharts-5.5-AA344D?style=for-the-badge&logo=apacheecharts&logoColor=white" />
  <img src="https://img.shields.io/badge/Tailwind-3-06B6D4?style=for-the-badge&logo=tailwindcss&logoColor=white" />
  <img src="https://img.shields.io/badge/Qwen-Plus-FF6A00?style=for-the-badge&logo=openai&logoColor=white" />
  <img src="https://img.shields.io/badge/SQLite-3-003B57?style=for-the-badge&logo=sqlite&logoColor=white" />
</p>

<p align="center">
  <b>风电设备健康管理 · 故障智能诊断 · 预测性维护 · 知识图谱 · 多Agent协作</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-2.0-blue" />
  <img src="https://img.shields.io/badge/status-active-success" />
  <img src="https://img.shields.io/badge/license-Educational-lightgrey" />
  <img src="https://img.shields.io/badge/commits-80+-brightgreen" />
</p>

---

## 📋 项目简介

**风调预顺**是面向风电行业的**预测性健康管理 (Prognostics and Health Management)** 平台，为陕西省风场提供从实时监控、故障诊断、预测维护到工单管理的全链路智能化运维方案。

### 🎯 核心能力

| 模块 | 能力 | 亮点 |
|------|------|------|
| 🗺️ **风场监控** | 30台风机实时地图 | ECharts 可视化 + SCADA 实时数据 |
| 🔍 **故障诊断** | 自动故障检测 + 批量检测 | 实时诊断工作台 + 振动频谱分析 |
| 📈 **预测决策** | RUL 剩余寿命 + 成本对比 | 维修时机优化 + 经济效益分析 |
| 📋 **工单管理** | 全生命周期流转 | 邮件通知 + 人员指派 + 优先级管理 |
| 📚 **故障百科** | 21种故障知识节点 | 9大分类 + 知识图谱可视化 + Demo模式 |
| 🤖 **AI 助手** | Copilot 悬浮对话 | Qwen多模型 + 截图识图 + 预设提示词 |
| 🧠 **多Agent诊断** | 智能调度诊断 | Orchestrator → Data + Knowledge → Synthesizer |
| 🌱 **知识自增长** | 对话→知识自动提取 | QualityGate → Extract → Dedup → Ingest |
| ⚙️ **系统管理** | 阈值/数据源/人员/密钥 | 个人AI模型配置 + API密钥管理 |

---

## 📊 开发进度

```
████████████████████░░  85%  v2.0 — AI Agent + 知识图谱
```

| 模块 | 进度 | 状态 |
|------|:--:|:--:|
| 认证系统 (JWT) | ██████████ | ✅ 完成 |
| 风机管理 (30台+SCADA) | ██████████ | ✅ 完成 |
| 故障诊断 (自动+批量) | ██████████ | ✅ 完成 |
| 预测决策 (RUL+成本) | ██████████ | ✅ 完成 |
| 工单管理 (全生命周期) | ██████████ | ✅ 完成 |
| AI 助手 (Copilot) | ██████████ | ✅ 完成 |
| **故障百科 (21节点+图谱)** | ██████████ | ✅ 完成 |
| **多Agent诊断架构** | █████████░ | ✅ 后端完成 |
| **知识自增长 Pipeline** | █████████░ | ✅ 后端完成 |
| **API Key 全链路贯通** | ██████████ | ✅ 完成 |
| 部署上线 (阿里云) | ██████░░░░ | 📝 方案就绪 |
| 移动端适配 | ███░░░░░░░ | 🔜 计划中 |

---

## 🏗️ 技术架构

```
┌──────────────────────────────────────────────────────────────────┐
│                        🌐 Nginx 反向代理                          │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────────────┐  ┌────────────────────────────┐ │
│  │     🖥️ 前端 (React 18)       │  │   ⚡ 后端 (FastAPI)         │ │
│  │                             │  │                            │ │
│  │  📄 7 个页面               │  │  📡 10 个 API 模块         │ │
│  │  🧩 20+ 组件               │  │  🗄️ 12 个数据表            │ │
│  │  🎨 Tailwind + ECharts     │  │  🔐 JWT 鉴权              │ │
│  │  📚 知识图谱 (Force Graph)  │  │  🤖 4 Agent 协作           │ │
│  │  🤖 CopilotFAB (可拖动)    │  │  📊 数据管道 (SCADA/气象)  │ │
│  │                             │  │                            │ │
│  └──────────────┬──────────────┘  └─────────────┬──────────────┘ │
│                 │                               │                 │
│                 └───────────┬───────────────────┘                 │
│                             │                                     │
│  ┌──────────────────────────▼──────────────────────────────────┐ │
│  │                      🗄️ 数据层                               │ │
│  │  SQLite (开发) / PostgreSQL (生产) / Redis (缓存·可选)       │ │
│  │  AI: Qwen (百炼) / OpenAI / Ollama 本地                      │ │
│  └─────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

---

## 🧠 AI 智能体架构 (v2.0 新增)

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

## 🚀 快速开始

### 前置要求

- **Python 3.10+** (推荐 conda 环境)
- **Node.js 18+**
- (可选) 阿里百炼 API Key → [免费申请](https://dashscope.aliyun.com/)

### 3 分钟启动

```bash
# 1. 后端
cd backend
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
python -m scripts.seed_data          # 初始化数据库 + 21个知识节点
python -m app.main                    # 启动 → http://localhost:8000

# 2. 前端 (新终端)
cd frontend
npm install
npm run dev                           # 启动 → http://localhost:5173

# 3. 打开浏览器 → http://localhost:5173
#    登录: admin / admin123
```

---

## 📁 项目结构

```
feng/
├── backend/
│   ├── app/
│   │   ├── api/                     # 10 个 API 模块
│   │   │   ├── auth.py              # 认证 (register/login/me)
│   │   │   ├── turbines.py          # 风机管理
│   │   │   ├── diagnosis.py         # 故障诊断 + 实时诊断工作台
│   │   │   ├── prediction.py        # RUL 预测 + 成本对比
│   │   │   ├── workorders.py        # 工单生命周期 + 邮件通知
│   │   │   ├── settings.py          # 系统设置 + 阈值/数据源
│   │   │   ├── ai.py                # AI 服务 (summary/analyze/copilot)
│   │   │   ├── personnel.py         # 人员管理
│   │   │   ├── knowledge.py         # 🆕 故障百科 CRUD + 图谱数据
│   │   │   └── agent.py             # 🆕 多 Agent 诊断
│   │   ├── models/__init__.py       # 12 个数据模型 (含 FaultKnowledgeNode)
│   │   ├── schemas/__init__.py      # Pydantic 模式定义
│   │   ├── services/
│   │   │   ├── agents/              # 🆕 4 Agent 实现
│   │   │   │   ├── orchestrator.py  # 调度器
│   │   │   │   ├── data_agent.py    # 数据查询
│   │   │   │   ├── knowledge_agent.py # 知识检索
│   │   │   │   └── synthesizer.py   # 汇总输出
│   │   │   ├── knowledge_extractor.py # 🆕 对话→知识提取
│   │   │   ├── diagnosis_orchestrator.py
│   │   │   ├── qwen_client.py       # Qwen/OpenAI 客户端
│   │   │   ├── email_service.py     # 邮件服务
│   │   │   └── data_pipeline/       # 数据管道 (SCADA/气象/地理)
│   │   ├── core/security.py         # JWT + 密码哈希
│   │   ├── config.py                # 配置管理
│   │   ├── database.py              # SQLite/PostgreSQL + 离线DB
│   │   └── main.py                  # FastAPI 入口
│   ├── scripts/                     # 9 个数据处理脚本
│   ├── tests/
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Dashboard/           # 风场监控
│   │   │   ├── Diagnosis/           # 故障诊断
│   │   │   ├── Prediction/          # 预测决策
│   │   │   ├── WorkOrder/           # 工单管理
│   │   │   ├── Knowledge/           # 🆕 故障百科 + 知识图谱
│   │   │   ├── Settings/            # 系统设置
│   │   │   ├── TurbineDetail/       # 风机详情
│   │   │   └── Login/               # 登录
│   │   ├── components/
│   │   │   ├── AIAssistant/         # CopilotFAB + AIPanel
│   │   │   ├── Layout/              # AppLayout (侧边栏)
│   │   │   └── Map/                 # 风机地图
│   │   ├── data/fault-kb.json       # 🆕 21 故障节点预设数据
│   │   ├── services/
│   │   └── types/
│   ├── package.json
│   └── vite.config.ts
├── docs/superpowers/specs/          # 设计文档
│   ├── 2026-06-11-ai-agent-operation-engine-design.md
│   ├── 2026-06-11-fault-knowledge-graph-design.md
│   ├── 2026-06-11-feature-brainstorm.md
│   ├── 2026-06-12-knowledge-self-growth-design.md
│   └── deployment-guide.md          # 🆕 阿里云部署指南
├── .env.example
└── README.md
```

---

## 📡 API 端点

| 端点 | 方法 | 说明 | 鉴权 |
|------|------|------|:--:|
| `/api/auth/register` | POST | 用户注册 | - |
| `/api/auth/login` | POST | 用户登录 → 返回 JWT | - |
| `/api/auth/me` | GET | 当前用户信息 | 🔐 |
| `/api/turbines/` | GET | 风机列表 + 统计 | 🔐 |
| `/api/turbines/{id}` | GET | 风机详情 + SCADA | 🔐 |
| `/api/diagnosis/faults` | GET | 故障列表 | 🔐 |
| `/api/diagnosis/auto-fault-detection` | POST | 🆕 自动故障检测 | 🔐 |
| `/api/prediction/rul` | GET | RUL 预测 | 🔐 |
| `/api/prediction/cost-comparison` | POST | 维修成本对比 | 🔐 |
| `/api/workorders/` | GET/POST | 工单列表 + 创建 | 🔐 |
| `/api/workorders/{id}` | PUT/DELETE | 工单更新/删除 | 🔐 |
| `/api/workorders/{id}/send-email` | POST | 发送工单邮件 | 🔐 |
| `/api/knowledge-base` | GET | 🆕 故障知识列表 | 🔐 |
| `/api/knowledge-base/search?q=` | GET | 🆕 知识搜索 | 🔐 |
| `/api/knowledge-base/{id}` | GET | 🆕 故障详情 | 🔐 |
| `/api/knowledge-graph` | GET | 🆕 图谱数据 (节点+边) | 🔐 |
| `/api/knowledge-base/{id}/verify` | PATCH | 🆕 确认AI提取 | 🔐 |
| `/api/agent/diagnose` | POST | 🆕 多Agent诊断 | 🔐 |
| `/api/ai/summary` | POST | AI 页面总结 | 🔐 |
| `/api/ai/analyze-fault` | POST | AI 故障分析 | 🔐 |
| `/api/ai/copilot` | POST | AI 对话 + 知识提取 | 🔐 |
| `/api/personnel/` | GET/POST | 人员管理 | 🔐 |
| `/api/settings/` | GET/PUT | 系统设置 | 🔐 |

---

## 🚀 生产部署

详见 [`docs/superpowers/specs/deployment-guide.md`](docs/superpowers/specs/deployment-guide.md)

```
阿里云 ECS 轻量服务器 → Nginx → 前端 dist/ + 后端 uvicorn → SQLite
月费: ~¥230-300
```

---

## 📈 版本历史

### v2.0 (2026-06-12) 🆕
- ✅ **故障百科**: 21 节点知识图谱 + 9 大分类
- ✅ **多 Agent 诊断**: Orchestrator → Data + Knowledge → Synthesizer
- ✅ **知识自增长**: Copilot 对话 → LLM 提取 → 自动入库
- ✅ **API Key 全链路贯通**: 用户密钥 → 所有 LLM 调用
- ✅ **Demo 模式**: 知识图谱示例开关
- ✅ **部署方案**: 阿里云完整部署指南

### v1.5 (2026-06-11)
- ✅ 实时诊断工作台 (diagnosis_orchestrator)
- ✅ AI 助手预设定 + 可拖动 + 截图识图
- ✅ 工单邮件通知 + 优化
- ✅ 离线数据库支持 + manage_db 工具
- ✅ 文档整理 + 分支管理规范化

### v1.0 (2026-05)
- 🎉 初始版本: 8 个核心模块 + AI 助手 + 数据管道

---

## 🤝 分支管理规范

```
master    ← 纯代码 (不含文档)
dev       ← 完整项目 (代码 + 文档 + 报告)
chenxi    ← 技术负责人工作分支
feature/* ← 各成员功能分支
```

- 每人从 `dev` 拉取最新代码创建功能分支
- 开发完成后提交 → 由技术负责人审核合并
- 合并到 `dev` → 验证 → 推送 `master` (纯代码)

---

## 📄 许可证

本项目为**西北工业大学软件架构设计课程**项目，仅供学习和研究使用。

---

<p align="center">
  <b>🌪️ 风调预顺 — 预知风云变幻，守护每一度清洁能源</b><br/>
  <sub>西北工业大学 · 第十五组 · 2026</sub>
</p>
