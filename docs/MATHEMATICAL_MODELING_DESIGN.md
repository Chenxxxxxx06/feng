# 风机 PHM 数学建模与指标体系设计

更新时间：2026-06-10  
适用项目：风调雨顺 PHM 系统  
当前阶段：真实数据下载与接入前的模型设计阶段

## 1. 建模目标

本文件用于定义项目中数学建模相关功能的公式、参数、数据输入、输出结果和后续标定方法。当前不填入未经验证的固定阈值、固定权重或业务成本数值。

建模目标包括：

- 将 SCADA、振动、叶片图像、业务工单等数据转化为可解释指标。
- 支撑 14 个用户故事中的监控、诊断、预测、决策和数据源管理功能。
- 明确哪些指标属于行业常用公式，哪些属于项目自定义综合模型。
- 在真实数据导入后，用数据计算、校准和验证模型参数。

核心约束：

- 不伪造数据、标签、图像、工单、成本或诊断结果。
- 没有真实数据时，参数状态标记为 `待标定`、`待配置` 或 `缺失`。
- NREL、Mendeley、DTU、YOLO 样本库不得伪造成 CARE SCADA 同一风机、同一时间的证据。

## 2. 建模功能总览

| 功能模块 | 服务用户故事 | 模型输出 | 当前能否定公式 | 参数是否已定 |
|---|---|---|---|---|
| 数据质量评分 | US01、US03、US13、US14 | 缺失率、时间戳有效率、可用性等级 | 能 | 部分待定 |
| SCADA运行指标 | US01、US02、US03、US07、US08 | 功率偏差、温度异常、运行状态 | 能 | 待 CARE 标定 |
| 振动诊断指标 | US04、US06、US07、US13 | RMS、峭度、波峰因子、频谱主峰 | 能 | 采样率来自数据集，阈值待定 |
| 叶片图像指标 | US04、US05、US07、US13 | 损伤类别、bbox面积占比、严重度 | 能 | 严重度阈值待定 |
| 健康指数 HI | US01、US02、US07、US08、US12 | 综合健康分、分项扣分 | 能定义 | 权重待标定 |
| 故障贡献排序 | US04、US07、US13 | 指标重要程度、根因候选 | 能定义 | 权重待标定 |
| RUL预测 | US08、US10、US13 | 剩余寿命、维护提前量 | 能定义基础模型 | 失效阈值待定 |
| 维护成本决策 | US09、US10、US11 | 立即维修/延迟维修成本对比 | 能定义 | 成本参数需用户录入 |
| 工单优先级 | US10、US11、US13 | 工单排序、处理优先级 | 能定义 | 权重需业务配置 |

## 3. 数据质量模型

数据质量模型用于判断某段数据是否可以进入诊断、预测或展示流程。

### 3.1 时间戳有效率

```text
valid_timestamp_rate = valid_timestamp_count / total_row_count
```

参数说明：

| 参数 | 含义 | 来源 |
|---|---|---|
| `valid_timestamp_count` | 可解析时间戳行数 | 数据预检 |
| `total_row_count` | 总行数 | 数据文件 |

### 3.2 数值完整率

```text
numeric_completeness_rate_j = non_null_numeric_count_j / total_row_count
```

其中 `j` 表示某个传感器字段，例如风速、功率、温度或振动通道。

### 3.3 数据新鲜度

```text
data_age = current_time - latest_data_timestamp
```

数据新鲜度用于判断页面展示是否过期。过期阈值不在当前阶段固定，后续根据业务刷新周期配置。

### 3.4 数据质量扣分

```text
DQ_penalty = a1 * missing_rate + a2 * invalid_timestamp_rate + a3 * stale_rate
```

说明：

- `a1`、`a2`、`a3` 是项目权重，待标定或配置。
- 如果数据缺失严重，应显示“数据不足”，而不是输出诊断结论。

## 4. SCADA运行指标模型

SCADA 主要服务风场监控、单机详情、健康指数、故障窗口和 RUL 入口。

### 4.1 功率曲线偏差

功率曲线偏差用于判断风机在给定风速下的发电表现是否偏离正常水平。

```text
power_deviation = |P_actual - P_expected(v)| / P_rated
```

参数说明：

| 参数 | 含义 | 来源 |
|---|---|---|
| `P_actual` | 实际有功功率 | CARE SCADA |
| `v` | 风速 | CARE SCADA |
| `P_expected(v)` | 风速为 `v` 时的期望功率 | 由健康运行样本拟合 |
| `P_rated` | 额定功率 | CARE元数据或真实台账 |

`P_expected(v)` 不能凭空填写，建议后续用 CARE 中正常运行段按风速分箱计算：

