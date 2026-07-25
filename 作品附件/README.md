# 作品附件 — 风调预顺 WindOps ProofLoop

> GOAI 无界应用赛道 · AI+工业制造 · 初赛提交包  
> 西北工业大学 · 软件架构设计 · 第十五组

---

## 包含内容

| 文件/目录 | 说明 |
|-----------|------|
| `backend/` | 后端源代码（FastAPI + Python 3.11） |
| `frontend/` | 前端源代码（React 18 + TypeScript） |
| `.env.example` | 环境变量配置模板 |
| `requirements.txt` | Python 依赖清单（backend目录下） |
| `launcher.py` | 便携版启动器（backend目录下） |
| `启动风调预顺.bat` | Windows 一键启动脚本 |
| `Demo视频录制指导手册.md` | Demo视频录制完整指导 |
| `COMPETITION_GOAL.md` | 比赛执行状态记录 |
| `LICENSE` | Apache 2.0 开源协议 |
| `NOTICE` / `THIRD_PARTY_NOTICES.md` | 第三方依赖声明 |

## 不包含内容

- 数据库文件（*.db）— 太大，运行 `seed_data.py` 自动生成
- 模型权重（*.pt）— YOLOv8需要单独下载
- node_modules / dist — 前端需要 `npm install && npm run build`
- 大型数据文件（SCADA CSV、ERA5 NC、叶片图像等）— 需单独配置

## 快速启动

```bash
# 后端
cd backend
pip install -r requirements.txt
python -m scripts.seed_data
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 前端
cd frontend
npm install && npm run build

# 访问 http://127.0.0.1:8000
# 登录: admin / admin123
```
