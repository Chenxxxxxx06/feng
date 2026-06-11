# 数据集覆盖评估

## 评估结论

现有真实数据集可以覆盖大部分技术类功能的样本演示和首批指标计算，但不能完整覆盖业务闭环。14 个用户故事中，已覆盖 2 个，部分覆盖 10 个，缺失 2 个。缺口主要集中在真实风机台账/地理坐标、ERA5 或现场气象、工单、成本、备件、库存、人员排班和维护历史。

必须保留事实边界：CARE 是匿名 SCADA 主时间线；NREL/Mendeley 是振动诊断样本库；YOLO/DTU 是图像诊断与巡检图像样本库。它们不能被伪造成同一台风机、同一时间、同一故障的完整证据链。

## 关键数据事实

- CARE：95 个事件时间序列文件，6 个元数据文件，事件表共 95 条，其中 anomaly 45 条、normal 50 条。
- CARE 规范化：`{"generated_at": "2026-06-10T17:06:24.964676+00:00", "dataset_id": "care_to_compare_v6", "normalized_root": "C:\\Users\\ASUS\\Desktop\\fengdiao-pHM\\backend\\data\\modeling\\care_to_compare_v6\\normalized_events", "event_window_rows": 95, "normalized_event_files": 95, "total_normalized_rows": 5242948, "ready_for_scada_indicator_files": 95, "ready_for_hi_input_files": 95, "ready_for_rul_window_files": 95, "outputs": {"care_standard_field_mapping": "C:\\Users\\ASUS\\Desktop\\fengdiao-pHM\\reports\\data_processing\\care_standard_field_mapping.csv", "care_event_windows_normalized": "C:\\Users\\ASUS\\Desktop\\fengdiao-pHM\\reports\\data_processing\\care_event_windows_normalized.csv", "care_normalized_event_manifest": "C:\\Users\\ASUS\\Desktop\\fengdiao-pHM\\reports\\data_processing\\care_normalized_event_manifest.csv", "care_status_type_distribution": "C:\\Users\\ASUS\\Desktop\\fengdiao-pHM\\reports\\data_processing\\care_status_type_distribution.csv", "care_modeling_import_plan": "C:\\Users\\ASUS\\Desktop\\fengdiao-pHM\\reports\\data_processing\\CARE_MODELING_IMPORT_PLAN.md"}, "notes": ["Normalized event CSV files are generated from real CARE SCADA only.", "No coordinates, turbine models, business costs, work orders, or cross-dataset asset links were generated.", "Large normalized CSV files are under backend/data/modeling and are ignored by Git."]}`。
- CARE 入库：`{"generated_at": "2026-06-10T18:20:44.630004+00:00", "dry_run": false, "dataset_id": "care_to_compare_v6", "db_path": "C:\\Users\\ASUS\\Desktop\\fengdiao-pHM\\backend\\fengdiao_phm.db", "manifest_path": "C:\\Users\\ASUS\\Desktop\\fengdiao-pHM\\reports\\data_processing\\care_normalized_event_manifest.csv", "field_mapping_version": "C:\\Users\\ASUS\\Desktop\\fengdiao-pHM\\reports\\data_processing\\care_standard_field_mapping.csv", "import_batch_id": 2, "started_at": "2026-06-10T17:34:40.862645+00:00", "files_total": 95, "files_imported": 95, "files_skipped": 0, "rows_imported": 5242948, "rows_skipped": 0, "anonymous_assets": 36, "database_scada_records_for_dataset": 5242948, "time_start": "2022-01-01T00:00:00+00:00", "time_end": "2024-02-06T16:30:00+00:00", "replace_dataset": true, "replacement": {"deleted_scada_records": 1000, "deleted_anonymous_assets": 1}, "max_files": null, "max_rows_per_file": null, "quality_gate": {"skipped_invalid_timestamps": true, "skipped_rows_without_source_asset": true, "coordinates_generated": false, "turbine_model_generated": false, "business_records_generated": false}, "reports": {"summary": "C:\\Users\\ASUS\\Desktop\\fengdiao-pHM\\reports\\data_processing\\care_scada_import_batch_summary.json", "file_results": "C:\\Users\\ASUS\\Desktop\\fengdiao-pHM\\reports\\data_processing\\care_scada_import_file_results.csv"}}`。
- CARE 字段类别：`{"active_power": 31, "bearing": 1, "direction_yaw": 16, "electrical": 57, "gearbox": 11, "generator": 10, "hydraulic": 12, "other_sensor": 63, "pitch": 4, "rotational_speed": 14, "temperature": 127, "wind_speed": 9}`。
- 振动样本：`{"mendeley_blade_vibration_faults": 35, "nrel_grc_gearbox_cm": 20}`。
- 图像样本：`{"yolo_annotated_wind_turbine_surface_damage": {"image_files": 13470, "label_files": 2995, "paired_image_label_count": 2995, "class_name_counts": {"dirt": 581, "damage": 8770}}, "dtu_drone_inspection": {"image_files": 701, "label_files": 0, "paired_image_label_count": null, "class_name_counts": {}}}`。