```text
P_expected(v_bin) = median(P_actual in v_bin under healthy/normal state)
```

### 4.2 温度异常

温度异常用于判断发电机、齿轮箱、轴承等部件是否出现热异常。

基础形式：

```text
temp_z_score = (T_actual - mean(T_baseline)) / std(T_baseline)
```

或使用残差形式：

```text
temp_residual = T_actual - T_expected(load, ambient_temp)
```

参数说明：

| 参数 | 含义 | 来源 |
|---|---|---|
| `T_actual` | 实测温度 | CARE SCADA |
| `T_baseline` | 正常状态温度基线 | CARE正常运行样本 |
| `load` | 负载或功率 | CARE SCADA |
| `ambient_temp` | 环境温度 | CARE或ERA5背景 |

### 4.3 转速异常

```text
rpm_deviation = |rpm_actual - rpm_expected(v, P_actual)| / rpm_rated
```

`rpm_expected` 应由正常工况数据拟合，不在当前阶段固定。

### 4.4 桨距角异常

```text
pitch_deviation = |pitch_actual - pitch_expected(v, P_actual)|
```

桨距角异常通常需要结合风速、功率和运行区域判断。单独阈值不应提前写死。

### 4.5 偏航或机舱方向异常

如果有风向和机舱方向，可定义：

```text
yaw_misalignment = angular_difference(wind_direction, nacelle_direction)
```

如果 CARE 中没有可靠风向字段，则该指标应标记为不可用。

## 5. 振动诊断模型

振动指标主要服务机械状态诊断、波形展示、频谱分析和故障贡献排序。

### 5.1 输入数据

| 数据源 | 当前状态 | 可用内容 |
|---|---|---|
| NREL Gearbox Vibration | 已解压 | 20 个 `.mat` 文件，包含 `Speed`、`Torque`、`AN3` 至 `AN10` 等变量 |
| Mendeley Blade Vibration | 已解压 | 28 个分号 CSV，7 个 XLSX，采样率说明为 1 kHz、每通道 500 样本 |

### 5.2 时域指标

设振动序列为：

```text
x = [x_1, x_2, ..., x_N]
```

均值：

```text
mean = (1 / N) * Σ x_i
```

均方根 RMS：

```text
RMS = sqrt((1 / N) * Σ x_i^2)
```

峰值：

```text
peak = max(|x_i|)
```

峰峰值：

```text
peak_to_peak = max(x_i) - min(x_i)
```

标准差：

```text
std = sqrt((1 / (N - 1)) * Σ (x_i - mean)^2)
```

偏度：

```text
skewness = (1 / N) * Σ ((x_i - mean) / std)^3
```

峭度：

```text
kurtosis = (1 / N) * Σ ((x_i - mean) / std)^4
```

波峰因子：

```text
crest_factor = peak / RMS
```

裕度因子：

```text
clearance_factor = peak / ((1 / N) * Σ sqrt(|x_i|))^2
```

脉冲因子：

```text
impulse_factor = peak / mean(|x_i|)
```

形状因子：

```text
shape_factor = RMS / mean(|x_i|)
```

### 5.3 频域指标

频谱由 FFT 得到：

```text
X_k = FFT(x)
frequency_k = k * fs / N
```

其中：

| 参数 | 含义 | 来源 |
|---|---|---|
| `fs` | 采样率 | 数据集说明或文件元数据 |
| `N` | 窗口样本数 | 数据文件或窗口配置 |
| `X_k` | 第 k 个频率点幅值 | FFT计算 |

主峰频率：

```text
f_peak = frequency at max(|X_k|)
```

频带能量：

```text
band_energy(f1, f2) = Σ |X_k|^2, where f1 <= frequency_k <= f2
```

谱质心：

```text
spectral_centroid = Σ(frequency_k * |X_k|) / Σ|X_k|
```

### 5.4 振动异常得分

当前阶段可定义通用形式：

```text
vibration_score = b1 * normalized_RMS
                + b2 * normalized_kurtosis
                + b3 * normalized_crest_factor
                + b4 * normalized_band_energy
```

说明：

- `b1` 至 `b4` 为待标定权重。
- `normalized_*` 应基于同数据集健康样本或正常段计算。
- NREL 的健康/损伤标签可用于初步标定齿轮箱振动指标。
- Mendeley 的文件名标签可用于叶片振动样本标定。

## 6. 叶片图像损伤模型

图像指标主要服务叶片损伤定位、巡检建议和诊断证据展示。

### 6.1 输入数据

