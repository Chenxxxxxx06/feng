# 代码审查报告 — diagnosis.py + turbines.py 数据接口同步

> 审查日期: 2026-06-15
> 审查范围: `backend/app/api/diagnosis.py` (511→852行) + `backend/app/api/turbines.py` (+40行)
> 变更来源: 从 `fengdiao_portable` 同步数据接口代码，确保相对路径与数据接入一致

---

## 变更概述

| 文件 | 变更 | 说明 |
|------|------|------|
| `diagnosis.py` | +400行 | 新增 SCADA/振动/叶片数据接入、CARE故障检测、DFT频谱计算、批量检测 |
| `turbines.py` | +40行 | 新增 `/monitoring-metrics`、`/refresh-health` 端点 |
| `care_monitoring_metrics.py` | 新文件 | CARE 事件指标计算（从 portable 复制） |
| `backend/data/` | 替换 | 从 portable 完整复制 17419 个文件 |
| `fengdiao_phm.db` | 替换 | 从 portable 复制 5.7GB SQLite 数据库 |

---

## 🔴 严重问题 (4个)

### 1. `turbine.hi_value >= 85` 空指针崩溃

- **文件**: `backend/app/api/diagnosis.py`
- **行号**: 438
- **函数**: `_build_dataset_detection`
- **代码**:
  ```python
  confidence = round(0.72 if turbine.hi_value >= 85 else 0.62, 2)
  ```
- **问题**: `turbine.hi_value` 在数据库中为可空字段 (`FLOAT`)。当值为 `None` 时，Python 抛出 `TypeError: '>=' not supported between instances of 'NoneType' and 'int'`
- **触发条件**: 任意 `status=normal` + `hi_value=NULL` 的风机
- **影响范围**: `POST /api/diagnosis/auto-detect`、`POST /api/diagnosis/auto-detect/batch`、`GET /api/diagnosis/faults/{negative_id}` 全部崩溃
- **建议修复**: `(turbine.hi_value or 0.0) >= 85`

### 2. `list_turbines` 默认值破坏 API 契约

- **文件**: `backend/app/api/turbines.py`
- **行号**: 73
- **代码**:
  ```python
  # 旧: source_dataset: str | None = Query(None, ...)
  # 新: source_dataset: str | None = Query("care_to_compare_v6", ...)
  ```
- **问题**: 默认值从 `None`(不过滤) 改为 `"care_to_compare_v6"`(只返回CARE风机)。前端 Dashboard、Diagnosis、Prediction 等页面调用 `GET /api/turbines/` 不传参时，只能看到 36 台 CARE 风机，30 台 demo 风机被静默过滤
- **影响范围**: 
  - `DashboardPage.tsx:77` — 仪表盘统计
  - `DiagnosisPage.tsx:191` — 诊断页风机列表
  - `predictionService.ts:78` — 预测服务
- **建议**: 保持默认 `None`，由前端显式传参过滤

### 3. DB 故障的工单元数据字段全部丢失

- **文件**: `backend/app/api/diagnosis.py`
- **行号**: 567-578 (`list_faults`), 606-615 (`get_fault_detail`)
- **问题**: 新的 `FaultResponse(...)` 构造只传了 9 个字段 (`id, turbine_id, turbine_name, turbine_region, detected_at, fault_type, confidence, status, details`)，以下 13 个字段不再从 DB 填充:
  - `discovered_at` → 默认 `None`
  - `processing_started_at` → 默认 `None`
  - `closed_at` → 默认 `None`
  - `failed_at` → 默认 `None`
  - `handler` → 默认 `None`
  - `processing_status` → 默认 `"pending"`
  - `priority` → 默认 `"medium"`
  - `work_order_id` → 默认 `None`
  - `work_order_title` → 默认 `None`
  - `last_action_at` → 默认 `None`
  - `maintenance_cost_estimate` → 默认 `None`
  - `maintenance_cost_actual` → 默认 `None`
  - `status_note` → 默认 `""`
- **影响**: 前端工单详情、处理状态、成本统计、时间线排序全部失效
- **建议**: 恢复 `FaultResponse` 中的字段填充，或确认 portable 版本有意移除

### 4. `get_fault_detail` 丢失 `turbine_region`

- **文件**: `backend/app/api/diagnosis.py`
- **行号**: 600
- **代码**:
  ```python
  # 旧: select(Fault, Turbine.name, Turbine.region)
  # 新: select(Fault, Turbine.name)
  ```
- **问题**: 不再从 JOIN 查询中获取 `Turbine.region`，导致 `turbine_region` 返回空字符串
- **影响**: 地图组件中 DB 故障标记的 `region` 为空 → 落入"未分组"桶

---

## 🟡 中等问题 (4个)

### 5. `_care_fault_detail` 重复调用 `_build_dataset_detection` 两次

- **文件**: `backend/app/api/diagnosis.py`
- **行号**: 534-535
- **问题**: `_care_fault_response_for_turbine` (line 534) 内部已调用 `_build_dataset_detection`，紧接着 line 535 又调一次
- **成本**: 每次 fault detail 请求: +3 DB 查询 +3 文件读取 +1 函数调用
- **建议**: 从 `_care_fault_response_for_turbine` 中返回 detection 结果，避免重复计算

