# 数据库交接包清单

## 包名称

`fengdiao_dataset_db_handoff_20260611.zip`

## 包内容

| 路径 | 说明 |
|---|---|
| `DB_HANDOFF.md` | 数据库人员交接说明 |
| `database/fengdiao_phm.db` | 已入库 CARE 的 SQLite 数据库 |
| `datasets/care_to_compare_v6_normalized/` | CARE 规范化事件 CSV |
| `datasets/processed_features/` | 振动、图像、CARE 字段映射和 manifest |
| `reports/` | 入库摘要、覆盖评估、schema 升级报告 |
| `scripts/` | 可复核和重建入库的 Python 脚本 |

## 未重复打包的内容

整理后的原始数据目录 `backend/data/curated_datasets` 约 42.61 GiB，未重复放入交接 zip。数据库人员如需追溯原始数据，应在项目本机按该路径读取，或另行制作原始数据归档盘。

## 数据边界

本包内所有数据均来自真实下载或真实处理结果，不包含伪造坐标、伪造机型、伪造额定功率、伪造工单、伪造成本、伪造库存或伪造人员数据。