| 数据源 | 当前状态 | 可用内容 |
|---|---|---|
| YOLO Annotated Wind Turbine Surface Damage | 下载中 | 图像和 YOLO 格式标注，类别说明包含 Dirt 和 Damage |
| DTU Drone Inspection Images | 下载中 | 原始巡检图像，用于来源追溯和图像展示 |

### 6.2 YOLO bbox转换

YOLO 标注通常包含：

```text
class_id, x_center_norm, y_center_norm, width_norm, height_norm
```

转换为像素坐标：

```text
x = (x_center_norm - width_norm / 2) * image_width
y = (y_center_norm - height_norm / 2) * image_height
w = width_norm * image_width
h = height_norm * image_height
```

### 6.3 损伤面积占比

```text
damage_area_ratio = (bbox_width * bbox_height) / (image_width * image_height)
```

如果一张图有多个损伤框：

```text
total_damage_area_ratio = Σ bbox_area_i / image_area
```

注意：该指标是图像平面占比，不等同于真实叶片物理面积占比。

### 6.4 图像损伤严重度

基础形式：

```text
image_damage_score = c1 * damage_type_weight
                   + c2 * damage_area_ratio
                   + c3 * object_count_score
                   + c4 * image_quality_penalty
```

说明：

- `damage_type_weight` 待根据标签类别和业务风险定义。
- `damage_area_ratio` 可直接计算。
- `object_count_score` 可由标注框数量计算。
- `image_quality_penalty` 需要根据模糊、遮挡、分辨率等规则定义。
- 不能为人工标注生成模型置信度。

## 7. 健康指数 HI 模型

HI 是项目自定义综合指标，用于把多类异常合成为可解释健康分。底层分项指标可来自行业常用公式，但综合方式、权重和阈值需要真实数据标定。

### 7.1 HI总体形式

```text
HI = 100 - total_penalty
```

```text
total_penalty = w_power * S_power
              + w_temp * S_temp
              + w_vibration * S_vibration
              + w_image * S_image
              + w_data_quality * S_data_quality
```

参数说明：

| 参数 | 含义 | 当前状态 |
|---|---|---|
| `S_power` | 功率曲线异常分 | 待 CARE 计算 |
| `S_temp` | 温度异常分 | 待 CARE 计算 |
| `S_vibration` | 振动异常分 | 待 NREL/Mendeley 标定 |
| `S_image` | 图像损伤分 | 待 YOLO/DTU 导入 |
| `S_data_quality` | 数据质量扣分 | 可先实现 |
| `w_*` | 各分项权重 | 待标定或配置 |

### 7.2 分项归一化

为了合成 HI，各类异常分应归一化到同一范围，例如：

```text
S_j = min(100, 100 * raw_anomaly_j / anomaly_reference_j)
```

其中 `anomaly_reference_j` 必须来自：

- 数据集健康样本统计；
- 文献或标准建议；
- 用户配置；
- 后续标定结果。

当前阶段不写死。

### 7.3 HI等级

HI等级建议用配置项表示：

```text
normal: HI >= threshold_normal
warning: threshold_fault <= HI < threshold_normal
fault: HI < threshold_fault
```

`threshold_normal` 和 `threshold_fault` 当前标记为 `待配置/待标定`。

## 8. 故障贡献排序模型

故障贡献排序用于解释“为什么系统认为某台风机或某个样本异常”。

### 8.1 贡献分数

```text
contribution_j = weight_j * normalized_anomaly_j * data_reliability_j
```

其中：

| 参数 | 含义 |
|---|---|
| `weight_j` | 指标权重 |
| `normalized_anomaly_j` | 归一化异常程度 |
| `data_reliability_j` | 数据可靠性，来自数据质量评分 |

排序：

```text
rank = sort(contribution_j, descending)
```

### 8.2 证据链要求

每个贡献项必须同时输出：

- 指标名称；
- 计算窗口；
- 数据源；
- 源文件或源表；
- 异常值；
- 基线值；
- 偏离程度；
- 是否来自同一资产同一时间。

如果某项来自诊断样本库，应标记：

```text
alignment_scope = method_demo_only_not_same_asset_as_care
```

## 9. RUL预测模型

RUL 用于估计剩余寿命或剩余维护窗口。当前阶段只设计基础模型，不声称工业级预测已经验证。

### 9.1 基于HI趋势的线性退化模型

设 `HI(t)` 随时间下降，可用最近窗口拟合退化斜率：

```text
HI(t) = alpha + beta * t
```

失效阈值为 `HI_failure`，则：

```text
RUL = (HI_failure - HI_current) / beta
```

使用条件：