## 数据集能力画像

| dataset_id | coverage_level | serves | available_evidence | limitations |
| --- | --- | --- | --- | --- |
| care_to_compare_v6 | 核心技术数据已标准化，支持匿名资产入库 | SCADA运行指标、数据质量、故障窗口、HI/RUL入口、数据源监控、离线建模 | 95 event datasets; 95 event_info rows; 45 anomaly and 50 normal events; 36 farm-scoped anonymous asset references; normalized 95 event files with 5242948 rows; imported 5242948 SCADA rows into SQLite with 36 anonymous assets | 匿名数据；没有真实经纬度、真实风机型号、真实额定功率、业务工单和成本；导入时必须使用匿名资产模式；不能与振动/图像样本伪造成同一台风机证据 |
| nrel_grc_gearbox_cm | 样本级覆盖 | 齿轮箱振动波形、时域/频域指标、样本级故障诊断解释 | 20 processed MAT samples; labels {'damaged': 10, 'healthy': 10} | 不是 CARE 同一风机；当前未确认所有通道采样率；只能作为诊断样本库和算法演示来源 |
| mendeley_blade_vibration_faults | 样本级覆盖 | 叶片振动波形、时域/频域指标、样本级故障诊断解释 | 35 processed CSV/XLSX samples; labels {'crack': 7, 'erosion': 7, 'healthy': 7, 'twist': 7, 'unbalance': 7} | 不是 CARE 同一风机；标签来自真实文件名/数据集结构，后续要保留来源说明 |
| yolo_annotated_wind_turbine_surface_damage | 样本级覆盖 | 叶片图像损伤定位、bbox面积占比、图像诊断证据 | 13470 images; 2995 YOLO label files; 2995 paired image-label samples; class counts {'dirt': 581, 'damage': 8770} | 类别以数据集 labels.txt 为准；不生成模型置信度；不代表 CARE 风机现场巡检历史 |
| dtu_drone_inspection | 图像展示覆盖，标注诊断缺失 | 真实巡检图像展示、图像质量检查、来源追溯 | 701 raw images; labels 0 | 没有检测标注；不能编造损伤类别或 bbox |
| era5_or_site_weather | 缺失，可后置 | 环境背景、RUL增强、页面解释 | not downloaded | 需要真实坐标和时间范围后再匹配；不能替代 SCADA 传感器 |
| business_records | 缺失，需要自建或导入 | 成本决策、维护日历、工单闭环、备件采购 | not available from public datasets | 必须由系统真实操作积累或用户提供带来源记录；不能预置伪造历史 |

## 建模指标覆盖

| indicator_group | coverage_level | can_compute_now | missing_or_pending |
| --- | --- | --- | --- |
| 数据质量评分 | 部分覆盖 | 文件级完整性、SCADA 行级时间戳有效率、标准字段非空计数、图像标注配对率、振动特征行数；CARE 已入库 5242948 条 SCADA 记录、36 个匿名资产，并保留批次日志 | 传感器异常值分布、页面级质量聚合和阈值标定 |
| SCADA运行指标 | 部分覆盖 | 运行状态、事件窗口、风速、功率、转速、温度、桨距、方向等标准字段已可计算；CARE 已入库 5242948 条 SCADA 记录、36 个匿名资产，并保留批次日志 | 真实额定功率、真实机型、真实地理位置和正常基线标定 |
| 振动诊断指标 | 已覆盖 | RMS、峰值、峰峰值、标准差、偏度、峭度、波峰因子、脉冲因子、形状因子、裕度因子、主频/主频bin | NREL 采样率和更多通道选择策略；阈值标定；诊断 API 接入 |
| 叶片图像损伤指标 | 已覆盖 | 真实图像展示、YOLO bbox、类别 dirt/damage、bbox面积占比、标注配对率 | 模型训练/推理置信度；DTU 无标注；严重度阈值需标定 |
| 健康指数 HI | 部分覆盖 | CARE 标准化 SCADA 可支持功率、温度、运行状态分项；振动和图像可支持样本级分项 | 权重、阈值、跨源资产关联边界、数据库入库后的统一计算 |
| 故障贡献排序 | 部分覆盖 | 基于来源明确的规则型证据排序 | 训练后的特征贡献、SHAP/模型解释、历史阈值验证 |
| RUL预测 | 部分覆盖 | 风险趋势、事件前窗口、HI 趋势入口；CARE 事件窗口已规范化 | 真实维修记录、失效阈值、寿命终点定义、工业级验证 |
| 维护成本决策 | 缺失 | 公式框架和用户输入参数计算 | 人工、备件、停机、电价、外包、库存、历史工单等真实业务数据 |
| 工单优先级 | 部分覆盖 | 规则框架 | 真实工单、人员、库存、备件、SLA 和业务权重 |
| 数据源监控与页面总结 | 部分覆盖 | 下载/解压/处理状态、缺失项说明、页面数据来源说明 | 导入批次日志、数据库记录数、字段映射版本、页面级数据质量聚合 |

