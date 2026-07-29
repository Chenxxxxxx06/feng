"""行业模板实例化脚本 —— 把风电 Playbook 变成目标行业的可运行适配包。

【解决什么问题】
``open_phm_api_service.get_industry_templates()`` 里的光伏 / 水泵 / 压缩机模板原先只是
静态 JSON 描述，没有实例化路径，「可迁移」停留在口号。本脚本消费模板里**机器可读**的
``term_mapping / metric_mapping / fault_mapping``，把 Agent Playbook 知识库
（实体定义、指标名、故障类型、工作流、原子动作、只读任务）按映射批量替换，
生成一份**可验证**的适配包，并当场重跑引用一致性校验证明替换后知识库仍然自洽。

【产物】``backend/exports/<industry>/``
    README.md                     中文使用说明（如何接入自有 SCADA / 数据源）
    manifest.json                 版本、来源、替换统计、逐文件 SHA-256 校验和
    mapping.json                  完整术语 / 指标 / 故障映射表
    adapter_config.json           适配器配置样例（资产类型、指标清单、数据源契约）
    knowledge_base/*.json         映射替换后的四个 Playbook 知识库文件
    openapi.json                  适配后的开放 API 规范
    client.py                     适配后的 Python 客户端 SDK

用法：
    python scripts/instantiate_industry_template.py --help
    python scripts/instantiate_industry_template.py all
    python scripts/instantiate_industry_template.py photovoltaic
    python scripts/instantiate_industry_template.py pump --output-dir exports
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.agent_playbooks.loader import KB_FILES, KNOWLEDGE_BASE_DIR  # noqa: E402
from app.services.open_phm_api_service import OpenPHMAPIService  # noqa: E402

DEFAULT_OUTPUT_ROOT = BACKEND_ROOT / "exports"
PACKAGE_FORMAT = "windops-industry-adapter/1.0"

OK = "[OK]"
NG = "[NG]"


# ── 术语替换 ──


def _expand_mapping(mapping: dict[str, str]) -> dict[str, str]:
    """扩充映射：为纯 ASCII 词条自动补上首字母大写形式，避免 Turbine/turbine 漏替换。"""
    expanded = dict(mapping)
    for src, dst in mapping.items():
        if src.isascii() and src[:1].isalpha():
            cap_src, cap_dst = src[0].upper() + src[1:], dst[0].upper() + dst[1:]
            expanded.setdefault(cap_src, cap_dst)
    return expanded


def _substitute(text: str, mapping: dict[str, str]) -> tuple[str, dict[str, int]]:
    """按「最长词条优先」单遍替换，返回 (新文本, 每个词条命中次数)。

    单遍替换（一次正则扫描）可以避免「A→B 之后 B 又被 B→C 替换」的级联污染。
    """
    if not mapping:
        return text, {}
    keys = sorted(mapping, key=len, reverse=True)
    pattern = re.compile("|".join(re.escape(k) for k in keys))
    hits: dict[str, int] = {}

    def _repl(match: re.Match[str]) -> str:
        key = match.group(0)
        hits[key] = hits.get(key, 0) + 1
        return mapping[key]

    return pattern.sub(_repl, text), hits


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical(data: Any) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


# ── 一致性复核 ──


def _recheck_references(kb: dict[str, Any]) -> list[str]:
    """替换后重跑引用一致性检查，证明适配包依然自洽（不是乱替换）。"""
    errors: list[str] = []
    action_ids = {a.get("id") for a in kb["primitive_actions"].get("actions", []) if a.get("id")}

    for workflow in kb["advanced_workflows"].get("workflows", []):
        wid = workflow.get("id")
        for step in workflow.get("standard_workflow", []):
            step_id = step.get("step")
            if step_id and step_id not in action_ids:
                errors.append(f"workflow {wid} 引用了未登记的步骤：{step_id}")
        for action_id in workflow.get("allowed_actions", []):
            if action_id and action_id not in action_ids:
                errors.append(f"workflow {wid} 允许了未登记的动作：{action_id}")

    for task in kb["read_tasks"].get("tasks", []):
        tid = task.get("id")
        for step in task.get("standard_workflow", []):
            step_id = step.get("step")
            if step_id and step_id not in action_ids:
                errors.append(f"read_task {tid} 引用了未登记的步骤：{step_id}")
        for action_id in task.get("allowed_actions", []):
            if action_id and action_id not in action_ids:
                errors.append(f"read_task {tid} 允许了未登记的动作：{action_id}")

    ids = [w.get("id") for w in kb["advanced_workflows"].get("workflows", [])]
    if len(ids) != len(set(ids)):
        errors.append("替换后出现重复的 workflow id")
    return errors


# ── README ──


def _render_readme(template: dict[str, Any], stats: dict[str, Any], stamp: datetime) -> str:
    name = template["name"]
    domain = template["domain"]
    cfg = template.get("example_config", {})
    metrics = cfg.get("metrics", [])
    return f"""# {domain} PHM 适配包（{name}）