- `beta < 0` 时才表示退化。
- 如果 `beta >= 0`，不能输出确定 RUL，只能显示“当前趋势未呈退化”。
- `HI_failure` 需要标定或配置。

### 9.2 基于风险评分的维护窗口

```text
risk_score = r1 * HI_risk
           + r2 * fault_probability
           + r3 * data_quality_risk
           + r4 * operating_severity
```

输出：

```text
maintenance_window = rule_based_mapping(risk_score)
```

例如输出“建议近期复核”“建议安排检修窗口”，而不是在无验证时给出精确寿命承诺。

### 9.3 置信区间

如果使用回归模型，可以输出：

```text
RUL_lower = RUL_estimate - uncertainty_margin
RUL_upper = RUL_estimate + uncertainty_margin
```

`uncertainty_margin` 应由模型误差、数据质量和历史验证结果计算，不能凭空设置。

## 10. 维护成本决策模型

维护成本模型用于比较立即检修、延迟检修、降载运行等策略。

### 10.1 立即检修成本

```text
C_now = C_labor + C_parts + C_vehicle + C_downtime_now + C_other
```

### 10.2 延迟检修期望成本

```text
C_delay = p_failure * C_failure_repair
        + E[downtime_hours] * C_downtime_per_hour
        + C_generation_loss
        + C_secondary_damage
```

### 10.3 发电损失

```text
C_generation_loss = lost_energy_kWh * electricity_price
```

```text
lost_energy_kWh = expected_power_kW * downtime_hours
```

### 10.4 策略比较

```text
best_strategy = argmin(C_strategy)
```

业务参数来源：

| 参数 | 来源 |
|---|---|
| 人工成本 | 用户录入或真实业务数据 |
| 备件成本 | 库存/采购系统或用户录入 |
| 停机损失 | 用户配置 |
| 电价 | 用户配置或业务系统 |
| 故障概率 | 诊断/RUL模型 |

当前不能预置伪造成本。

## 11. 工单优先级模型

工单优先级用于维护日历、派工和备件计划。

```text
priority_score = q1 * severity_score
               + q2 * HI_risk
               + q3 * RUL_urgency
               + q4 * cost_risk
               + q5 * data_reliability
               + q6 * part_availability
```

参数说明：

| 参数 | 含义 | 来源 |
|---|---|---|
| `severity_score` | 故障严重度 | 诊断模型或人工录入 |
| `HI_risk` | HI风险 | HI模型 |
| `RUL_urgency` | RUL紧急程度 | RUL模型 |
| `cost_risk` | 成本风险 | 成本模型 |
| `data_reliability` | 数据可靠性 | 数据质量模型 |
| `part_availability` | 备件可用性 | 真实库存或用户录入 |

权重 `q1` 至 `q6` 属于项目业务规则，需配置或后续标定。

## 12. 页面总结模型

页面总结不是纯数学模型，但应由结构化指标驱动，防止编造。

### 12.1 输入

- 当前页面类型；
- 当前筛选条件；
- 风机列表；
- HI摘要；
- SCADA摘要；
- 诊断结果；
- RUL结果；
- 工单状态；
- 数据质量标记。

### 12.2 输出规则

输出三类内容：

```text
summary = top_3_findings + actionable_suggestions + data_quality_notice
```

如果数据缺失：

```text
summary = missing_data_explanation + next_required_data
```

页面总结不得输出没有数据支撑的故障、成本或维护结论。

## 13. 参数管理表

后续建议把参数配置成结构化文件或数据库表。

| 参数名 | 所属模型 | 含义 | 来源类型 | 当前状态 |
|---|---|---|---|---|
| `fs` | 振动模型 | 采样率 | 数据集说明 | NREL待确认，Mendeley说明为1kHz |
| `window_size` | 振动模型 | 分析窗口长度 | 算法配置 | 待配置 |
| `P_rated` | SCADA模型 | 额定功率 | CARE/真实台账 | 待导入 |
| `P_expected(v)` | SCADA模型 | 正常功率曲线 | 真实数据拟合 | 待CARE |
| `temp_baseline` | SCADA模型 | 正常温度基线 | 真实数据拟合 | 待CARE |
| `w_power` | HI模型 | 功率异常权重 | 项目配置/标定 | 待标定 |
| `w_temp` | HI模型 | 温度异常权重 | 项目配置/标定 | 待标定 |
| `w_vibration` | HI模型 | 振动异常权重 | 项目配置/标定 | 待标定 |
| `w_image` | HI模型 | 图像损伤权重 | 项目配置/标定 | 待标定 |
| `HI_failure` | RUL模型 | 失效阈值 | 标定/配置 | 待标定 |
| `C_downtime_per_hour` | 成本模型 | 单小时停机损失 | 用户录入 | 待录入 |
| `C_parts` | 成本模型 | 备件成本 | 真实库存/用户录入 | 待录入 |
| `q1...q6` | 工单优先级 | 优先级权重 | 业务配置 | 待配置 |