## 用户故事覆盖

| story_id | user_story | coverage_level | evidence | gap_action |
| --- | --- | --- | --- | --- |
| US01 | 地图查看所有风机状态 | 部分覆盖 | CARE 已完成匿名资产入库：5242948 条 SCADA 记录、36 个匿名资产；仍缺真实坐标、机型、额定功率和现场台账。 | 先完成字段映射、入库和指标标定，再开放完整功能 |
| US02 | 按机型、HI、区域筛选风机 | 部分覆盖 | CARE 可支持状态和后续 HI；缺机型、额定功率、区域标签、投运信息等真实台账字段。 | 先完成字段映射、入库和指标标定，再开放完整功能 |
| US03 | 查询单台风机详细指标 | 部分覆盖 | CARE 已完成匿名资产入库：5242948 条 SCADA 记录、36 个匿名资产；仍缺真实坐标、机型、额定功率和现场台账。 CARE 已映射风速、功率、转速、温度、桨距、方向等字段；ERA5/现场气象未接入。 | 先完成字段映射、入库和指标标定，再开放完整功能 |
| US04 | 自动识别故障类型并给出置信度 | 部分覆盖 | CARE 事件窗口已规范化；NREL/Mendeley 有振动样本；YOLO 有图像标注；模型置信度和跨源融合尚未实现。 | 先完成字段映射、入库和指标标定，再开放完整功能 |
| US05 | 基于叶片图像定位损伤 | 已覆盖 | YOLO 有真实图像、真实 bbox、类别 dirt/damage；DTU 有真实巡检图像但无标注。 | 接入后端 API 和前端展示，保留来源字段 |
| US06 | 查看振动波形数据 | 已覆盖 | NREL/Mendeley 原始振动数据已整理，并已计算 55 行首批时域/频域特征。 | 接入后端 API 和前端展示，保留来源字段 |
| US07 | 故障相关指数按重要程度排序 | 部分覆盖 | 有可解释指标输入，但贡献排序算法、权重、SHAP 或历史阈值仍待建立。 | 先完成字段映射、入库和指标标定，再开放完整功能 |
| US08 | 查看风机和核心部件RUL预测 | 部分覆盖 | CARE 长期 SCADA 和事件窗口已标准化，可做风险趋势入口；缺维修记录、寿命终点和工业级 RUL 验证。 | 先完成字段映射、入库和指标标定，再开放完整功能 |
| US09 | 对比不同维护决策成本 | 缺失 | 公开数据集不提供真实成本、备件、人工、停机损失；只能等待用户录入或真实业务导入。 | 从空状态开始，由系统真实积累或用户提供带来源数据 |
| US10 | 自动生成维护日历和备件采购提示 | 部分覆盖 | 诊断/RUL 风险输入可逐步形成；备件、库存、采购周期、人员排班和天气窗口缺失。 | 先完成字段映射、入库和指标标定，再开放完整功能 |
| US11 | 管理维修工单完整流程 | 缺失 | 真实工单流程数据应由系统操作积累或用户导入；不能沿用 demo 工单。 | 从空状态开始，由系统真实积累或用户提供带来源数据 |
| US12 | 配置HI阈值和通知渠道 | 部分覆盖 | 阈值配置可先做系统配置；HI 输出、阈值版本和误报漏报统计要等真实指标运行后沉淀。 | 先完成字段映射、入库和指标标定，再开放完整功能 |
| US13 | 自动总结当前页面关键信息 | 部分覆盖 | 可以总结真实数据状态和缺失项；完整页面摘要依赖各模块 API 入库和质量标记。 | 先完成字段映射、入库和指标标定，再开放完整功能 |
| US14 | 配置和监控各类数据源连接 | 部分覆盖 | CARE 已完成匿名资产入库：5242948 条 SCADA 记录、36 个匿名资产；仍缺真实坐标、机型、额定功率和现场台账。 已有真实数据源、处理摘要、字段映射、规范化清单、质量报告和入库批次日志。 | 先完成字段映射、入库和指标标定，再开放完整功能 |

## 开发优先级

1. CARE 字段语义映射和主时间线入库：先解决 US01、US02、US03、US08、US14 的数据底座。
2. 振动与图像样本库接入诊断页面：先解决 US04、US05、US06、US07 的真实证据展示。
3. HI 与贡献排序做规则型版本：先输出来源明确的分项分数，不写死未标定权重。
4. RUL 先做风险趋势和事件窗口解释：不声称工业级寿命预测已经完成。
5. 业务数据从空状态开始：工单、成本、库存、人员排班必须由系统真实积累或用户导入。