### 6. `list_faults` 无缓存，串行查询 36 台风机

- **文件**: `backend/app/api/diagnosis.py`
- **行号**: 543-557
- **问题**: 每个 CARE 风机串行执行 SCADA 查询 + 振动查询 + 波形 JSON 文件读取
- **成本**: 36 台风机 = 72 次 DB 查询 + 72 次文件读取（单次 `/faults` 调用）
- **建议**: 使用 `asyncio.gather` 并行查询，或为频繁访问的风机添加缓存

### 7. `_spectrum_from_waveform` O(n×bins) 手写 DFT

- **文件**: `backend/app/api/diagnosis.py`
- **行号**: 251-268
- **问题**: 用纯 Python 双重循环实现 DFT，100k 样本 × 120 bins = 12M 次迭代 + 24M 次三角函数调用
- **成本**: 单次无缓存调用阻塞事件循环数十毫秒
- **修复**: 项目 `requirements.txt` 已包含 `numpy==1.26.4`，脚本层已有 `np.fft.rfft` 实现 (`scripts/import_real_datasets.py:348`)
- **建议**: 用 `numpy.fft.rfft` 替代手写 DFT

### 8. `diagnosis_orchestrator.py` 变成死代码

- **文件**: `backend/app/services/diagnosis_orchestrator.py`
- **问题**: `run_auto_fault_identification` 和 `run_batch_auto_fault_identification` 不再被任何代码导入调用
- **影响**: 
  - 已有的通用 demo-turbine 过滤逻辑 (`source_dataset IS NOT NULL`) 被废弃
  - 批量检测从通用数据集支持降级为硬编码 `CARE_DATASET_ID`
- **建议**: 将新逻辑集成到 orchestrator 中，而非绕过它

---

## 🟢 建议 (4个)

### 9. 架构问题：~160 行业务逻辑嵌入 API 路由层

- **问题**: `_build_dataset_detection`、`_care_fault_response_for_turbine`、`_care_fault_detail`、`_care_fault_type`、`_diagnosis_steps` 等函数共约 160 行领域逻辑直接写在 `diagnosis.py` API 路由模块中
- **影响**: 
  - 无法被其他端点复用
  - 无法进行单元测试（依赖 `db` 参数的私有路由辅助函数）
  - 路由文件膨胀至 852 行
- **建议**: 提取到 `backend/app/services/care_fault_service.py`

### 10. 死代码：`_severity_from_priority` 从未被调用

- **文件**: `backend/app/api/diagnosis.py`
- **行号**: 233
- **问题**: 函数定义后全代码库无调用
- **建议**: 删除

### 11. 重复代码：`_parse_dt` 与 `care_monitoring_metrics._parse_datetime` 完全相同

- **文件**: `diagnosis.py:218` vs `care_monitoring_metrics.py:226`
- **代码**: 两者均为 `datetime.fromisoformat(value.replace("Z", "+00:00"))`
- **建议**: 删除 `_parse_dt`，导入 `_parse_datetime`

### 12. `_confidence_interval` 边界值不一致

- **文件**: `diagnosis.py:229` vs `diagnosis_orchestrator.py:91`
- **差异**: diagnosis 版本下界 `c - 0.06`，orchestrator 版本下界 `c - 0.07`
- **建议**: 统一边界值，提取到共享工具模块

---

## 已验证无问题的部分

| 项目 | 状态 | 说明 |
|------|------|------|
| `care_monitoring_metrics.py` | ✅ | 正确从 portable 复制，路径完全相对 |
| `backend/data/` 目录结构 | ✅ | 与 portable 完全一致 (17419 文件) |
| `fengdiao_phm.db` 数据 | ✅ | 所有表 checksum 与 portable 一致 |
| `models.py` | ✅ | 与 portable 完全一致 |
| `data_pipeline/*` (6个文件) | ✅ | 与 portable 完全一致 |
| `blade_yolo_service.py` | ✅ | 与 portable 完全一致 |
| `config.py` ROOT_DIR/BACKEND_DIR | ✅ | 路径模式与 portable 一致 |
| CARE turbine 计数 | ✅ | 33+2+1 = 36 台，3 个区域 |
| 无"陕北"等 demo 风机泄露 | ✅ | 默认 `source_dataset=care_to_compare_v6` |
| `/api/prediction/maintenance-plan` | ✅ | 路由存在且正常响应 |
| `/api/health` | ✅ | 返回 version 2.0.0 |
| 所有 Python 导入 | ✅ | 无 import 错误 |

---

## 优先级建议

| 优先级 | 编号 | 问题 | 修复难度 |
|--------|------|------|---------|
| P0 | #1 | hi_value 空指针崩溃 | 低 (1行) |
| P0 | #2 | list_turbines 默认值 | 低 (1行) |
| P0 | #3 | 工单元数据丢失 | 中 (~15行) |
| P1 | #4 | turbine_region 丢失 | 低 (1行) |
| P1 | #5 | 重复调用 _build_dataset_detection | 中 |
| P2 | #6 | list_faults 无缓存 | 中 |
| P2 | #7 | 手写 DFT 性能 | 中 |
| P3 | #8 | orchestrator 死代码 | 高 (架构) |
| P3 | #9-12 | 架构/重复/死代码 | 中-高 |

---

*报告由 AI code-review 工具生成*
