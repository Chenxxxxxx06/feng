# 风调预顺 PHM 项目 AI 交接文档

更新时间：2026-06-12  
项目根目录：`C:\Users\ASUS\Desktop\fengdiao-pHM`  
当前分支：`dev`  
远程仓库：`git@codehub.devcloud.cn-north-4.huaweicloud.com:f01a951229ef4c2eb12b24d15fd819db/feng.git`

## 1. 交接目标

本文档用于让下一位 AI 或开发者完整接手当前风电 PHM 项目。接手者应优先阅读本文档，再查看既有文档、数据库交接包和代码。

当前项目已经从早期 demo 逐步迁移到公开真实数据集驱动。核心原则是：公开数据集和真实现场数据边界必须说清楚，不能把不同来源的数据伪造成同一台风机的完整真实历史。

## 2. 当前项目状态

项目是一个前后端分离的风电机组预测性运维系统，主要页面包括：

- 风场监控总览
- 单机详情
- 故障诊断
- 预测决策
- 维修工单
- 故障百科
- 系统设置
- AI 助手

当前本机服务状态：

| 服务 | 地址 | 进程 |
|---|---|---|
| 后端 FastAPI | `http://127.0.0.1:8000` | `python.exe` |
| 前端 Vite | `http://127.0.0.1:5173` | `node.exe` |

当前数据库文件：

`C:\Users\ASUS\Desktop\fengdiao-pHM\backend\fengdiao_phm.db`

当前数据库规模：

| 表/范围 | 数量 |
|---|---:|
| `turbines` | 66 |
| `scada_records` | 5,247,268 |
| `vibration_data` | 36 |
| `blade_images` | 0 |
| `faults` | 8 |
| `work_orders` | 8 |
| `data_sources` | 5 |
| `data_import_batches` | 2 |
| CARE 风机资产 | 36 |
| CARE SCADA 记录 | 5,242,948 |

注意：当前工作区存在未提交修改。不要随意 `git reset --hard` 或覆盖用户本地改动。

未提交文件：

```text
backend/app/api/diagnosis.py
backend/scripts/align_care_asset_registry.py
frontend/src/components/Map/TurbineMap.tsx
frontend/src/styles/global.css
frontend/src/types/index.ts
frontend/vite.config.ts
docs/AI_PROJECT_HANDOFF_20260612.md
```

## 3. 技术栈

后端：

- Python
- FastAPI
- SQLAlchemy
- SQLite
- pandas / numpy / scipy
- httpx
- Open-Meteo API

前端：

- React
- TypeScript
- Vite
- Leaflet
- ECharts
- Tailwind CSS
- Axios

主要依赖文件：

| 文件 | 作用 |
|---|---|
| `backend\requirements.txt` | 后端 Python 依赖 |
| `frontend\package.json` | 前端依赖和脚本 |
| `.env.example` | 环境变量模板 |
| `.env` | 当前本地环境配置 |
| `backend\.env` | 后端本地环境配置 |

## 4. 关键路径总览

### 4.1 项目和文档

| 路径 | 说明 |
|---|---|
| `C:\Users\ASUS\Desktop\fengdiao-pHM` | 当前项目根目录 |
| `README.md` | 项目说明 |
| `docs\PROJECT_HANDOFF.md` | 旧版项目交接文档 |
| `docs\AI_PROJECT_HANDOFF_20260612.md` | 本交接文档 |
| `handoff_packages\fengdiao_dataset_db_handoff_20260611\DB_HANDOFF.md` | 数据库交接说明 |
| `reports\data_processing` | 数据处理日志和报告 |

### 4.2 后端核心代码

| 路径 | 说明 |
|---|---|
| `backend\app\main.py` | FastAPI 入口和路由注册 |
| `backend\app\config.py` | 配置加载、离线数据库检测 |
| `backend\app\database.py` | SQLAlchemy engine/session |
| `backend\app\models\__init__.py` | 数据库模型 |
| `backend\app\schemas\__init__.py` | API schema |
| `backend\app\api\turbines.py` | 风机、SCADA、健康度、天气接口 |
| `backend\app\api\diagnosis.py` | 故障、振动、叶片图像接口 |
| `backend\app\api\prediction.py` | RUL 和成本比较接口 |
| `backend\app\api\workorders.py` | 工单接口 |
| `backend\app\api\knowledge.py` | 故障百科接口 |
| `backend\app\api\settings.py` | 设置和数据源状态接口 |
| `backend\app\services\data_pipeline\open_meteo_loader.py` | Open-Meteo 当前天气接入 |