> 由 `backend/scripts/instantiate_industry_template.py` 从「风调预顺」风电 PHM 平台
> 自动实例化生成，生成时间 {stamp.isoformat()}。
> 本目录是**产物**，可整体复制到目标行业项目中使用。

## 1. 这个包是什么

平台的 Agent 决策能力由一套 Playbook 知识库驱动（实体定义 / 原子动作 / 只读任务 /
高级工作流）。本适配包把风电领域的实体、指标名、故障类型按 `mapping.json` 的映射表
批量替换成 **{domain}** 的术语，同时保持工作流结构、风险等级、人工确认约束不变。

替换后已重新跑过引用一致性校验：{stats['recheck']}

| 产物 | 说明 |
| --- | --- |
| `knowledge_base/entities.json` | 实体定义（{stats['counts']['entities']} 个实体） |
| `knowledge_base/primitive_actions.json` | 原子动作登记表（{stats['counts']['primitive_actions']} 个） |
| `knowledge_base/read_tasks.json` | 只读任务（{stats['counts']['read_tasks']} 个） |
| `knowledge_base/advanced_workflows.json` | 高级工作流（{stats['counts']['advanced_workflows']} 个） |
| `mapping.json` | 术语 / 指标 / 故障映射表（共替换 {stats['total_replacements']} 处） |
| `adapter_config.json` | 数据源适配契约 + 资产配置样例 |
| `openapi.json` | 适配后的开放 API 规范 |
| `client.py` | 适配后的 Python 客户端 SDK |
| `manifest.json` | 版本、来源、逐文件 SHA-256 校验和 |

## 2. 关键实体与指标

- 关键实体：{"、".join(template.get("key_entities", []))}
- 关键指标：{"、".join(template.get("key_metrics", []))}
- 典型故障：{"、".join(template.get("fault_types", []))}
- 适配要点：{template.get("adapter_notes", "")}

## 3. 接入自有 SCADA / 数据源（三步）

### 第一步：实现数据源适配器

参考 `adapter_config.json` 的 `data_contract`，实现一个把你的数据源
（OPC UA / Modbus / MQTT / 关系库 / CSV）转换成统一时序记录的加载器：

```python
# my_scada_loader.py
from datetime import datetime

REQUIRED_FIELDS = {json.dumps(metrics, ensure_ascii=False)}

def load_records(asset_id: str, start: datetime, end: datetime) -> list[dict]:
    \"\"\"返回 [{{"asset_id":..., "ts": datetime, "<metric>": float, ...}}]。\"\"\"
    raise NotImplementedError
```

字段命名对齐 `adapter_config.json -> metrics`，缺失指标请显式置 `None`，
不要用 0 填充——平台的数据质量标注依赖 `None` 区分「缺失」与「真实为零」。

### 第二步：替换资产台账

把 `knowledge_base/entities.json` 中实体的 `resolver` / `primary_fields`
指向你自己的资产表，保持 `id` 不变即可复用全部工作流。

### 第三步：挂接动作网关

`primitive_actions.json` 中每个动作的 `implemented_by` 指向平台内的实现函数。
迁移时把它替换成你系统里的等价实现；未实现的动作会被 Agent 网关拒绝执行
（fail-closed），不会产生未定义行为。

## 4. 安全与合规约束（务必保留）

- 所有写动作必须位于 `require_confirmation` 之后 —— 人工确认不可绕过。
- 高风险工作流保留 `risk_level: high` 标注，网关据此强制二次确认。
- Agent 执行轨迹建议接入审计链（SHA-256 链 + Ed25519 根签名），
  参见平台 `backend/app/services/audit_chain_service.py`。

## 5. 校验产物完整性

