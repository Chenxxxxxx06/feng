# 数据路径清单与处理概览

## 数据总览表

| 序号 | 数据或文件夹 | 本机路径 | 交接包路径 | 数据内容 | 数据形式 | 当前处理方式 | 当前状态 | 规模 |
|---:|---|---|---|---|---|---|---|---:|
| 1 | CARE to Compare v6 原始数据 | `backend/data/curated_datasets/raw/scada/care_to_compare_v6/CARE_To_Compare` | 未重复打包，见路径说明 | 三个匿名风场的 SCADA 事件数据、`event_info.csv`、`feature_description.csv` | 分号分隔 CSV，含匿名 `asset_id`、事件窗口、传感器字段 | 已解压、识别事件文件、读取元数据、建立字段语义映射 | 已归档，保留原始形态 | 原始总目录包含在 42.61 GiB 内 |
| 2 | CARE 规范化建模数据 | `backend/data/modeling/care_to_compare_v6/normalized_events` | `datasets/care_to_compare_v6_normalized/` | 95 个事件级 SCADA 文件，统一为项目标准字段 | UTF-8 CSV，字段含 `timestamp`、`source_turbine_id`、`event_id`、`event_label`、`status_type_id`、功率、风速、温度等 | 从 CARE 原始数据按字段映射生成，未补造坐标、机型或额定功率 | 已生成、已放入交接包 | 95 文件，约 0.97 GiB |
| 3 | CARE 已入库数据库 | `backend/fengdiao_phm.db` | `database/fengdiao_phm.db` | CARE 匿名资产和 SCADA 时间序列记录 | SQLite 数据库 | 已升级 schema，按匿名资产模式批量导入 CARE 规范化数据 | 已入库，可直接交给数据库人员复核 | 5,242,948 条 SCADA；36 个匿名资产；约 5.32 GiB |
| 4 | CARE 入库批次报告 | `reports/data_processing/care_scada_import_batch_summary.json` | `reports/care_scada_import_batch_summary.json` | CARE 全量入库批次摘要 | JSON | 由批量导入脚本生成，记录文件数、行数、时间范围、质量门禁 | 已生成 | 1 份 |
| 5 | CARE 逐文件入库结果 | `reports/data_processing/care_scada_import_file_results.csv` | `reports/care_scada_import_file_results.csv` | 95 个规范化事件文件的逐文件导入结果 | CSV | 记录每个文件读取行数、入库行数、跳过行数、时间范围 | 已生成 | 95 行 |
| 6 | CARE 字段映射表 | `reports/data_processing/care_standard_field_mapping.csv` | `datasets/processed_features/care_standard_field_mapping.csv` | CARE 传感器字段到项目标准字段的映射 | CSV | 依据 CARE `feature_description.csv` 和字段语义人工审定映射 | 已生成 | 30 行 |
| 7 | CARE 事件窗口表 | `reports/data_processing/care_event_windows_normalized.csv` | `datasets/processed_features/care_event_windows_normalized.csv` | CARE 事件标签、时间窗口、部件类别 | CSV | 从 CARE `event_info.csv` 规范化，保留真实标签和匿名资产 | 已生成 | 95 行 |
| 8 | CARE 状态分布表 | `reports/data_processing/care_status_type_distribution.csv` | `datasets/processed_features/care_status_type_distribution.csv` | 各事件文件 `status_type_id` 分布 | CSV | 从规范化 CARE 文件统计 | 已生成 | 按事件和状态展开 |
| 9 | CARE 字段目录 | `reports/data_processing/care_feature_catalog.csv` | `datasets/processed_features/care_feature_catalog.csv` | CARE 各风场传感器字段说明与粗分类 | CSV | 从 `feature_description.csv` 读取并分类 | 已生成 | 355 行 |
| 10 | CARE 事件摘要 | `reports/data_processing/care_event_summary.csv` | `datasets/processed_features/care_event_summary.csv` | 三个风场事件数量、异常/正常数量、部件类别摘要 | CSV | 从 `event_info.csv` 统计 | 已生成 | 3 行 |
| 11 | NREL 齿轮箱振动原始数据 | `backend/data/curated_datasets/raw/vibration/nrel_grc_gearbox_cm` | 未重复打包，见路径说明 | Healthy / Damaged 齿轮箱振动样本 | MAT、ZIP 等真实下载文件 | 已镜像到统一目录，计算首批振动特征 | 已归档，样本级可用 | 20 个已处理 MAT 样本 |
| 12 | Mendeley 叶片振动原始数据 | `backend/data/curated_datasets/raw/vibration/mendeley_blade_vibration_faults` | 未重复打包，见路径说明 | healthy、crack、erosion、twist、unbalance 等叶片振动样本 | CSV / XLSX 等真实下载文件 | 已镜像到统一目录，按真实文件名/目录标签计算特征 | 已归档，样本级可用 | 35 个已处理样本 |
| 13 | 振动特征表 | `reports/data_processing/vibration_features.csv` | `datasets/processed_features/vibration_features.csv` | NREL 和 Mendeley 样本的时域/频域特征 | CSV | 计算 RMS、峰值、峰峰值、标准差、偏度、峭度、主频等 | 已生成，可服务诊断样本库 | 55 行 |
| 14 | YOLO 叶片图像原始数据 | `backend/data/curated_datasets/raw/blade_images/yolo_annotated_wind_turbine_surface_damage` | 未重复打包，见路径说明 | 叶片表面图像与 YOLO 标注，类别为 dirt / damage | JPG/PNG 图像、YOLO TXT 标签、`labels.txt` | 已解压、统计图像和标签配对、统计 bbox 面积 | 已归档，样本级可用 | 13,470 张图；2,995 标签文件 |
| 15 | DTU 巡检图像原始数据 | `backend/data/curated_datasets/raw/blade_images/dtu_drone_inspection` | 未重复打包，见路径说明 | 真实无人机巡检图像 | 图片文件 | 已解压、统计图像数量和样本分辨率 | 已归档，可做图像展示；无检测标注 | 701 张图 |
| 16 | 图像质量表 | `reports/data_processing/image_dataset_quality.csv` | `datasets/processed_features/image_dataset_quality.csv` | YOLO 与 DTU 图像数量、标签数量、配对情况、bbox 统计 | CSV | 从真实图像和标签文件统计，不生成新标签 | 已生成 | 2 行 |
| 17 | 数据集能力画像 | `reports/data_processing/dataset_capability_profile.csv` | `reports/dataset_capability_profile.csv` | 每个数据集能服务哪些功能、限制是什么 | CSV | 汇总真实处理结果 | 已生成 | 7 行 |
| 18 | 建模指标覆盖表 | `reports/data_processing/modeling_indicator_dataset_coverage.csv` | `reports/modeling_indicator_dataset_coverage.csv` | 数据质量、SCADA、振动、图像、HI、RUL 等指标覆盖情况 | CSV | 对照建模需求和真实数据可用性生成 | 已生成 | 10 行 |
| 19 | 用户故事覆盖表 | `reports/data_processing/user_story_dataset_coverage.csv` | `reports/user_story_dataset_coverage.csv` | 14 个用户故事的数据覆盖情况 | CSV | 对照用户故事需求生成 | 已生成 | 14 行 |
| 20 | 数据覆盖评估报告 | `reports/data_processing/DATASET_COVERAGE_ASSESSMENT.md` | `reports/DATASET_COVERAGE_ASSESSMENT.md` | 数据集覆盖结论、边界和开发优先级 | Markdown | 由覆盖评估脚本生成 | 已生成 | 1 份 |
| 21 | CARE 接入计划 | `reports/data_processing/CARE_MODELING_IMPORT_PLAN.md` | `reports/CARE_MODELING_IMPORT_PLAN.md` | CARE 主时间线接入、入库流程、建模使用方式 | Markdown | 基于实际入库结果编写 | 已生成 | 1 份 |
| 22 | 数据交接说明 | `reports/db_handoff/DB_HANDOFF.md` | `DB_HANDOFF.md` | 交给数据库人员的说明文档 | Markdown | 人工整理，说明数据库、边界、表、复核命令 | 已生成 | 1 份 |
| 23 | 交接包清单 | `reports/db_handoff/PACKAGE_MANIFEST.md` | `PACKAGE_MANIFEST.md` | 交接包内容、未打包内容、边界说明 | Markdown | 人工整理 | 已生成 | 1 份 |

