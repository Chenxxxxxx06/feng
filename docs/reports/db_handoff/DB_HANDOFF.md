# 数据库人员交接说明

## 交接目标

本交接包用于将风调雨顺 PHM 项目当前真实数据集、数据库入库状态、数据边界和后续数据库管理要求交给数据库负责人员。当前交接重点是 CARE to Compare v6 SCADA 主时间线，以及已经整理出的振动、图像数据处理清单。

## 当前数据库文件

数据库文件：

`database/fengdiao_phm.db`

数据库类型：

SQLite，本地开发库。

当前 CARE 主数据集已完成全量入库：

| 项目 | 数值 |
|---|---:|
| 数据集 | CARE to Compare v6 SCADA |
| 入库批次 ID | 2 |
| 事件文件数 | 95 |
| 入库 SCADA 记录数 | 5,242,948 |
| 跳过行数 | 0 |
| 匿名资产数 | 36 |
| 时间范围 | 2022-01-01 至 2024-02-06 |

## 关键数据边界

CARE 是匿名公开 SCADA 数据集，不能被还原为真实风场台账。

不得补造以下字段：

- 真实经纬度
- 真实风机型号
- 真实额定功率
- 真实工单
- 真实维护成本
- 真实库存
- 真实人员排班

当前 CARE 资产采用匿名资产模式：

| 字段 | 规则 |
|---|---|
| `source_dataset` | `care_to_compare_v6` |
| `source_asset_id` | `<wind_farm>:<source_turbine_id>` |
| `asset_scope` | `anonymous_public_dataset` |
| `geo_scope` | `anonymous_unlocated` |
| `model` | 空 |
| `power_mw` | 空 |
| `lat` / `lng` | 空 |

## 当前重点数据表

| 表名 | 用途 | 当前状态 |
|---|---|---|
| `turbines` | 风机/匿名资产台账 | 包含 36 个 CARE 匿名资产 |
| `scada_records` | SCADA 时间序列 | 包含 5,242,948 条 CARE SCADA 记录 |
| `data_sources` | 数据源状态 | CARE SCADA 状态为 connected |
| `data_import_batches` | 入库批次日志 | 记录 CARE 全量入库批次 |

## 已整理数据集状态

| 数据集 | 当前状态 | 规模 | 用途 |
|---|---|---:|---|
| CARE to Compare v6 SCADA | 已规范化、已全量入库 | 95 个事件文件；5,242,948 条 SCADA | SCADA 指标、HI/RUL 输入、数据质量 |
| NREL GRC Gearbox Vibration | 已整理特征 | 20 个 MAT 样本 | 齿轮箱振动诊断样本 |
| Mendeley Blade Fault Vibration | 已整理特征 | 35 个 CSV/XLSX 样本 | 叶片振动诊断样本 |
| YOLO Wind Turbine Surface Damage | 已统计质量和标签 | 13,470 张图；2,995 个标签文件 | 叶片损伤图像样本 |
| DTU Drone Inspection Images | 已统计质量 | 701 张原始图像 | 巡检图像展示 |
| ERA5 / 现场气象 | 未接入 | 无 | 后续环境数据 |
| 工单/成本/库存/人员 | 缺失 | 无 | 需系统真实积累或用户导入 |

## 交接包内容

本交接包为数据库交接核心包，不重复打包 42GB 以上的原始图像和原始压缩数据。原始数据仍保留在项目本机目录中，并由报告记录来源与处理结果。

包内目录：

| 目录 | 内容 |
|---|---|
| `database/` | 当前 SQLite 数据库文件 |
| `datasets/care_to_compare_v6_normalized/` | CARE 规范化事件级 SCADA CSV，可用于重建入库 |
| `datasets/processed_features/` | 振动特征、图像质量、CARE 字段映射和 manifest |
| `reports/` | 数据覆盖、入库批次、文件结果、schema 升级报告 |
| `scripts/` | SQLite 升级、CARE 批量导入、覆盖评估脚本 |
| `DB_HANDOFF.md` | 本交接说明 |

原始全量数据本机路径：

| 数据 | 本机路径 | 规模 |
|---|---|---:|
| 整理后的原始数据 | `backend/data/curated_datasets` | 约 42.61 GiB |
| CARE 规范化数据 | `backend/data/modeling` | 约 0.97 GiB |
| 已入库 SQLite | `backend/fengdiao_phm.db` | 约 5.32 GiB |

## 复核命令

在项目根目录执行：

```powershell
python backend\scripts\import_care_normalized_batch.py --dry-run
```

该命令只读检查 CARE 规范化文件，不写数据库。

检查数据库中 CARE 入库结果：

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

预期结果：

| 查询 | 预期值 |
|---|---:|
| CARE 匿名资产数 | 36 |
| CARE SCADA 记录数 | 5,242,948 |
| 最新批次状态 | completed |
| 导入文件数 | 95 |
| 跳过行数 | 0 |

## 重新导入流程

如果需要在新库中重建 CARE 主时间线：

1. 先升级 SQLite schema：

```powershell
python backend\scripts\upgrade_sqlite_for_anonymous_assets.py --db-path backend\fengdiao_phm.db
```

2. 预检规范化文件：

```powershell
python backend\scripts\import_care_normalized_batch.py --dry-run
```

3. 执行全量导入：

```powershell
python backend\scripts\import_care_normalized_batch.py --replace-dataset --commit-rows 50000
```

## 后续数据库工作建议

建议新增派生指标表，避免直接覆盖原始 SCADA：

| 建议表名 | 用途 |
|---|---|
| `scada_quality_metrics` | 时间戳有效率、字段完整率、异常值比例 |
| `scada_operation_metrics` | 功率、风速、温度、转速、状态窗口等运行指标 |
| `health_index_scores` | HI 总分与分项得分 |
| `rul_risk_windows` | RUL 风险趋势、事件前窗口、解释字段 |
| `diagnosis_feature_samples` | 振动和图像诊断样本特征索引 |

所有派生表必须保留以下溯源字段：

- `source_dataset`
- `source_asset_id`
- `import_batch_id`
- `field_mapping_version`
- `source_file` 或 `source_window`
- `computed_at`
- `algorithm_version`

## 风险提示

1. CARE、NREL、Mendeley、YOLO、DTU 不是同一台风机、同一时间、同一故障链路，不能强行合并成同一资产历史。
2. 地图、机型、额定功率、维护成本、工单闭环等业务字段仍缺真实来源。
3. 图像和振动数据可以服务诊断演示与算法样本库，但不能直接证明 CARE 匿名资产的具体故障。
4. 后续若迁移到 PostgreSQL，应先导入 `turbines` 匿名资产，再分批导入 `scada_records`，最后导入批次日志和数据源状态。