### 4.3 前端核心代码

| 路径 | 说明 |
|---|---|
| `frontend\src\pages\Dashboard\DashboardPage.tsx` | 风场监控首页 |
| `frontend\src\components\Map\TurbineMap.tsx` | 风场地图、风场聚合图标、风机图标 |
| `frontend\src\pages\TurbineDetail\TurbineDetailPage.tsx` | 单机详情 |
| `frontend\src\pages\Diagnosis\DiagnosisPage.tsx` | 故障诊断 |
| `frontend\src\pages\Prediction\PredictionPage.tsx` | 预测决策 |
| `frontend\src\pages\WorkOrder\WorkOrderPage.tsx` | 工单管理 |
| `frontend\src\pages\Knowledge\KnowledgeBasePage.tsx` | 故障百科 |
| `frontend\src\pages\Settings\SettingsPage.tsx` | 系统设置 |
| `frontend\src\services\api.ts` | Axios 实例和登录态拦截 |
| `frontend\src\types\index.ts` | 前端类型定义 |
| `frontend\src\styles\global.css` | 全局样式、地图图标样式 |
| `frontend\vite.config.ts` | Vite 配置和 `/api`、`/data` 代理 |

### 4.4 数据目录

| 路径 | 说明 |
|---|---|
| `backend\data` | 数据根目录 |
| `backend\data\curated_datasets` | 整理后的公开数据集 |
| `backend\data\modeling\care_to_compare_v6` | CARE 规范化建模数据 |
| `backend\data\modeling\care_to_compare_v6\normalized_events` | CARE 事件级规范化 CSV |
| `backend\data\scada\care_to_compare_v6` | CARE 原始下载和下载日志 |
| `backend\data\vibration\nrel_grc_gearbox_cm` | NREL 齿轮箱振动数据 |
| `backend\data\vibration\mendeley_blade_vibration_faults` | Mendeley 叶片振动数据 |
| `backend\data\vibration\care_reference_waveforms` | 映射到 CARE 展示资产的振动波形 JSON |
| `backend\data\blade_images` | 叶片图像数据 |
| `backend\data\geojson\shaanxi.json` | 陕西边界 GeoJSON |
| `backend\data\real_dataset_sources.json` | 真实数据源清单 |
| `backend\data\local_dataset_inventory.json` | 本地数据状态清单 |
| `backend\data\data_integration_plan.json` | 数据集成方案 |

### 4.5 重要脚本

| 路径 | 说明 |
|---|---|
| `backend\scripts\upgrade_sqlite_for_anonymous_assets.py` | 升级 SQLite schema，支持匿名公开资产字段 |
| `backend\scripts\import_care_normalized_batch.py` | 批量导入 CARE 规范化 SCADA |
| `backend\scripts\align_care_asset_registry.py` | 为 CARE 匿名资产补展示名称、机型、功率、展示坐标 |
| `backend\scripts\refresh_care_monitoring_snapshot.py` | 根据导入记录刷新监控页状态/HI 快照 |
| `backend\scripts\import_reference_vibration_for_care_assets.py` | 为 CARE 展示资产绑定公开振动参考波形 |
| `backend\scripts\curate_and_process_datasets.py` | 整理公开数据集并生成处理报告 |
| `backend\scripts\audit_dataset_coverage.py` | 审计数据覆盖和用户故事可支撑情况 |
| `backend\scripts\import_real_datasets.py` | 旧版真实数据导入入口，仍可参考 |
| `backend\scripts\seed_data.py` | 初始化账号/配置/种子数据，谨慎使用 |

## 5. 当前数据边界

### 5.1 CARE SCADA

数据集：CARE to Compare v6 SCADA  
数据集 ID：`care_to_compare_v6`  
来源：Zenodo `10.5281/zenodo.15846963`

当前状态：

- 已规范化
- 已全量入库
- 36 个匿名资产
- 95 个事件文件
- 5,242,948 条 CARE SCADA 记录
- 时间范围约为 2022-01-01 至 2024-02-06

重要边界：

- CARE 是匿名公开 SCADA 数据集。
- CARE 不提供真实风场名称、真实经纬度、真实风机型号、真实功率台账。
- 当前地图使用的是 `display_registry` 展示坐标，不是原始真实机位。
- 页面上可以展示为“榆林靖边/定边/横山风场 A/B/C 区”，但交接和技术说明中必须明确这是展示注册表。

### 5.2 风机台账

