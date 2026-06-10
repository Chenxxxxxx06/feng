# 风调预顺 PHM 数据整合策略

## 对原方案的修正

原方案“CARE SCADA 做主数据集，NREL/Mendeley/DTU 做诊断样本库，ERA5 做环境数据，业务数据由系统积累”的方向是对的，但需要修正以下不合理点：

| 原表述 | 不合理之处 | 修正 |
|---|---|---|
| CARE SCADA 负责统一故障窗口 | CARE 可以统一 SCADA 时间线和部分故障/事件窗口，但不能覆盖振动、图像、维修成本、人员调度 | CARE 只作为运行主线和故障事件主线 |
| NREL/Mendeley 振动负责演示诊断算法 | NREL/Mendeley 振动样本与 CARE 风机不是同一设备、同一时间、同一传感器体系 | 只能作为诊断算法样本库，不能反证 CARE 中某台风机的真实故障 |
| DTU 叶片图像负责图像诊断 | DTU 图像与 CARE 无设备关系；原始图像不一定有统一损伤标签，派生标注还有许可证限制 | 作为图像样本库，必须保留来源、标注来源和许可证 |
| ERA5 按经纬度和时间匹配 | 第一阶段 CARE/公开数据不一定提供足够精确的风机坐标；ERA5 时空分辨率也不等于现场传感器 | ERA5 改为可选环境补充，不作为 MVP 必需数据 |
| 业务数据由系统积累 | 方向正确，但 demo 初期没有历史工单、成本、人员负载数据 | 初期只允许用户操作生成，不预置伪造历史闭环 |

## 新数据方案

新方案采用“四层事实边界”：

| 层级 | 数据源 | 系统角色 | 可支撑功能 | 禁止用途 |
|---|---|---|---|---|
| L1 运行主线 | CARE to Compare v6 或现场 SCADA | `primary_scada_timeline` | 风机运行曲线、健康指数、异常窗口、预测维护入口 | 不支撑叶片图像、振动波形、维修成本 |
| L2 诊断样本库 | NREL/DOE 齿轮箱振动、Mendeley 叶片振动、DTU/YOLO 叶片图像 | `diagnostic_sample_library` | 诊断算法展示、频谱/RMS解释、图像标注解释 | 不冒充 L1 同一风机的现场证据 |
| L3 环境补充 | ERA5 或现场气象站 | `optional_weather_context` | 风资源、温度、气压等背景解释 | 不替代 SCADA 风速和现场测量 |
| L4 业务沉淀 | 系统真实工单、成本、人员、检修记录 | `operational_business_records` | 工单流转、成本复盘、人员负载 | 不导入伪造历史记录 |

## 执行顺序

1. 清理旧 demo 数据库或新建空库。
2. 导入 L1：先对 CARE/现场 SCADA 执行 `--dry-run`，确认字段映射、有效时间戳比例和传感器列完整率。
3. 正式导入 L1 后，用 SCADA 驱动地图、风机详情、健康指数和预测维护入口。
4. 导入 L2：振动和图像只挂为“诊断样本库”，页面显示来源边界。
5. L3 仅在有可匹配经纬度和时间范围时导入。
6. L4 由系统操作自然产生；没有真实记录时显示“待积累”。

## 统一来源字段

| 字段 | 含义 |
|---|---|
| `source_dataset` | 数据集 ID，例如 `care_to_compare_v6` |
| `source_file` | 原始文件路径或文件名 |
| `source_row` | 原始 CSV 行号，适用于表格数据 |
| `source_doi` | 数据集 DOI |
| `source_url` | 数据集页面 |
| `source_license` | 数据许可证 |
| `dataset_role` | 数据在系统中的角色 |
| `field_mapping` | 原始列名到系统字段的映射 |

## 当前落地

- `backend/data/data_integration_plan.json`：机器可读的数据方案。
- `GET /api/settings/data-integration-plan`：返回数据方案、当前接入状态和不合理点。
- `scripts.import_real_datasets scada-csv --dry-run`：预检真实 SCADA CSV，不写数据库。
- `scripts.import_real_datasets scada-csv`：导入 L1 运行主线。
- `scripts.import_real_datasets vibration-csv`：导入 L2 振动样本。
- `scripts.import_real_datasets blade-yolo`：导入 L2 图像样本。
- 风机详情页通过 `dataset_window=historical_latest` 标识历史公开数据窗口。