```bash
python - <<'PY'
import hashlib, json, pathlib
m = json.loads(pathlib.Path("manifest.json").read_text(encoding="utf-8"))
for rel, sha in m["files"].items():
    actual = hashlib.sha256(pathlib.Path(rel).read_bytes()).hexdigest()
    print(("OK " if actual == sha else "BAD"), rel)
PY
```

## 6. 许可

Apache-2.0，与上游平台一致。术语映射表可按需扩展 `mapping.json` 后重新运行实例化脚本。
"""


# ── 主流程 ──


def instantiate(template: dict[str, Any], output_root: Path, quiet: bool = False) -> dict[str, Any]:
    """实例化一个行业模板，返回统计信息。"""
    name = template["name"]
    stamp = datetime.now(timezone.utc)
    out_dir = output_root / name
    kb_dir = out_dir / "knowledge_base"
    kb_dir.mkdir(parents=True, exist_ok=True)

    mapping = _expand_mapping({
        **template.get("term_mapping", {}),
        **template.get("metric_mapping", {}),
        **template.get("fault_mapping", {}),
    })

    hits_total: dict[str, int] = {}
    counts: dict[str, int] = {}
    kb_out: dict[str, Any] = {}
    item_keys = {
        "entities": "entities",
        "primitive_actions": "actions",
        "read_tasks": "tasks",
        "advanced_workflows": "workflows",
    }

    for label, filename in KB_FILES.items():
        raw = (KNOWLEDGE_BASE_DIR / filename).read_text(encoding="utf-8")
        replaced, hits = _substitute(raw, mapping)
        for key, count in hits.items():
            hits_total[key] = hits_total.get(key, 0) + count
        data = json.loads(replaced)
        data["adapted_for"] = {"industry": name, "domain": template["domain"], "source": "windops-phm"}
        counts[label] = len(data.get(item_keys[label], []) or [])
        kb_out[label] = data
        (kb_dir / filename).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    recheck_errors = _recheck_references(kb_out)
    recheck_text = (
        f"{OK} 全部通过（{counts['advanced_workflows']} 个工作流 + "
        f"{counts['read_tasks']} 个只读任务的每一个步骤/动作引用都能解析）"
        if not recheck_errors else f"{NG} 发现 {len(recheck_errors)} 处引用问题"
    )

    # mapping.json
    (out_dir / "mapping.json").write_text(json.dumps({
        "industry": name,
        "domain": template["domain"],
        "term_mapping": template.get("term_mapping", {}),
        "metric_mapping": template.get("metric_mapping", {}),
        "fault_mapping": template.get("fault_mapping", {}),
        "expanded_rules": len(mapping),
        "replacement_hits": dict(sorted(hits_total.items(), key=lambda kv: -kv[1])),
        "total_replacements": sum(hits_total.values()),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # adapter_config.json
    cfg = template.get("example_config", {})
    (out_dir / "adapter_config.json").write_text(json.dumps({
        "industry": name,
        "domain": template["domain"],
        "asset": cfg,
        "key_entities": template.get("key_entities", []),
        "metrics": cfg.get("metrics", []),
        "key_metrics_display": template.get("key_metrics", []),
        "fault_types": template.get("fault_types", []),
        "data_contract": {
            "record": {
                "asset_id": "string，资产唯一标识",
                "ts": "ISO8601 时间戳（带时区）",
                **{m: "number|null，缺失必须为 null，不得用 0 填充" for m in cfg.get("metrics", [])},
            },
            "sampling_interval_s": 600,
            "quality_flags": ["ok", "missing", "out_of_range", "sensor_fault"],
        },
        "adapter_notes": template.get("adapter_notes", ""),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # openapi.json + client.py（同样做术语替换）
    service = OpenPHMAPIService()
    spec_text, _ = _substitute(json.dumps(service.get_spec(), ensure_ascii=False, indent=2), mapping)
    spec = json.loads(spec_text)
    spec["info"]["title"] = f"{template['domain']} PHM Open API v1.0 (adapted)"
    spec["adapted_for"] = {"industry": name, "domain": template["domain"], "generated_at": stamp.isoformat()}
    (out_dir / "openapi.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")

    client_text, _ = _substitute(service.get_python_client_template(), mapping)
    (out_dir / "client.py").write_text(
        f'"""{template["domain"]} PHM Python Client —— 由行业模板实例化脚本生成。"""\n\n'
        + client_text.split('"""', 2)[-1].lstrip("\n"),
        encoding="utf-8",
    )

    stats = {
        "industry": name,
        "domain": template["domain"],
        "counts": counts,
        "total_replacements": sum(hits_total.values()),
        "distinct_terms_hit": len(hits_total),
        "mapping_rules": len(mapping),
        "recheck": recheck_text,
        "recheck_errors": recheck_errors,
        "output_dir": str(out_dir),
    }

    # README + manifest（manifest 最后生成，覆盖所有已落盘文件）
    (out_dir / "README.md").write_text(_render_readme(template, stats, stamp), encoding="utf-8")

    files_sha: dict[str, str] = {}
    for path in sorted(out_dir.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            files_sha[path.relative_to(out_dir).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {
        "format": PACKAGE_FORMAT,
        "industry": name,
        "domain": template["domain"],
        "generated_at": stamp.isoformat(),
        "generated_by": "backend/scripts/instantiate_industry_template.py",
        "source_platform": "风调预顺 PHM (WindOps)",
        "license": "Apache-2.0",
        "playbook_counts": counts,
        "mapping_rules": len(mapping),
        "total_replacements": stats["total_replacements"],
        "reference_check_passed": not recheck_errors,
        "reference_check_errors": recheck_errors,
        "files": files_sha,
    }
    manifest["checksum"] = _sha256_text(_canonical(manifest))
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    if not quiet:
        print()
        print("-" * 68)
        print(f"行业        : {name} / {template['domain']}")
        print(f"输出目录    : {out_dir}")
        print(f"映射规则    : {len(mapping)} 条（含自动补全的大写变体）")
        print(f"替换命中    : {stats['total_replacements']} 处，覆盖 {stats['distinct_terms_hit']} 个不同词条")
        print(f"知识库条目  : 实体 {counts['entities']} / 动作 {counts['primitive_actions']} / "
              f"只读任务 {counts['read_tasks']} / 工作流 {counts['advanced_workflows']}")
        print(f"引用复核    : {recheck_text}")
        for err in recheck_errors[:10]:
            print(f"              {NG} {err}")
        print(f"产物文件    : {len(files_sha)} 个，包校验和 {manifest['checksum'][:16]}…")
        top = list(sorted(hits_total.items(), key=lambda kv: -kv[1]))[:6]
        print("高频替换    : " + "、".join(f"{k}→{mapping[k]}({v}次)" for k, v in top))
    return stats


def build_parser() -> argparse.ArgumentParser:
    service = OpenPHMAPIService()
    names = [t["name"] for t in service.get_industry_templates()]
    parser = argparse.ArgumentParser(
        prog="instantiate_industry_template.py",
        description="行业模板实例化：把风电 Playbook 生成为目标行业的可运行适配包（开放复用资产）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "可用行业：" + "、".join(names) + "、all\n\n"
            "示例：\n"
            "  python scripts/instantiate_industry_template.py all\n"
            "  python scripts/instantiate_industry_template.py photovoltaic\n"
            "  python scripts/instantiate_industry_template.py pump --output-dir exports\n"
        ),
    )
    parser.add_argument("industry", nargs="?", default="all",
                        choices=names + ["all"], help="目标行业（默认 all，全部生成）")
    parser.add_argument("-o", "--output-dir", default=str(DEFAULT_OUTPUT_ROOT),
                        help="输出根目录（默认 backend/exports）")
    parser.add_argument("-q", "--quiet", action="store_true", help="只输出结论，不打印明细")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_root = Path(args.output_dir)
    if not output_root.is_absolute():
        output_root = BACKEND_ROOT / output_root

    templates = OpenPHMAPIService().get_industry_templates()
    if args.industry != "all":
        templates = [t for t in templates if t["name"] == args.industry]

    print("=" * 68)
    print("行业模板实例化 —— 风电 PHM Playbook → 目标行业适配包")
    print("=" * 68)
    print(f"源知识库    : {KNOWLEDGE_BASE_DIR}")
    print(f"输出根目录  : {output_root}")
    print(f"待生成行业  : {', '.join(t['name'] for t in templates)}")

    failed = 0
    for template in templates:
        stats = instantiate(template, output_root, quiet=args.quiet)
        if stats["recheck_errors"]:
            failed += 1

    print()
    print("=" * 68)
    if failed:
        print(f"{NG} 完成，但有 {failed} 个行业的适配包未通过引用一致性复核。")
        return 1
    print(f"{OK} 全部完成：{len(templates)} 个行业适配包已生成，且均通过引用一致性复核。")
    print(f"   产物位置：{output_root}/<industry>/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