当前接口默认只查 CARE 数据集：

`GET /api/turbines/?source_dataset=care_to_compare_v6`

`backend\app\api\turbines.py` 中 `source_dataset` 默认值为 `care_to_compare_v6`。

CARE 资产字段：

| 字段 | 当前规则 |
|---|---|
| `source_dataset` | `care_to_compare_v6` |
| `source_asset_id` | `<Wind Farm>:<asset_id>` |
| `asset_scope` | `anonymous_public_dataset` |
| `geo_scope` | `display_registry` |
| `name` | `YJ-A-000`、`YD-B-013`、`YH-C-053` 等展示名 |
| `model` | 展示用机型 |
| `power_mw` | 展示用额定功率 |
| `lat` / `lng` | 展示坐标 |

展示坐标由以下脚本生成：

```powershell
cd C:\Users\ASUS\Desktop\fengdiao-pHM
& 'C:\Users\ASUS\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' backend\scripts\align_care_asset_registry.py
```

### 5.3 SCADA 页面和接口

单机 SCADA 接口：

`GET /api/turbines/{turbine_id}/scada?hours=24`

当前逻辑：

- 优先查指定小时窗口内记录。
- 如果没有实时/近期记录，则返回数据库中最新历史时间片。
- 前端不应再出现“当前公开数据集不是实时采集流……”这类小字提示。
- 温度、功率等数值已要求保留合理小数。

### 5.4 振动波形

CARE SCADA 没有振动通道。当前系统为了让每台风机诊断页可展示波形，使用真实公开振动样本作为“诊断 UI 参考波形”，由脚本映射到 CARE 展示资产。

脚本：

`backend\scripts\import_reference_vibration_for_care_assets.py`

输出目录：

`backend\data\vibration\care_reference_waveforms`

数据库表：

`vibration_data`

注意：

- `vibration_data` 表目前只有 `turbine_id`、`timestamp`、`component`、`rms`、`peak_freq_hz`、`waveform_path`。
- 该表没有 `source_dataset` 列。
- 来源信息主要在波形 JSON 文件和脚本逻辑里。
- 不要展示“导入记录标记为健康或正常样本……”等冗长标记文本。
- 故障风机的波形应异常或只展示故障前参考，不应把故障风机展示成健康基线。
- 健康度较低但非故障的风机，波形应有轻微异常，逻辑要自洽。

振动接口：

`GET /api/diagnosis/vibration?turbine_id={id}&component=blade`

当前 `backend/app/api/diagnosis.py` 已改为读取数据库记录，不再使用旧模拟波形。

### 5.5 叶片图像

当前 `blade_images` 表为 0。YOLO/DTU 图像数据已下载/整理部分，但页面还没有真实图像入库记录。

相关路径：

| 路径 | 说明 |
|---|---|
| `backend\data\blade_images\yolo_annotated_wind_turbine_surface_damage` | YOLO 风机表面损伤数据 |
| `backend\data\blade_images\dtu_drone_inspection` | DTU 巡检图像数据 |
| `backend\data\curated_datasets\raw\blade_images` | 整理后的原始图像数据 |

### 5.6 天气数据

当前采用方案 A：Open-Meteo。

代码：

`backend\app\services\data_pipeline\open_meteo_loader.py`

接口：

`GET /api/turbines/{turbine_id}/wind`

当前逻辑：

- 若风机有 `lat/lng`，调用 Open-Meteo 当前天气。
- 如果 Open-Meteo 失败且没有本地天气数据，则返回错误。
- 不采用方案 B。

## 6. 当前地图和风场监控状态

地图组件：

`frontend\src\components\Map\TurbineMap.tsx`

当前行为：

- 总览页只显示 3 个风场大图标。
- 总览页显示陕西省内 3 个蓝色虚线风场范围框。
- 点击风场图标后进入该风场详情视角。
- 进入详情后显示该风场全部风机。
- 进入详情后范围框消失。
- 用户可以拖动地图。
- 用户不能滚轮/双击/键盘/触控自由缩放。
- 点击“返回总览”回到 3 风场视角。
- 风机图标下方显示 HI 数字和风机名。
- 故障风机为红色，叶片不转动。
- 正常/预警风机叶片保持旋转。
- 风场图标颜色：有故障为红色；无故障为绿色。
- 风场圆环样式已回退为之前的简洁虚线圆环版本。

当前各风场自动缩放：

```ts
const REGION_ZOOM: Record<string, number> = {
  '榆林靖边风场A区': 14.5,
  '榆林定边风场B区': 14.2,
  '榆林横山风场C区': 14.55,
};
```

