# COMPETITION_GOAL.md — 风调预顺 WindOps ProofLoop 比赛执行状态

> 北极星目标: 可验证闭环工业Agent — 无人机巡检→证据→事件→方案→审批→工单→验证→知识
> 初赛截止: 2026-08-16 | 当前日期: 2026-07-24

---

## 当前阶段: P0 闭环建设 (第1轮)

### ✅ P0 已完成

| # | 任务 | 状态 |
|---|------|:----:|
| P0-fix-1 | BladeYoloService.is_model_available() 方法 | ✅ |
| P0-fix-2 | 振动诊断验证(DFT频谱+真实DB数据) | ✅ |
| P0-1 | 巡检任务和证据资产持久化 | ✅ |
| P0-2 | 无人机结果进入事件中心 | ✅ |
| P0-3 | 动态补拍闭环(缺失角度+质量门+补拍标记) | ✅ |
| - | SCADA数据管道(5.2M条记录正常) | ✅ |
| - | Incident闭环(调查→方案→审批→执行→验证) | ✅ |
| - | 恢复验证门禁(pass/conditional/fail不能关闭) | ✅ |
| - | 审计签名链(SHA-256+Ed25519) | ✅ |
| - | 红队测试(真实行为评分) | ✅ |
| - | 测试: 130 passed, 10 skipped | ✅ |

### ✅ P0 已完成 (续)

| # | 任务 | 状态 |
|---|------|:----:|
| P0-4 | 多模态冲突感知(5维交叉对比+证据边自动生成) | ✅ |
| P0-5 | 黄金演示场景(13步确定性格子,13/13通过) | ✅ |
| - | 前端构建: 通过 | ✅ |
| - | 黄金Demo: 13/13 HTTP 200 | ✅ |

### 🔴 正在执行

| # | 任务 | 优先级 |
|---|------|:------:|
| P0-6 | 修后验证门禁完整端到端测试 | 🔴 |
| P1-1 | 证据价值航线 | 🟡 |

## 本轮新增文件

- `backend/app/api/drone.py` — 无人机巡检API (11 endpoints)
- `backend/app/services/multimodal_conflict_service.py` — 5维多模态冲突分析
- `backend/app/api/incidents.py` — 黄金Demo / 多模态冲突API
- `backend/app/models/__init__.py` — InspectionMission模型 + BladeImage扩展22列

### ⬜ 待完成

| # | 任务 | 优先级 |
|---|------|:------:|
| P0-4 | 多模态冲突感知(图像vs SCADA) | 🟡 |
| P0-5 | 黄金演示场景(确定性可重复) | 🟡 |
| P0-6 | 修后验证门禁完整测试 | 🟡 |
| P1-1 | 证据价值航线(非最短距离) | 🟢 |
| P1-2 | 预测时间表升级(RUL区间化) | 🟢 |
| P1-3 | 统一事件工作台 | 🟢 |
| P1-4 | 故障百科Playbook化 | 🟢 |
| P1-5 | 最小备件闭环(只在P0主线稳定后) | 🟢 |

---

## 已知限制

1. YOLO模型权重(DTU best.pt)依赖ultralytics环境，当前可能未安装
2. 模拟数据与真实记录需在UI明确区分(data_source标记)
3. SCADA为历史公开数据(已标记source_dataset)
4. 叶片图像数据当前为空(需demo_fixture或真实图片)
5. 无人机调度为前端3D仿真，无后端持久化

---

## 测试命令

```bash
# 后端测试
cd backend && python -m pytest tests/ -v --tb=short

# 前端构建
cd frontend && npm run build

# 启动
cd backend && python -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

## 下一步: P0-1 巡检任务持久化
