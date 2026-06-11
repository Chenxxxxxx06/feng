# 风调雨顺 PHM 项目交接文档

更新时间：2026-06-10 12:10  
项目路径：`C:\Users\ASUS\Desktop\fengdiao-pHM`

## 1. 项目情况

本项目目标是开发一个风电机组在线健康管理与预测性运维系统，覆盖风场监控、单机状态查看、故障诊断、振动/图像诊断样本展示、剩余寿命预测、维护决策、工单管理、数据源监控和页面智能总结等功能。

当前项目是一个 demo 基础上的迭代工程，已经开始从模拟数据向真实公开数据集接入迁移。后续开发的核心原则是：不得伪造数据、图像、标签、工单、成本或诊断结论；没有真实来源的数据必须显示为缺失、下载中、待导入或待用户录入。

技术栈现状：

- 后端：FastAPI、SQLAlchemy、SQLite、本地脚本导入数据。
- 前端：React、TypeScript、Vite。
- 数据目录：`backend/data/`。
- 数据库：`backend/fengdiao_phm.db`，当前仍含旧 demo 数据，不能作为真实业务数据使用。
- Git：仓库已初始化，主分支为 `main`。

## 2. 已有内容

### 2.1 代码与功能

已具备的主要模块：

- 用户认证与基础账号逻辑。
- 风机总览、地图展示、筛选、单机详情页面。
- 诊断页面、振动数据接口、叶片图像接口。
- 预测维护页面、RUL/成本相关页面框架。
- 工单管理页面。
- 设置页：阈值配置、数据源状态、数据集成方案展示。
- AI 总结入口。

已完成的重要约束改造：

- 关闭旧的模拟数据生成逻辑。
- `backend/demo_server.py` 已禁用，不再生成假数据。
- `backend/scripts/seed_data.py` 只初始化账号和数据源状态，不再生成业务假数据。
- 诊断、SCADA、叶片图像、振动模块已改为优先读取真实导入数据；无数据时展示缺失说明，而不是 fallback 伪造。
- `backend/scripts/import_real_datasets.py` 已有真实数据导入入口：
  - `scada-csv`
  - `vibration-csv`
  - `blade-yolo`
- 已新增数据方案接口：
  - `GET /api/settings/data-integration-plan`

### 2.2 文档和清单

已有文档/清单：

- `DATA_INTEGRATION_STRATEGY.md`：数据整合原则，定义 SCADA、振动、图像、气象、业务数据的事实边界。
- `backend/data/real_dataset_sources.json`：真实数据源候选和官方来源。
- `backend/data/local_dataset_inventory.json`：本地已下载/已解压/下载中的数据状态。
- `reports/user_story_data_requirements.xlsx`：初版 14 个用户故事数据需求矩阵。
- `reports/user_story_data_requirements_updated.xlsx`：补充版，新增“数据下载清单”工作表。

### 2.3 Git 记录

关键提交包括：

- `833cca2 chore: 初始化项目 Git 仓库基线`
- `f9b3ba3 feat: 强化真实诊断数据解释链路`
- `e296e51 feat: 建立SCADA主时间线数据接入`
- `a1bc548 feat: 增加SCADA导入质量预检`
- `3974b86 feat: 调整数据集成方案并展示状态`
- `3ae7691 chore: 记录真实振动数据解压状态`
- `08ce780 docs: 增加用户故事数据需求矩阵`
- `9e8f5d0 docs: 补充数据需求与下载清单`

每次后续修改也应继续提交 Git，保持记录。

## 3. 数据情况

### 3.1 数据总原则

当前数据分为四层：

- L1 运行主线：CARE SCADA 或真实现场 SCADA。用于风机、时间线、运行状态、故障窗口、HI、RUL 入口。
- L2 诊断样本库：NREL、Mendeley、DTU、YOLO 等公开样本。用于算法演示和解释，不得声称与 CARE 是同一台风机、同一时间。
- L3 环境补充：ERA5 或现场气象。只作环境背景，不替代 SCADA 传感器。
- L4 业务沉淀：工单、成本、备件、人员、检修记录。必须由系统真实操作积累或带来源导入，不预置伪造历史。

### 3.2 当前下载与接入状态

下载进度快照如下：

| 数据集 | 作用 | 本地状态 |
|---|---|---|
| CARE to Compare v6 SCADA | SCADA 主时间线、监控、HI、故障窗口、RUL 入口 | 下载中，约 59,957,248 / 5,503,439,673 bytes，约 1.09%；未完成，不能解压或导入 |
| NREL Gearbox Vibration | 齿轮箱振动诊断样本 | 已下载并解压；20 个 `.mat` 文件 |
| Mendeley Blade Vibration | 叶片振动诊断样本 | 已下载并解压；28 个 `.csv`、7 个 `.xlsx` |
| YOLO Annotated Wind Turbine Surface Damage | 叶片图像损伤定位、YOLO 标注 | 下载中，约 1,139,171,328 / 2,756,431,451 bytes，约 41.33%；未完成 |
| DTU Drone Inspection Images | 叶片原始巡检图像与来源追溯 | 下载中，约 43,016,192 / 3,029,715,385 bytes，约 1.42%；未完成 |
| ERA5 single levels | 气象环境背景 | 暂缓下载；需真实坐标和时间范围 |
| 工单/成本/备件/人员数据 | 维护决策和业务闭环 | 缺失；应由系统操作积累或真实导入 |

