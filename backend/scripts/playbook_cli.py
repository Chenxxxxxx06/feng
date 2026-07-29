"""Agent Playbook 知识库 CLI —— 导出 / 导入 / 校验 / 统计。

面向「开放复用」：把平台的 Agent 任务知识库（实体 / 原子动作 / 只读任务 / 高级工作流）
做成**可分发、可校验、可导入**的资产包，让第三方能把这套 Playbook 搬到自己的系统里。

子命令：
    export     导出四个知识库 JSON 为可分发包（含版本号与 SHA-256 校验和）
    import     从包导入并逐文件校验；发现冲突只报告、**默认不覆盖**
    validate   跑 loader.validate_agent_knowledge_base()，输出人类可读中文报告
    stats      统计动作 / 工作流 / 只读任务数量与分类分布

用法示例：
    python scripts/playbook_cli.py --help
    python scripts/playbook_cli.py stats
    python scripts/playbook_cli.py validate
    python scripts/playbook_cli.py export
    python scripts/playbook_cli.py export --output exports/playbook/my_pack.json
    python scripts/playbook_cli.py import --input exports/playbook/xxx.json
    python scripts/playbook_cli.py import --input xxx.json --target /tmp/kb --overwrite
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.agent_playbooks.loader import (  # noqa: E402
    KB_FILES,
    KNOWLEDGE_BASE_DIR,
    validate_agent_knowledge_base,
)

PACKAGE_FORMAT = "windops-playbook-pack/1.0"
DEFAULT_EXPORT_DIR = BACKEND_ROOT / "exports" / "playbook"

# 各知识库文件里承载条目的字段名
ITEM_KEYS = {
    "entities": "entities",
    "primitive_actions": "actions",
    "read_tasks": "tasks",
    "advanced_workflows": "workflows",
}

OK = "[OK]"
NG = "[NG]"
WARN = "[!!]"


# ── 通用工具 ──


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_kb_file(name: str) -> tuple[dict[str, Any], str]:
    """读取知识库文件，返回 (解析后的对象, 原始文本)。"""
    path = KNOWLEDGE_BASE_DIR / name
    text = path.read_text(encoding="utf-8")
    return json.loads(text), text


def _canonical(data: Any) -> str:
    """规范化 JSON（排序键 + 紧凑分隔符），用于稳定校验和。"""
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _title(text: str) -> None:
    print()
    print("=" * 68)
    print(text)
    print("=" * 68)


# ── export ──


def cmd_export(args: argparse.Namespace) -> int:
    """把四个知识库 JSON 打包为单文件可分发包。"""
    stamp = datetime.now(timezone.utc)
    files: dict[str, Any] = {}
    versions: dict[str, str] = {}
    counts: dict[str, int] = {}

    for label, filename in KB_FILES.items():
        data, _raw = _read_kb_file(filename)
        canonical = _canonical(data)
        files[label] = {
            "filename": filename,
            "version": data.get("version", "unknown"),
            "sha256": _sha256_text(canonical),
            "item_count": len(data.get(ITEM_KEYS[label], []) or []),
            "content": data,
        }
        versions[label] = data.get("version", "unknown")
        counts[label] = files[label]["item_count"]

    payload = {
        "format": PACKAGE_FORMAT,
        "package_version": stamp.strftime("%Y%m%d.%H%M%S"),
        "generated_at": stamp.isoformat(),
        "source": "风调预顺 PHM — Agent Playbook 知识库",
        "license": "Apache-2.0",
        "kb_versions": versions,
        "item_counts": counts,
        "files": files,
    }
    # 包级校验和：对去掉 checksum 字段后的规范化内容求 SHA-256
    payload["checksum"] = _sha256_text(_canonical(payload))

    output = Path(args.output) if args.output else (
        DEFAULT_EXPORT_DIR / f"playbook_pack_{stamp.strftime('%Y%m%d_%H%M%S')}.json"
    )
    if not output.is_absolute():
        output = BACKEND_ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    _title("导出 Playbook 知识库分发包")
    print(f"包格式      : {PACKAGE_FORMAT}")
    print(f"包版本      : {payload['package_version']}")
    print(f"包校验和    : {payload['checksum']}")
    print(f"输出文件    : {output}")
    print(f"文件大小    : {output.stat().st_size / 1024:.1f} KB")
    print()
    print(f"{'知识库':<22}{'版本':<14}{'条目数':>8}  SHA-256(前16位)")
    print("-" * 68)
    for label, info in files.items():
        print(f"{label:<22}{info['version']:<14}{info['item_count']:>8}  {info['sha256'][:16]}")
    print("-" * 68)
    print(f"{'合计':<22}{'':<14}{sum(counts.values()):>8}")
    print(f"\n{OK} 导出完成。第三方可用 `import` 子命令校验并导入本包。")
    return 0


# ── import ──


def cmd_import(args: argparse.Namespace) -> int:
    """从分发包导入知识库；校验校验和，冲突时**只报告不覆盖**。"""
    pkg_path = Path(args.input)
    if not pkg_path.is_absolute():
        pkg_path = BACKEND_ROOT / pkg_path
    if not pkg_path.exists():
        print(f"{NG} 找不到分发包：{pkg_path}")
        return 2

    try:
        payload = json.loads(pkg_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"{NG} 分发包不是合法 JSON：{exc}")
        return 2

    _title("导入 Playbook 知识库分发包")
    print(f"分发包      : {pkg_path}")

    # 1. 格式校验
    if payload.get("format") != PACKAGE_FORMAT:
        print(f"{NG} 包格式不匹配：期望 {PACKAGE_FORMAT}，实际 {payload.get('format')}")
        return 2
    print(f"{OK} 包格式    : {payload['format']}")
    print(f"   包版本    : {payload.get('package_version', 'unknown')}")
    print(f"   生成时间  : {payload.get('generated_at', 'unknown')}")

    # 2. 包级校验和
    declared = payload.get("checksum", "")
    recomputed = _sha256_text(_canonical({k: v for k, v in payload.items() if k != "checksum"}))
    if declared != recomputed:
        print(f"{NG} 包校验和不一致，分发包可能已被篡改或损坏")
        print(f"   声明: {declared}")
        print(f"   重算: {recomputed}")
        return 2
    print(f"{OK} 包校验和  : {declared[:32]}… 一致")

    # 3. 逐文件校验 + 与本地对比
    target_dir = Path(args.target) if args.target else KNOWLEDGE_BASE_DIR
    if not target_dir.is_absolute():
        target_dir = BACKEND_ROOT / target_dir
    print(f"   目标目录  : {target_dir}")
    print()

    files = payload.get("files", {})
    missing = [label for label in KB_FILES if label not in files]
    if missing:
        print(f"{NG} 分发包缺少知识库文件：{missing}")
        return 2

    plan: list[tuple[str, str, Path, dict]] = []  # (状态, label, 目标路径, 内容)
    conflicts: list[str] = []
    for label, filename in KB_FILES.items():
        info = files[label]
        content = info["content"]
        canonical = _canonical(content)
        if _sha256_text(canonical) != info.get("sha256"):
            print(f"{NG} {label:<22} 文件级校验和不一致，拒绝导入")
            return 2

        dest = target_dir / info.get("filename", filename)
        if not dest.exists():
            plan.append(("NEW", label, dest, content))
        else:
            local_canonical = _canonical(json.loads(dest.read_text(encoding="utf-8")))
            if local_canonical == canonical:
                plan.append(("SAME", label, dest, content))
            else:
                plan.append(("CONFLICT", label, dest, content))
                conflicts.append(label)

    print(f"{'状态':<10}{'知识库':<22}{'包内版本':<14}{'本地版本'}")
    print("-" * 68)
    for status, label, dest, content in plan:
        local_ver = "-"
        if dest.exists():
            try:
                local_ver = json.loads(dest.read_text(encoding="utf-8")).get("version", "unknown")
            except Exception:
                local_ver = "解析失败"
        flag = {"NEW": "新增", "SAME": "一致", "CONFLICT": "冲突"}[status]
        print(f"{flag:<10}{label:<22}{str(content.get('version', 'unknown')):<14}{local_ver}")
    print("-" * 68)

    if args.dry_run:
        print(f"\n{WARN} --dry-run：仅校验与比对，未写入任何文件。")
        return 1 if conflicts else 0

    written: list[str] = []
    for status, label, dest, content in plan:
        if status == "SAME":
            continue
        if status == "CONFLICT" and not args.overwrite:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(label)

    print()
    if written:
        print(f"{OK} 已写入 {len(written)} 个文件：{', '.join(written)}")
    else:
        print(f"{OK} 无需写入，本地内容与分发包一致。")

    if conflicts:
        if args.overwrite:
            print(f"{WARN} 已按 --overwrite 覆盖冲突文件：{', '.join(conflicts)}")
        else:
            print(f"{WARN} 检测到 {len(conflicts)} 个冲突文件，**未覆盖**：{', '.join(conflicts)}")
            print("     如确认要用分发包内容替换本地内容，请显式加 --overwrite。")
            return 1
    return 0


# ── validate ──


def cmd_validate(args: argparse.Namespace) -> int:
    """跑 loader 的完整性校验，输出中文报告。"""
    _title("Playbook 知识库完整性校验")
    print(f"知识库目录  : {KNOWLEDGE_BASE_DIR}")
    print()

    # 文件级检查
    print("[1/2] 文件与 JSON 语法")
    print("-" * 68)
    all_present = True
    for label, filename in KB_FILES.items():
        path = KNOWLEDGE_BASE_DIR / filename
        if not path.exists():
            print(f"{NG} {label:<22} 文件缺失：{filename}")
            all_present = False
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"{NG} {label:<22} JSON 解析失败：{exc}")
            all_present = False
            continue
        size_kb = path.stat().st_size / 1024
        print(
            f"{OK} {label:<22} version={data.get('version', 'unknown'):<12}"
            f"条目={len(data.get(ITEM_KEYS[label], []) or []):>3}  {size_kb:>6.1f} KB"
        )

    # 引用一致性检查
    print()
    print("[2/2] 引用一致性（工作流步骤 / 允许动作 → 原子动作登记表）")
    print("-" * 68)
    errors = validate_agent_knowledge_base()
    if not errors:
        print(f"{OK} 全部通过：工作流与只读任务引用的每一个 step / allowed_action")
        print("     都能在 primitive_actions 登记表中找到；无重复 workflow id；")
        print("     所有 confirmation_required 的工作流都含 require_confirmation 步骤。")
    else:
        for err in errors:
            print(f"{NG} {err}")

    print()
    print("-" * 68)
    if all_present and not errors:
        print(f"{OK} 校验结论：知识库完整可用，可安全导出分发。")
        return 0
    print(f"{NG} 校验结论：发现 {len(errors)} 处引用问题" + ("，且存在文件级问题。" if not all_present else "。"))
    return 1


# ── stats ──


def _bar(count: int, total: int, width: int = 24) -> str:
    if total <= 0:
        return ""
    filled = max(1, round(count / total * width)) if count else 0
    return "#" * filled + "." * (width - filled)


def _print_distribution(title: str, counter: collections.Counter, total: int) -> None:
    print(f"\n  {title}")
    for key, count in counter.most_common():
        label = str(key) if key is not None else "(未标注)"
        print(f"    {label:<24}{count:>4}  {_bar(count, total)}  {count / total * 100:5.1f}%")


def cmd_stats(args: argparse.Namespace) -> int:
    """统计知识库规模与分布。"""
    _title("Playbook 知识库统计")

    entities, _ = _read_kb_file(KB_FILES["entities"])
    actions_doc, _ = _read_kb_file(KB_FILES["primitive_actions"])
    read_doc, _ = _read_kb_file(KB_FILES["read_tasks"])
    wf_doc, _ = _read_kb_file(KB_FILES["advanced_workflows"])

    actions = actions_doc.get("actions", [])
    tasks = read_doc.get("tasks", [])
    workflows = wf_doc.get("workflows", [])
    entity_list = entities.get("entities", [])

    print(f"{'知识库':<22}{'版本':<14}{'条目数':>8}")
    print("-" * 68)
    print(f"{'实体定义 entities':<22}{entities.get('version', '-'):<14}{len(entity_list):>8}")
    print(f"{'原子动作 actions':<22}{actions_doc.get('version', '-'):<14}{len(actions):>8}")
    print(f"{'只读任务 read_tasks':<22}{read_doc.get('version', '-'):<14}{len(tasks):>8}")
    print(f"{'高级工作流 workflows':<22}{wf_doc.get('version', '-'):<14}{len(workflows):>8}")
    print("-" * 68)
    print(f"{'合计':<22}{'':<14}{len(entity_list) + len(actions) + len(tasks) + len(workflows):>8}")

    print("\n【原子动作】")
    _print_distribution("按动作类型 type 分布：", collections.Counter(a.get("type") for a in actions), len(actions))
    implemented = sum(1 for a in actions if a.get("implemented_by"))
    print(f"\n    已绑定实现 implemented_by：{implemented}/{len(actions)}"
          f"（{implemented / len(actions) * 100:.1f}%）")

    print("\n【高级工作流】")
    _print_distribution("按业务域 category 分布：",
                        collections.Counter(w.get("category") for w in workflows), len(workflows))
    _print_distribution("按风险等级 risk_level 分布：",
                        collections.Counter(w.get("risk_level") for w in workflows), len(workflows))
    _print_distribution("按落地状态 implementation_status 分布：",
                        collections.Counter(w.get("implementation_status") for w in workflows), len(workflows))
    need_confirm = sum(1 for w in workflows if w.get("confirmation_required"))
    print(f"\n    需人工确认 confirmation_required：{need_confirm}/{len(workflows)}"
          f"（{need_confirm / len(workflows) * 100:.1f}%）")

    print("\n【只读任务】")
    _print_distribution("按业务域 category 分布：",
                        collections.Counter(t.get("category") for t in tasks), len(tasks))

    print("\n【实体与枚举】")
    print(f"    实体类型：{', '.join(e.get('id', '?') for e in entity_list)}")
    print(f"    枚举字典：{', '.join((entities.get('enums') or {}).keys())}")

    covered = sorted({w.get("category") for w in workflows} | {t.get("category") for t in tasks} - {None})
    print(f"\n【覆盖业务域】{len(covered)} 个：{', '.join(covered)}")
    return 0


# ── 入口 ──


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="playbook_cli.py",
        description="Agent Playbook 知识库工具：导出 / 导入 / 校验 / 统计（开放复用资产）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python scripts/playbook_cli.py stats\n"
            "  python scripts/playbook_cli.py validate\n"
            "  python scripts/playbook_cli.py export --output exports/playbook/pack.json\n"
            "  python scripts/playbook_cli.py import --input exports/playbook/pack.json --dry-run\n"
        ),
    )
    sub = parser.add_subparsers(dest="command", metavar="子命令")

    p_export = sub.add_parser("export", help="导出四个知识库 JSON 为可分发包（含版本与校验和）")
    p_export.add_argument("-o", "--output", help="输出文件路径（默认 backend/exports/playbook/ 下按时间命名）")
    p_export.set_defaults(func=cmd_export)

    p_import = sub.add_parser("import", help="从分发包导入并校验；冲突只报告、默认不覆盖")
    p_import.add_argument("-i", "--input", required=True, help="分发包路径")
    p_import.add_argument("-t", "--target", help="导入目标目录（默认为项目内知识库目录）")
    p_import.add_argument("--overwrite", action="store_true", help="显式允许覆盖冲突文件")
    p_import.add_argument("--dry-run", action="store_true", help="只校验与比对，不写入任何文件")
    p_import.set_defaults(func=cmd_import)

    p_validate = sub.add_parser("validate", help="校验知识库完整性并输出中文报告")
    p_validate.set_defaults(func=cmd_validate)

    p_stats = sub.add_parser("stats", help="统计动作/工作流/只读任务数量与分类分布")
    p_stats.set_defaults(func=cmd_stats)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