最近验证结果：

- 前端构建：`npm run build` 通过。
- C 风场 22 台风机：重叠数为 0。
- C 风场详情：蓝色范围框消失。
- 总览：A 区无故障为绿色，B/C 有故障为红色。

## 7. 本地开发启动流程

### 7.1 拉取仓库

用户明确要求“仓库只拉取 dev”。

推荐新环境流程：

```powershell
cd C:\Users\ASUS\Desktop
git clone -b dev git@codehub.devcloud.cn-north-4.huaweicloud.com:f01a951229ef4c2eb12b24d15fd819db/feng.git fengdiao-pHM
cd C:\Users\ASUS\Desktop\fengdiao-pHM
git status
```

已有仓库更新 dev：

```powershell
cd C:\Users\ASUS\Desktop\fengdiao-pHM
git fetch origin
git switch dev
git pull --ff-only origin dev
```

如果本地有未提交修改，不要直接 pull。先：

```powershell
git status --short
git diff --stat
```

再决定提交、暂存或另建目录测试。

### 7.2 后端启动

推荐使用项目虚拟环境：

```powershell
cd C:\Users\ASUS\Desktop\fengdiao-pHM\backend
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

如果 `venv` 不可用，可用系统 Python，但要确保依赖已安装。

后端地址：

`http://127.0.0.1:8000`

API 文档：

`http://127.0.0.1:8000/docs`

### 7.3 前端启动

```powershell
cd C:\Users\ASUS\Desktop\fengdiao-pHM\frontend
npm install
npm run dev
```

前端地址：

`http://127.0.0.1:5173`

Vite 代理：

- `/api` -> `http://localhost:8000`
- `/data` -> `http://localhost:8000`

可用环境变量修改代理：

```powershell
$env:VITE_API_TARGET='http://127.0.0.1:8000'
npm run dev
```

### 7.4 登录

常用本地账号通常为：

| 用户名 | 密码 |
|---|---|
| `admin` | 项目种子数据默认密码，若不确定需查 `backend/scripts/seed_data.py` 或重新初始化 |

浏览器 localStorage 中 token key：

- `token`
- `user`

## 8. 构建和验证流程

前端构建：

```powershell
cd C:\Users\ASUS\Desktop\fengdiao-pHM\frontend
npm run build
```

后端基础检查：

```powershell
cd C:\Users\ASUS\Desktop\fengdiao-pHM\backend
pytest
```

注意：当前没有每次都跑完整 pytest。接手者修改后至少跑相关模块测试或手动验证关键页面。

地图页面手动验证：

1. 打开 `http://127.0.0.1:5173/dashboard`。
2. 总览应出现 3 个风场图标。
3. 无故障风场为绿色，有故障风场为红色。
4. 点击风场 C。
5. 应显示 22 台风机。
6. 图标和名称不应遮挡。
7. 故障风机红色叶片不转动。
8. 点击风机后右侧信息面板不应被地图覆盖。

## 9. 数据重建工作流

### 9.1 重建 CARE 主时间线

如果新库需要重建 CARE：

```powershell
cd C:\Users\ASUS\Desktop\fengdiao-pHM
python backend\scripts\upgrade_sqlite_for_anonymous_assets.py --db-path backend\fengdiao_phm.db
python backend\scripts\import_care_normalized_batch.py --dry-run
python backend\scripts\import_care_normalized_batch.py --replace-dataset --commit-rows 50000
python backend\scripts\align_care_asset_registry.py
python backend\scripts\refresh_care_monitoring_snapshot.py
python backend\scripts\import_reference_vibration_for_care_assets.py
```

若使用 Codex 桌面内置 Python：

```powershell
& 'C:\Users\ASUS\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' backend\scripts\align_care_asset_registry.py
```

### 9.2 复核 CARE 入库

```sql
SELECT COUNT(*)
FROM turbines
WHERE source_dataset = 'care_to_compare_v6';

SELECT COUNT(*)
FROM scada_records
WHERE turbine_id IN (
  SELECT id FROM turbines WHERE source_dataset = 'care_to_compare_v6'
);

SELECT status, files_imported, rows_imported, rows_skipped, anonymous_assets
FROM data_import_batches
WHERE dataset_id = 'care_to_compare_v6'
ORDER BY id DESC
LIMIT 1;
```

预期：

