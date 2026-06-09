# 风调预顺 — PHM预测性运维系统

> 风电设备健康管理与预测性维护平台

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green.svg)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18-61DAFB.svg)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.6-3178C6.svg)](https://www.typescriptlang.org/)

---

## 📋 项目简介

风调预顺是一个面向风电行业的**预测性健康管理(PHM)**系统，集成了风场监控、故障诊断、预测性维护和工单管理等核心功能。

### 核心特性

- 🗺️ **风场地图监控** - 陕西省风场可视化，实时风机状态展示
- 🔍 **智能故障诊断** - CV叶片检测、振动分析、故障根因分析
- 📈 **预测性维护** - RUL剩余寿命预测、维护成本对比
- 📋 **工单管理** - 全生命周期工单流转、邮件通知
- 🤖 **AI助手** - Copilot悬浮窗、智能问答、页面感知
- ⚙️ **系统管理** - 阈值配置、数据管道、人员管理

---

## 🏗️ 技术架构

```
┌─────────────────────────────────────────────────────────┐
│                      前端 (React)                        │
│  React 18 + TypeScript + Vite + TailwindCSS + ECharts   │
├─────────────────────────────────────────────────────────┤
│                    后端 (FastAPI)                         │
│  Python 3.10+ + SQLAlchemy + Pydantic + JWT Auth        │
├─────────────────────────────────────────────────────────┤
│                    数据层                                 │
│  PostgreSQL/SQLite + Redis (可选) + Milvus (可选)        │
└─────────────────────────────────────────────────────────┘
```

---

## 🚀 快速开始

### 前置要求

- Python 3.10+
- Node.js 18+
- npm 或 yarn

### 1. 克隆项目

```bash
git clone <repository-url>
cd fengdiao-pHM
```

### 2. 配置环境变量

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑 .env 文件，填入真实配置
# 至少需要配置 DASHSCOPE_API_KEY（AI功能）
```

### 3. 启动后端

```bash
cd backend

# 创建虚拟环境（推荐）
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或
venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 启动服务
python -m app.main
# 或
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

后端服务将运行在 http://localhost:8000

- API文档: http://localhost:8000/api/docs
- ReDoc: http://localhost:8000/api/redoc

### 4. 启动前端

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

前端应用将运行在 http://localhost:5173

### 5. 访问系统

1. 打开 http://localhost:5173
2. 注册新账号或使用默认账号登录
3. 开始使用系统

---

## 📁 项目结构

```
fengdiao-pHM/
├── backend/                    # 后端服务
│   ├── app/
│   │   ├── api/               # API路由
│   │   │   ├── auth.py        # 认证管理
│   │   │   ├── turbines.py    # 风机管理
│   │   │   ├── diagnosis.py   # 故障诊断
│   │   │   ├── prediction.py  # 预测决策
│   │   │   ├── workorders.py  # 工单管理
│   │   │   ├── settings.py    # 系统设置
│   │   │   ├── ai.py          # AI服务
│   │   │   └── personnel.py   # 人员管理
│   │   ├── core/              # 核心模块
│   │   │   └── security.py    # 安全认证
│   │   ├── models/            # 数据模型
│   │   ├── schemas/           # Pydantic模式
│   │   ├── services/          # 业务服务
│   │   │   ├── data_pipeline/ # 数据管道
│   │   │   ├── health_index.py# 健康指数
│   │   │   └── qwen_client.py # AI客户端
│   │   ├── config.py          # 配置管理
│   │   ├── database.py        # 数据库连接
│   │   └── main.py            # 应用入口
│   ├── data/                  # 数据文件
│   ├── scripts/               # 工具脚本
│   ├── tests/                 # 测试文件
│   └── requirements.txt       # Python依赖
├── frontend/                   # 前端应用
│   ├── src/
│   │   ├── components/        # 组件
│   │   │   ├── AIAssistant/   # AI助手组件
│   │   │   ├── Common/        # 通用组件
│   │   │   ├── Layout/        # 布局组件
│   │   │   └── Map/           # 地图组件
│   │   ├── pages/             # 页面
│   │   │   ├── Dashboard/     # 风场监控
│   │   │   ├── Diagnosis/     # 故障诊断
│   │   │   ├── Prediction/    # 预测决策
│   │   │   ├── WorkOrder/     # 工单管理
│   │   │   ├── Settings/      # 系统设置
│   │   │   └── TurbineDetail/ # 风机详情
│   │   ├── services/          # 服务
│   │   ├── styles/            # 样式
│   │   └── types/             # 类型定义
│   ├── package.json
│   └── vite.config.ts
├── .env.example                # 环境变量模板
├── .gitignore                  # Git忽略配置
└── README.md                   # 项目说明
```

---

## 🔧 配置说明

### 环境变量

| 变量名 | 说明 | 必填 | 默认值 |
|--------|------|------|--------|
| `APP_NAME` | 应用名称 | 否 | 风调预顺 - PHM预测性运维系统 |
| `DEBUG` | 调试模式 | 否 | false |
| `SECRET_KEY` | JWT密钥 | 是 | - |
| `DATABASE_URL` | 数据库连接 | 否 | sqlite+aiosqlite:///./fengdiao_phm.db |
| `DASHSCOPE_API_KEY` | 阿里百炼API密钥 | 否 | - |
| `OPENAI_API_KEY` | OpenAI API密钥 | 否 | - |

### 数据库配置

**SQLite (开发环境)**
```env
DATABASE_URL=sqlite+aiosqlite:///./fengdiao_phm.db
```

**PostgreSQL (生产环境)**
```env
DATABASE_URL=postgresql+asyncpg://username:password@localhost:5432/fengdiao_phm
```

---

## 📊 API文档

启动后端服务后，访问以下地址查看API文档：

- **Swagger UI**: http://localhost:8000/api/docs
- **ReDoc**: http://localhost:8000/api/redoc

### 主要API端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/auth/register` | POST | 用户注册 |
| `/api/auth/login` | POST | 用户登录 |
| `/api/turbines/` | GET | 获取风机列表 |
| `/api/turbines/{id}` | GET | 获取风机详情 |
| `/api/diagnosis/faults` | GET | 获取故障列表 |
| `/api/prediction/rul` | GET | 获取RUL预测 |
| `/api/workorders/` | GET/POST | 工单管理 |
| `/api/ai/summary` | POST | AI页面总结 |
| `/api/ai/copilot` | POST | AI对话 |
| `/api/personnel/` | GET | 人员列表 |

---

## 🧪 测试

```bash
cd backend

# 运行测试
pytest

# 运行测试并生成覆盖率报告
pytest --cov=app --cov-report=html
```

---

## 🚀 部署

### Docker部署 (推荐)

```bash
# 构建镜像
docker build -t fengdiao-phm .

# 运行容器
docker run -d -p 8000:8000 --env-file .env fengdiao-phm
```

### 手动部署

1. 配置Nginx反向代理
2. 使用Gunicorn运行后端
3. 构建前端并部署到静态文件服务器

---

## 📈 版本历史

### v2.0 (2026-05-29)
- ✅ 修复安全性问题（移除硬编码密钥）
- ✅ 补全缺失API端点（人员管理、AI分析）
- ✅ 改善代码规范和文档
- ✅ 添加.env.example配置模板
- ✅ 优化数据库配置

### v1.0 (2026-05-01)
- 🎉 初始版本发布
- ✅ 核心功能实现

---

## 🤝 贡献指南

1. Fork 项目
2. 创建功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 创建 Pull Request

---

## 📄 许可证

本项目仅供学习和研究使用。

---

## 📞 联系方式

如有问题，请通过以下方式联系：

- 项目Issues: [GitHub Issues](链接)
- 邮箱: your-email@example.com

---

> **风调预顺** — 让风电运维更智能、更高效
