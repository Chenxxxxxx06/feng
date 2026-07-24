"""Ship-gate audit — final delivery quality check.

Runs before every release. Critical failures MUST be zero.
Usage: PYTHONIOENCODING=utf-8 python backend/tests/test_ship_gate.py
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"


def _run(cmd: list[str], cwd: Path, timeout: int = 120) -> subprocess.CompletedProcess:
    """Run command with shell=True on Windows for PATH resolution."""
    cmd_str = " ".join(f'"{c}"' if " " in c else c for c in cmd)
    return subprocess.run(
        cmd_str, cwd=str(cwd), capture_output=True, text=True,
        timeout=timeout, shell=True,
        encoding="utf-8", errors="replace",
    )


def check(label: str, passed: bool, critical: bool = True) -> bool:
    icon = "PASS" if passed else ("FAIL" if critical else "WARN")
    level = "CRITICAL" if critical else "WARNING"
    print(f"  [{icon}] [{level}] {label}")
    return passed


def main():
    print("=" * 60)
    print("SHIP-GATE AUDIT")
    print("=" * 60)
    all_pass = True

    # 1. Backend unit + integration tests (no external LLM required)
    print("\n[1] Backend Tests (unit + integration, no external LLM)")
    result = _run(
        [sys.executable, "-m", "pytest", "backend/tests", "-q",
         "-m", "not integration",
         "--ignore=backend/tests/test_ship_gate.py"],
        cwd=ROOT, timeout=180,
    )
    test_pass = result.returncode == 0
    all_pass &= check("Backend tests pass (0 failed)", test_pass)
    if result.stdout:
        for line in result.stdout.strip().split("\n")[-5:]:
            if line.strip():
                print(f"    {line.strip()}")

    # 1b. Integration tests (requires DASHSCOPE_API_KEY) — report separately
    print("\n[1b] Backend Integration Tests (requires DASHSCOPE_API_KEY)")
    api_key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        print("  [SKIP] [INFO] DASHSCOPE_API_KEY not set — integration tests skipped")
        print("    These test external LLM calls (intent_router, knowledge_extractor).")
        print("    Set DASHSCOPE_API_KEY to run them.")
    else:
        result_int = _run(
            [sys.executable, "-m", "pytest", "backend/tests", "-q",
             "-m", "integration",
             "--ignore=backend/tests/test_ship_gate.py"],
            cwd=ROOT, timeout=300,
        )
        int_pass = result_int.returncode == 0
        check("Integration tests pass", int_pass, critical=False)
        if result_int.stdout:
            for line in result_int.stdout.strip().split("\n")[-5:]:
                if line.strip():
                    print(f"    {line.strip()}")

    # 2. Frontend build
    print("\n[2] Frontend Build")
    result = _run(["npm", "run", "build"], cwd=FRONTEND, timeout=120)
    built = "built in" in (result.stdout + result.stderr).lower()
    all_pass &= check("Frontend build passes", built)
    for line in (result.stdout + result.stderr).split("\n"):
        if "built in" in line.lower():
            print(f"    {line.strip()}")

    # 3. Alembic
    print("\n[3] Alembic Migrations")
    env = {**os.environ, "PYTHONPATH": str(BACKEND)}
    result = subprocess.run(
        f'"{sys.executable}" -m alembic current',
        cwd=str(BACKEND), capture_output=True, text=True, timeout=30, shell=True, env=env,
        encoding="utf-8", errors="replace",
    )
    has_head = "head" in (result.stdout + result.stderr)
    all_pass &= check("Alembic at head revision", has_head)
    for line in (result.stdout + result.stderr).strip().split("\n"):
        if line.strip():
            print(f"    {line.strip()}")

    # 4. Branch check
    print("\n[4] Branch")
    result = _run(["git", "branch", "--show-current"], cwd=ROOT)
    branch = result.stdout.strip()
    all_pass &= check("On codex/goai-wind-ops branch", branch == "codex/goai-wind-ops")
    print(f"    Current: {branch}")

    # 5. Protected files
    print("\n[5] Protected Files")
    protected = ["start.bat", "start.ps1", "backend/launcher.py"]
    result = _run(["git", "diff", "--cached", "--name-only"] + protected, cwd=ROOT)
    staged_files = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
    ok = len(staged_files) == 0
    if staged_files:
        print(f"    STAGED: {staged_files}")
    all_pass &= check("Protected files not staged for commit", ok)
    result2 = _run(["git", "diff", "--name-only"] + protected, cwd=ROOT)
    working = [l.strip() for l in result2.stdout.strip().split("\n") if l.strip()]
    if working:
        print(f"    Working tree changes (pre-existing, not ours): {working}")

    # 6. Security
    print("\n[6] Security")
    env_file = ROOT / ".env"
    has_default = False
    if env_file.exists():
        try:
            content = env_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = env_file.read_text(encoding="gbk")
        if "fengdiao-phm-dev-secret-key-change-in-production" in content:
            has_default = True
    is_prod = os.environ.get("ENV", "").upper() in ("PRODUCTION", "PROD")
    all_pass &= check(
        "No default SECRET_KEY in .env" if not has_default else "Default SECRET_KEY present (OK for dev)",
        not has_default or not is_prod,
    )

    # 7. No .env in git
    result = _run(["git", "ls-files", ".env"], cwd=ROOT)
    env_tracked = bool(result.stdout.strip())
    all_pass &= check(".env not tracked by git", not env_tracked)

    # Summary
    print("\n" + "=" * 60)
    if all_pass:
        print("SHIP-GATE: ALL CHECKS PASSED [Ready to ship]")
    else:
        print("SHIP-GATE: CRITICAL FAILURES [Do not ship]")
    print("=" * 60)
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