| 查询 | 预期 |
|---|---:|
| CARE 资产数 | 36 |
| CARE SCADA | 5,242,948 |
| 最新批次状态 | `completed` |
| 导入文件数 | 95 |
| 跳过行数 | 0 |

### 9.3 振动参考波形重建

```powershell
cd C:\Users\ASUS\Desktop\fengdiao-pHM
python backend\scripts\import_reference_vibration_for_care_assets.py
```

输出：

- `backend\data\vibration\care_reference_waveforms\turbine_*.json`
- `vibration_data` 表 36 条记录

## 10. Git 工作流

当前分支：

`dev`

强制规则：

- 以后所有工作流都先从远程 `origin/dev` 拉取最新版本，再在本地修改。
- 任何 `git push`、`git push origin dev`、上传远程仓库的动作，都必须先向用户汇报本次拟上传内容，并等待用户明确确认。
- 未得到用户确认前，只允许本地 `fetch`、`pull --ff-only`、本地修改、本地构建和本地测试，不允许私自上传。

查看状态：

```powershell
cd C:\Users\ASUS\Desktop\fengdiao-pHM
git status --short
git branch --show-current
```

推荐提交：

```powershell
git add backend/app/api/diagnosis.py backend/scripts/align_care_asset_registry.py frontend/src/components/Map/TurbineMap.tsx frontend/src/styles/global.css frontend/src/types/index.ts frontend/vite.config.ts docs/AI_PROJECT_HANDOFF_20260612.md
git commit -m "feat: 完善风场监控与真实数据交接"
git push origin dev
```

如果只提交文档：

```powershell
git add docs/AI_PROJECT_HANDOFF_20260612.md
git commit -m "docs: 增加AI项目交接文档"
git push origin dev
```

不要提交：

- `backend\fengdiao_phm.db`，除非团队明确要求。
- 大型原始数据 zip。
- 本地日志、临时截图。
- `.env` 中真实密钥。

## 11. 近期重要改动清单

### 11.1 地图与风场监控

文件：

- `frontend\src\components\Map\TurbineMap.tsx`
- `frontend\src\styles\global.css`
- `backend\scripts\align_care_asset_registry.py`

当前状态：

- 总览展示 3 个风场聚合图标。
- 点击聚合图标进入风场详情。
- 地图允许拖动，不允许用户自由缩放。
- 详情视角按固定缩放展示风机，解决图标重叠。
- 风机图标显示 HI 和风机名称。
- 故障风机红色且叶片不转。
- 无故障风场图标为绿色。
- 风场圆环使用之前的简洁虚线版本。

### 11.2 SCADA 展示

文件：

- `backend\app\api\turbines.py`
- `frontend\src\pages\TurbineDetail\TurbineDetailPage.tsx`
- `frontend\src\types\index.ts`

当前状态：

- 单机详情可读取 CARE 最新历史 SCADA 时间片。
- 不再展示冗长的“公开数据集不是实时采集流”小字。
- 温度、功率等数值应保留合理小数。

### 11.3 振动波形

文件：

- `backend\app\api\diagnosis.py`
- `backend\scripts\import_reference_vibration_for_care_assets.py`
- `backend\data\vibration\care_reference_waveforms`

当前状态：

- 诊断接口读取数据库和波形 JSON。
- 36 台 CARE 展示资产都有参考振动波形。
- 故障或低健康度风机波形展示应保持异常逻辑。

### 11.4 天气

文件：

- `backend\app\services\data_pipeline\open_meteo_loader.py`
- `backend\app\api\turbines.py`

当前状态：

- 采用 Open-Meteo。
- 根据风机展示坐标获取当前天气。

### 11.5 Vite 代理

文件：

- `frontend\vite.config.ts`

当前状态：

- 默认代理后端：`http://localhost:8000`
- 支持 `VITE_API_TARGET` 覆盖。

## 12. 当前风险和注意事项

1. CARE、NREL、Mendeley、YOLO、DTU 不是同一批真实风机，不可强行拼成同一台风机的完整真实故障链。
2. CARE 原始数据匿名，不提供真实经纬度。当前地图经纬度是展示注册表坐标。
3. `vibration_data` 没有 `source_dataset` 列，不要按这个列查询。
4. `backend\fengdiao_phm.db` 很大，约 5GB 以上；拉仓库不会自动得到数据库。
5. `fengdiao_phm.db` 在项目根目录还有一个 0 字节同名文件，实际使用的是 `backend\fengdiao_phm.db`。
6. `.env.example` 提到离线数据库目录名 `fengdiao_dataset_db_handoff_20260611`，但当前实际交接包在 `handoff_packages\fengdiao_dataset_db_handoff_20260611`。如果要自动使用离线库，需要按 `backend/app/config.py` 的检测逻辑放到项目根目录同级位置。
7. 当前前端地图使用第三方瓦片，网络慢时会有加载延迟；已加 OSM fallback 和 `invalidateSize`。
8. 不要使用旧的 `backend/demo_server.py` 当真实系统。
9. 不要恢复旧模拟波形/模拟图像 fallback。
10. 修改地图时优先改显示缩放和样式，不要随意把风机坐标前端网格化。