### 3.3 真实来源

当前使用或计划使用的数据源：

- CARE v6 SCADA：`10.5281/zenodo.15846963`  
  页面：`https://zenodo.org/records/15846963`  
  预期文件：`CARE_To_Compare.zip`  
  预期大小：`5,503,439,673 bytes`  
  MD5：`2547b58c21ac8c242d13232860cf500c`

- NREL Gearbox Vibration：`10.25984/1844194`  
  页面：`https://data.openei.org/submissions/738`  
  本地源包：`C:\edge\738.zip`  
  解压目录：`backend/data/vibration/nrel_grc_gearbox_cm/raw`

- Mendeley Blade Vibration：`10.17632/5d7vbdp8f7.4`  
  页面：`https://data.mendeley.com/datasets/5d7vbdp8f7/4`  
  本地源包：`C:\edge\Wind_Turbine_Blades_Fault_Diagnosis_based_on_Vibration_Dataset_Analysis.zip`  
  解压目录：`backend/data/vibration/mendeley_blade_vibration_faults/raw`

- YOLO Annotated Wind Turbine Surface Damage：`10.17632/t6fwpc735s.1`  
  页面：`https://data.mendeley.com/datasets/t6fwpc735s/1`  
  下载中：`backend/data/blade_images/yolo_annotated_wind_turbine_surface_damage/t6fwpc735s-1.zip`

- DTU Drone Inspection Images：`10.17632/hd96prn3nc.2`  
  页面：`https://data.mendeley.com/datasets/hd96prn3nc/2`  
  下载中：`backend/data/blade_images/dtu_drone_inspection/hd96prn3nc-2.zip`

- ERA5：  
  页面：`https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels`  
  状态：暂缓。

### 3.4 当前数据库状态

本地 SQLite 当前仍含旧 demo 数据：

- `data_sources`: 4
- `turbines`: 30
- `scada_records`: 4320
- `vibration_data`: 0
- `blade_images`: 0
- `faults`: 8
- `work_orders`: 8

这些旧数据不能作为真实项目结果使用。后续建议使用干净数据库，或显式清理旧 demo 数据后再导入真实数据。

## 4. 目前正在做什么

当前后台下载进程：

- CARE SCADA：`zenodo_get`，进程 `py.exe` PID `198184`，子进程 `python.exe` PID `204040`。
- YOLO 叶片标注图像：`curl.exe` PID `207028`。
- DTU 原始叶片图像：`curl.exe` PID `169220`。

曾经出现过 CARE 同时由 `zenodo_get` 和 `curl` 写同一个 `CARE_To_Compare.zip` 的风险。已停止重复的 CARE `curl`，保留 `zenodo_get` 继续下载。后续不要再让两个进程同时写同一个 zip。

监控下载进度可用：

```powershell
$items=@(
  @{Name='CARE'; Path='backend\data\scada\care_to_compare_v6\CARE_To_Compare.zip'; Expected=5503439673},
  @{Name='YOLO'; Path='backend\data\blade_images\yolo_annotated_wind_turbine_surface_damage\t6fwpc735s-1.zip'; Expected=2756431451},
  @{Name='DTU'; Path='backend\data\blade_images\dtu_drone_inspection\hd96prn3nc-2.zip'; Expected=3029715385}
)
foreach($i in $items){
  $f=Get-Item -LiteralPath $i.Path -ErrorAction SilentlyContinue
  if($f){ '{0}: {1} / {2} bytes ({3}%)' -f $i.Name,$f.Length,$i.Expected,[math]::Round($f.Length/$i.Expected*100,3) }
}
```

查看后台下载进程：

```powershell
Get-Process curl,py,python -ErrorAction SilentlyContinue |
  Select-Object Id,ProcessName,StartTime,CPU,Path |
  Format-Table -AutoSize
```

## 5. 待完善内容

### 5.1 数据导入能力

当前最紧急的是增强真实诊断样本导入：

- NREL 振动数据是 `.mat` 文件，当前 `vibration-csv` 不能直接导入。
- Mendeley 叶片振动数据包括分号分隔 CSV 和 XLSX，当前读取逻辑还不够。
- 需要新增或扩展振动导入能力：
  - 支持 `.mat`。
  - 支持分号 CSV。
  - 支持 XLSX。
  - 支持从文件夹或文件名解析真实标签。
  - 支持保留源文件、通道名、采样率、样本长度、标签来源。

### 5.2 诊断样本库建模

