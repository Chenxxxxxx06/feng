# 真实数据整理与首批处理结果

## 处理目标

本轮任务将已下载的真实数据统一整理到项目内的受控目录，并依据 `MATHEMATICAL_MODELING_DESIGN.md` 生成首批可复核的数据处理结果。处理过程不生成伪造数据，不创建合成图像，不向业务数据库写入记录。

## 统一数据目录

大体量数据统一放置在：

`C:\Users\ASUS\Desktop\fengdiao-pHM\backend\data\curated_datasets`

该目录已加入 `.gitignore`，只保留本机数据，不纳入 Git 仓库。

## 已整理数据

| 数据集 | 本轮用途 | 处理状态 | 说明 |
|---|---|---|---|
| CARE to Compare v6 SCADA | 主时间线、运行状态、状态标签、SCADA 指标建模 | 已归档并解压 | 识别到 95 个事件时间序列 CSV 和 6 个元数据 CSV；事件数据为分号分隔，Wind Farm A 单文件表头识别为 86 列 |
| Mendeley Blade Fault Vibration | 叶片振动诊断样本 | 已镜像到统一目录并计算特征 | 计算均值、标准差、RMS、峰值、峭度、偏度、峰值因子、主频等首批指标 |
| NREL GRC Gearbox Vibration | 齿轮箱振动诊断样本 | 已镜像到统一目录并计算特征 | 基于真实 MAT 文件读取通道并计算首批振动特征 |
| YOLO Annotated Wind Turbine Surface Damage | 叶片表面损伤识别样本 | 已归档并解压 | 使用项目中已验证可解压的压缩包；`maindata` 中同名压缩包尾部为零填充，不作为处理来源 |
| DTU Drone Inspection Images | 叶片巡检图像演示与质量检查 | 已归档并解压 | 统计图像数量与样本分辨率；该数据集没有标注文件 |

## 输出文件

| 文件 | 内容 | 当前规模 |
|---|---|---|
| `dataset_processing_summary.json` | 数据来源、归档、解压、镜像、输出文件与处理计数 | 记录 3 个归档数据集、2 个振动镜像目录 |
| `vibration_features.csv` | 振动诊断首批数学特征 | 55 行 |
| `image_dataset_quality.csv` | 图像数据质量与标注完整性统计 | 2 行 |
| `care_scada_files.csv` | CARE SCADA 文件级摘要 | 101 行 |
| `care_event_summary.csv` | CARE 事件标签、异常/正常数量、部件类别摘要 | 3 行 |
| `care_feature_catalog.csv` | CARE 各风场传感器字段说明和粗分类 | 355 行 |
| `care_standard_field_mapping.csv` | CARE 传感器字段到项目标准 SCADA 字段的映射 | 30 行 |
| `care_event_windows_normalized.csv` | CARE 事件窗口规范表 | 95 行 |
| `care_normalized_event_manifest.csv` | 规范化事件 CSV 的可用性、完整性和状态分布摘要 | 95 行 |
| `care_status_type_distribution.csv` | 各事件文件的 `status_type_id` 分布 | 按事件和状态展开 |
| `care_modeling_dataset_summary.json` | CARE 建模预处理汇总 | 1 份 |
| `care_normalized_import_dry_run.json` | 规范化 CARE 文件通过现有 SCADA 导入器 dry-run 的验证结果 | 1 份 |
| `CARE_MODELING_IMPORT_PLAN.md` | CARE 主时间线入库计划和约束 | Markdown 报告 |
| `dataset_capability_profile.csv` | 当前真实数据集能力画像 | 7 行 |
| `modeling_indicator_dataset_coverage.csv` | 建模指标与数据集覆盖关系 | 10 行 |
| `user_story_dataset_coverage.csv` | 14 个用户故事的数据覆盖判断 | 14 行 |
| `DATASET_COVERAGE_ASSESSMENT.md` | 数据集覆盖评估结论和开发优先级 | Markdown 报告 |

## 当前限制

1. CARE SCADA 目前已完成文件级摘要、事件摘要、字段目录、标准字段映射、事件窗口规范化和 95 个事件文件的标准 SCADA 字段输出，规范化大文件位于 `backend/data/modeling/care_to_compare_v6/normalized_events`。
2. 振动数据已计算首批统计与频域特征，但 NREL 与 Mendeley 不是同一设备来源，不能强行绑定到 CARE 风机资产。
3. DTU 图像没有检测标注，只适合作为巡检图像展示与人工质检样本；YOLO 数据集可用于表面损伤检测演示，类别来自真实 `labels.txt`。
4. CARE 规范化文件已经能被 `scada-csv --allow-anonymous-assets` 导入器 dry-run 识别；导入时会创建无真实坐标、无机型、无额定功率的匿名 CARE 资产，不能把匿名资产硬绑定到真实风机或伪造坐标。
5. 真实工单、成本、库存、人员排班和维护历史仍缺失，需要系统真实积累或用户提供带来源数据。

## 下一步

1. 基于 `care_normalized_event_manifest.csv` 建立 SCADA 入库批次和质量日志。
2. 用正常事件窗口拟合功率曲线与温度基线，再计算 HI 分项。
3. 将 `vibration_features.csv` 接入诊断样本库，前端展示真实振动特征与可解释诊断依据。
4. 将 YOLO 标注样本接入图像诊断演示，明确类别映射、标注完整性与样本限制。