## 13. 下一步建议

优先级从高到低：

1. 把当前未提交修改整理成一次清晰提交。
2. 复核 `backend/app/api/diagnosis.py`、`frontend/src/types/index.ts`、`frontend/vite.config.ts` 的未提交改动，确认全部符合当前需求。
3. 为 `vibration_data` 增加来源字段或新增诊断样本表，避免来源追溯只靠 JSON 文件路径。
4. 对 SCADA 单机详情增加更明确的数据时间戳展示，但不要出现冗长免责声明。
5. 将 `align_care_asset_registry.py` 的展示坐标规则写入 README 或数据说明，避免误认为真实机位。
6. 完成叶片图像入库和页面展示。
7. 为地图交互增加 Playwright/DOM 回归检查，至少覆盖：总览 3 风场、点击 C 区 22 风机、重叠为 0、故障风机停转。
8. 考虑 PostgreSQL 迁移或提供可下载数据库交接包。

## 14. 常用命令速查

进入项目：

```powershell
cd C:\Users\ASUS\Desktop\fengdiao-pHM
```

查看 Git：

```powershell
git status --short
git branch --show-current
git log --oneline -10
```

启动后端：

```powershell
cd C:\Users\ASUS\Desktop\fengdiao-pHM\backend
.\venv\Scripts\Activate.ps1
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

启动前端：

```powershell
cd C:\Users\ASUS\Desktop\fengdiao-pHM\frontend
npm run dev
```

构建前端：

```powershell
cd C:\Users\ASUS\Desktop\fengdiao-pHM\frontend
npm run build
```

写入展示坐标：

```powershell
cd C:\Users\ASUS\Desktop\fengdiao-pHM
python backend\scripts\align_care_asset_registry.py
```

导入振动参考波形：

```powershell
cd C:\Users\ASUS\Desktop\fengdiao-pHM
python backend\scripts\import_reference_vibration_for_care_assets.py
```

检查端口：

```powershell
Get-NetTCPConnection -LocalPort 8000,5173 -ErrorAction SilentlyContinue |
  Select-Object LocalAddress,LocalPort,State,OwningProcess |
  Format-Table -AutoSize
```

检查数据库核心计数：

```powershell
@'
import sqlite3
p=r"C:\Users\ASUS\Desktop\fengdiao-pHM\backend\fengdiao_phm.db"
con=sqlite3.connect(p)
for table in ["turbines","scada_records","vibration_data","blade_images","faults","work_orders","data_sources","data_import_batches"]:
    print(table, con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
print("care_turbines", con.execute("SELECT COUNT(*) FROM turbines WHERE source_dataset='care_to_compare_v6'").fetchone()[0])
print("care_scada", con.execute("SELECT COUNT(*) FROM scada_records WHERE turbine_id IN (SELECT id FROM turbines WHERE source_dataset='care_to_compare_v6')").fetchone()[0])
'@ | python -
```

## 15. 给下一位 AI 的接手提示

接手后先做四件事：

1. 读本文档。
2. 执行 `git status --short`，确认不要覆盖用户本地修改。
3. 打开 `http://127.0.0.1:5173/dashboard`，确认当前视觉状态。
4. 改代码前先读相关文件，不要凭记忆重构。

Git 协作补充：

- 默认拉取顺序：`git fetch origin` -> `git switch dev` -> `git pull --ff-only origin dev`
- 本地完成修改后，先汇报变更内容、验证结果和拟执行的 push 命令，等用户确认后再上传。

当前用户偏好：

- 希望页面美观、实用，不要过度花哨。
- 地图点位要看起来符合真实风场，不要明显像模拟网格或人工斜线。
- 需要风机名称和健康度，但不能遮挡。
- 故障风机红色，叶片不转。
- 无故障风场聚合图标用绿色。
- 交互上可以拖动地图，但不让用户自由缩放。
- 不喜欢冗长小字提示，尤其是数据免责声明类文字。