当前数据库中的 `VibrationData` 和 `BladeImage` 都要求绑定 `turbine_id`。这对真实公开样本库不够严谨，因为 NREL、Mendeley、DTU 与 CARE 不是同一台风机。后续应考虑：

- 新增“诊断样本库”实体，允许样本不绑定运营风机。
- 或增加明确字段区分：
  - `asset_scope = sample_library`
  - `source_dataset`
  - `source_file`
  - `label_source`
  - `not_same_asset_as_care = true`

目标是页面可以展示真实诊断样本，但不把它们伪造成 CARE 风机的直接故障证据。

### 5.3 图像数据接入

YOLO 和 DTU 下载完成后应执行：

1. 校验 zip 是否完整。
2. 解压到对应 `raw` 目录。
3. 统计图片数量、标签数量、图片/标签配对率。
4. 检查类别名：YOLO 数据集说明包含 Dirt 和 Damage。
5. 用 `blade-yolo` 导入时保留：
   - 数据集 DOI
   - 图像源文件
   - YOLO 标签来源
   - bbox
   - 分辨率
6. 不生成模型置信度；人工或公开标注没有置信度。

### 5.4 CARE SCADA 接入

CARE 下载完成后应执行：

1. 校验大小和 MD5。
2. 解压 zip。
3. 检查目录结构和 CSV 文件字段。
4. 优先使用 Avg 信号，谨慎使用 Min/Max/Std。
5. 用 `scada-csv --dry-run` 做字段映射预检。
6. 确认 `ready_for_import=true` 后再正式导入。
7. 重新建立真实风机主时间线和状态，而不是使用旧 demo 风机台账。

### 5.5 HI、RUL、成本和工单

后续算法建议顺序：

1. 先做可解释 HI：
   - 功率曲线偏差
   - 温度异常
   - 转速/桨距异常
   - 数据完整性
   - 振动/图像样本分项只作为样本库演示，不强行合并到 CARE 单机证据链

2. 再做故障贡献排序：
   - 每个指标给出来源和偏离程度。
   - 不输出无证据的“根因”。

3. RUL 第一阶段只做风险趋势或演示级预测：
   - 无真实维修历史时，不能声称工业级寿命预测已验证。

4. 成本、备件、人员排班：
   - 公开数据通常不提供。
   - 应由用户录入或真实业务导入。
   - 不能预置伪造工单、成本、库存或人员排班。

## 6. 用户故事数据需求

14 个用户故事的数据需求已经整理为 Excel：

- `reports/user_story_data_requirements.xlsx`
- `reports/user_story_data_requirements_updated.xlsx`

补充版包含 4 张表：

- `用户故事数据需求`
- `数据源服务矩阵`
- `数据项字典`
- `数据下载清单`

其中 `数据下载清单` 是当前最重要的后续执行依据。

## 7. 风险和注意事项

必须遵守的约束：

- 不生成假数据。
- 不使用 AI 生成图像代替叶片巡检图像。
- 不把 NREL/Mendeley/DTU 样本说成 CARE 同一台风机的数据。
- 不把旧 demo 数据当成真实数据。
- 不提交大型真实数据文件到 Git；`backend/data/scada/`、`backend/data/vibration/`、`backend/data/blade_images/` 已在 `.gitignore` 中忽略。
- NREL 许可文件要求使用时致谢 DOE/NREL，并且数据文件不能直接再分发，应引导他人到 NREL/OEDI 获取。
- Excel 打开时会产生 `~$*.xlsx` 临时锁文件，已加入 `.gitignore`。

## 8. 建议下一步

优先级建议：

1. 等 YOLO 标注图像包下载完成，先校验和解压，因为它对“叶片图像诊断”最直接。
2. 增强 `import_real_datasets.py`，支持：
   - `.mat`
   - 分号 CSV
   - XLSX
   - 标签解析
   - 诊断样本库边界字段
3. 导入 NREL 和 Mendeley 振动样本，做真实振动波形、RMS、频谱主峰展示。
4. 导入 YOLO 图像样本，做真实图像 bbox 展示。
5. CARE 完成后再做 SCADA 主时间线、HI 和 RUL。
6. 业务数据从空状态开始，用系统工单真实积累；如用户提供真实记录，再做带来源导入。

## 9. 常用命令

启动后端：

```powershell
cd C:\Users\ASUS\Desktop\fengdiao-pHM\backend
.\venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

启动前端：

```powershell
cd C:\Users\ASUS\Desktop\fengdiao-pHM\frontend
npm run dev
```

运行后端测试：

```powershell
cd C:\Users\ASUS\Desktop\fengdiao-pHM\backend
.\venv\Scripts\python.exe -m pytest
```

前端构建：

```powershell
cd C:\Users\ASUS\Desktop\fengdiao-pHM\frontend
npm run build
```

查看 Git 状态：

```powershell
cd C:\Users\ASUS\Desktop\fengdiao-pHM
git status --short
```
