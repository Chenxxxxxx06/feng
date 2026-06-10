# CARE 主时间线接入计划

## 当前状态

CARE to Compare v6 已完成本地整理、字段语义映射和事件级 SCADA 规范化。规范化文件位于：

`C:\Users\ASUS\Desktop\fengdiao-pHM\backend\data\modeling\care_to_compare_v6\normalized_events`

当前清单包含 95 个事件 CSV，合计 5,242,948 行。每个文件保留 `timestamp`、`source_turbine_id`、`event_id`、`event_label`、`status_type_id`、`train_test` 以及项目标准 SCADA 字段。95 个事件文件均具备风速、功率和温度类字段，可作为 SCADA 指标、HI 输入和 RUL 风险趋势窗口的主时间线。

## 事实边界

CARE 是匿名公开 SCADA 数据集。当前不能把 CARE 资产映射为真实风机坐标、真实机型、真实额定功率、真实业务工单或真实维护成本；也不能把 CARE 与 NREL、Mendeley、DTU、YOLO 样本伪造成同一台风机、同一时间、同一故障的完整证据链。

因此入库采用匿名资产模式：

- `source_dataset = care_to_compare_v6`
- `source_asset_id = <wind_farm>:<source_turbine_id>`
- `asset_scope = anonymous_public_dataset`
- `geo_scope = anonymous_unlocated`
- `model`、`power_mw`、`lat`、`lng` 保持为空

## 可执行流程

1. 升级旧 SQLite 本地库，使 `turbines` 表支持匿名公开数据资产。

```powershell
backend\venv\Scripts\python.exe backend\scripts\upgrade_sqlite_for_anonymous_assets.py
```

2. 只读预检规范化 CARE 文件。

```powershell
backend\venv\Scripts\python.exe backend\scripts\import_care_normalized_batch.py --dry-run
```

3. 执行数据库导入。全量导入会替换当前 `care_to_compare_v6` 匿名资产及其 SCADA 记录，不会影响原 demo 风机。

```powershell
backend\venv\Scripts\python.exe backend\scripts\import_care_normalized_batch.py --replace-dataset --commit-rows 50000
```

## 输出报告

- `reports/data_processing/sqlite_schema_upgrade_anonymous_assets.json`
- `reports/data_processing/care_scada_import_batch_summary.json`
- `reports/data_processing/care_scada_import_file_results.csv`
- `reports/data_processing/care_normalized_event_manifest.csv`
- `reports/data_processing/care_standard_field_mapping.csv`

## 建模使用方式

CARE 入库后优先服务以下建模内容：

- SCADA 运行指标：风速、功率、转速、温度、桨距、方向、状态窗口。
- 数据质量指标：文件可读性、字段非空率、时间戳有效率、入库行数校验、批次状态。
- HI 输入：功率偏差、温度异常、运行状态、事件窗口趋势。
- RUL 风险趋势：事件前窗口、HI 趋势、异常窗口解释。

暂不支持的内容必须保持缺失或等待真实业务数据导入：真实地理地图定位、机型筛选、额定功率归一化、工单闭环、成本决策、备件库存、人员排班、真实维护历史。