来源类型建议统一为：

- `行业通用公式`
- `标准/文献支持`
- `数据集元数据`
- `真实数据拟合`
- `用户配置`
- `业务系统导入`
- `待标定`

## 14. 后续标定流程

### 14.1 振动指标标定

1. 读取 NREL `.mat` 和 Mendeley CSV/XLSX。
2. 统一提取波形、采样率、通道、标签。
3. 计算 RMS、峭度、波峰因子、频谱主峰等指标。
4. 对比健康/损伤样本的指标分布。
5. 选择区分能力强的指标进入 `S_vibration`。
6. 记录每个阈值的来源和验证结果。

### 14.2 图像指标标定

1. 解压 YOLO 标注图像。
2. 检查图片和标签配对率。
3. 计算 bbox 面积占比、目标数量和类别分布。
4. 建立初始严重度规则。
5. 不输出模型置信度，除非后续训练真实检测模型。

### 14.3 SCADA指标标定

1. CARE 下载完成后校验并解压。
2. 识别时间戳、风机编号和 SCADA 字段。
3. 按正常运行段拟合功率曲线和温度基线。
4. 计算功率偏差、温度残差和数据质量。
5. 根据故障窗口检验异常指标是否提前变化。
6. 标定 HI 分项权重和阈值。

### 14.4 业务参数标定

1. 从系统工单真实积累维修记录。
2. 用户录入成本、备件、人员、库存参数。
3. 根据历史结果修正成本模型。
4. 不使用无来源的成本常数。

## 15. 与用户故事的对应关系

| 用户故事 | 依赖模型 |
|---|---|
| US01 地图查看所有风机状态 | 数据质量、SCADA状态、HI |
| US02 按机型/HI/区域筛选 | HI、风机台账、区域标签 |
| US03 查询单台指标 | SCADA运行指标、数据质量 |
| US04 自动识别故障类型 | SCADA异常、振动诊断、图像损伤、贡献排序 |
| US05 叶片图像定位损伤 | YOLO bbox、图像损伤严重度 |
| US06 查看振动波形 | 振动时域/频域指标 |
| US07 故障指数排序 | 贡献排序、HI分项 |
| US08 RUL预测 | HI趋势、风险评分、SCADA故障窗口 |
| US09 维护成本对比 | 成本模型、故障概率、停机损失 |
| US10 维护日历和备件提示 | RUL、工单优先级、库存参数 |
| US11 工单流程管理 | 工单优先级、成本模型 |
| US12 HI阈值和通知渠道 | HI阈值、配置管理 |
| US13 页面总结 | 所有指标摘要、数据质量说明 |
| US14 数据源监控 | 数据质量模型、数据源状态 |

## 16. 实现建议

建议后续新增以下模块：

```text
backend/app/services/modeling/
  data_quality.py
  scada_features.py
  vibration_features.py
  image_features.py
  health_index_v2.py
  fault_ranking.py
  rul.py
  maintenance_cost.py
  workorder_priority.py
```

每个模块至少提供：

- `compute_features(input)`;
- `explain_result(result)`;
- `validate_input(input)`;
- `source_metadata`;
- `quality_flags`;
- 单元测试。

建议新增参数配置文件：

```text
backend/config/model_parameters.example.json
```

真实参数可以存在数据库或本地未提交配置中，避免把未经验证的参数当作固定结论。

## 17. 参考依据

- ISO 13379-1：机器状态监测和故障诊断的数据解释与诊断技术通用指南。ISO 页面显示 2012 版已撤回，并有 2025 新版本可用。后续引用时应优先核对最新版。  
  https://www.iso.org/standard/39836.html

- ISO 13381-1：机器状态监测与故障诊断中的预后预测通用指南。  
  https://www.iso.org/standard/51436.html

- IEC 61400-12-1：风电机组功率性能测量，与功率曲线分析相关。  
  https://webstore.iec.ch/en/publication/68499

- CARE to Compare v6 SCADA 数据集。  
  https://zenodo.org/records/15846963

- NREL/OEDI 齿轮箱振动状态监测数据集。  
  https://data.openei.org/submissions/738

## 18. 当前结论

当前可以先实现公式和参数框架，但不能提前写死阈值和权重。后续真实数据到位后，按照“读取数据、计算指标、检查分布、标定参数、记录来源、验证效果”的顺序推进。

