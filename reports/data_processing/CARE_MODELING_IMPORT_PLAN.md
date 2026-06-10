# CARE 主时间线接入计划

## 当前状态

CARE 已生成规范化事件级 SCADA 文件，位置为：

`C:\Users\ASUS\Desktop\fengdiao-pHM\backend\data\modeling\care_to_compare_v6\normalized_events`

本目录包含 95 个事件 CSV。每个文件保留 `timestamp`、`source_turbine_id`、`event_id`、`event_label`、`status_type_id`、`train_test` 和项目标准 SCADA 字段。当前有 95 个事件文件具备风速和功率字段，可用于 SCADA 运行指标；95 个事件文件具备 HI 输入所需的基础 SCADA 与温度字段。

## 数据边界

CARE 风机 ID、时间戳和传感器均为匿名数据。当前不能把 CARE 资产映射成真实经纬度、真实机型或真实额定功率，也不能与 NREL、Mendeley、DTU、YOLO 样本伪造成同一台风机的完整证据链。

## 入库约束

现有 `SCADARecord` 表要求绑定项目内 `turbine_id`。直接把 36 个 CARE 匿名资产写入现有真实风机表会造成事实混淆。因此入库前需要二选一：

1. 增加匿名 CARE 资产台账表或扩展 Turbine 模型，允许 `source_dataset`、`source_asset_id`、`geo_scope=anonymous` 且经纬度为空。
2. 由用户提供真实风机台账，并明确 CARE 是否允许映射到该台账。没有明确来源时不能映射。

## 可执行导入前提

当数据库支持匿名资产后，规范化 CSV 可用现有 SCADA 导入器读取，因为字段名已经对齐：

```powershell
python -m scripts.import_real_datasets scada-csv `
  --path <normalized_event_csv> `
  --dataset-id care_to_compare_v6 `
  --turbine-id <匿名资产对应的内部ID> `
  --timestamp-column timestamp `
  --power-column power_kw `
  --wind-speed-column wind_speed_ms `
  --rotor-rpm-column rotor_rpm `
  --gen-temperature-column gen_temperature_c `
  --gearbox-temperature-column gearbox_temperature_c `
  --bearing-temperature-column bearing_temperature_c `
  --pitch-angle-column pitch_angle_deg `
  --nacelle-direction-column nacelle_direction_deg `
  --grid-frequency-column grid_frequency_hz `
  --ambient-temperature-column ambient_temp_c `
  --source-turbine-column source_turbine_id
```

## 下一步开发

1. 将数据库资产模型改为支持匿名公开数据资产，避免伪造经纬度和机型。
2. 基于 `care_normalized_event_manifest.csv` 建立入库批次日志和字段映射版本。
3. 用正常事件窗口拟合功率曲线与温度基线，再计算 HI 分项。
4. 用 anomaly 事件窗口做 RUL 风险趋势验证，不声称工业级寿命预测已经完成。