## 目录规模

| 路径 | 内容 | 文件数 | 规模 |
|---|---|---:|---:|
| `backend/data/curated_datasets` | 整理后的真实原始数据 | 17,337 | 约 42.61 GiB |
| `backend/data/modeling` | CARE 规范化建模数据 | 95 | 约 0.97 GiB |
| `backend/fengdiao_phm.db` | 已入库 SQLite 数据库 | 1 | 约 5.32 GiB |
| `backend/data/vibration` | 振动导出/中间结果 | 59 | 约 5.49 GiB |
| `backend/data/blade_images` | 图像导出/中间结果 | 7 | 约 5.28 GiB |
| `backend/data/scada` | SCADA 导出/中间结果 | 39 | 约 0.69 GiB |
| `reports/data_processing` | 处理报告和覆盖评估 | 23 | 约 1.19 MiB |
| `handoff_packages/fengdiao_dataset_db_handoff_20260611` | 数据库交接核心包 | 120 | 约 6.29 GiB |

## 当前处理结论

CARE 是当前系统的主时间线数据，已经完成字段标准化和数据库入库，可以支撑 SCADA 运行指标、数据质量、HI/RUL 输入和数据源管理。NREL、Mendeley、YOLO、DTU 是诊断样本库，能支撑振动诊断和图像诊断的真实样本展示，但不能与 CARE 伪造成同一台风机的完整故障链。ERA5/现场气象和业务数据尚未接入，尤其工单、成本、库存、人员排班必须由系统真实积累或用户导入。

## 接下来怎么做

接下来应从“数据已入库”进入“指标可计算”。第一步基于 CARE 的 5,242,948 条 SCADA 记录建立派生指标表，先计算数据质量、功率偏差、温度异常、运行状态分项和事件窗口统计，并保留 `source_dataset`、`source_asset_id`、`import_batch_id`、`field_mapping_version` 等溯源字段。第二步用正常窗口建立功率曲线和温度基线，再形成 HI 分项得分；RUL 先做事件前风险趋势和窗口解释，不直接宣称工业级寿命预测。第三步把振动特征和图像 bbox 统计接入诊断样本库，用真实样本解释诊断结果。业务层面的工单、成本、备件、人员排班应保持空状态或提供导入入口，等待真实业务数据，而不是预置伪造记录。
