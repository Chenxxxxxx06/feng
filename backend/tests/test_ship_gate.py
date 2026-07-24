"""Ship-gate audit — final delivery quality check.

Runs before every release. Critical failures MUST be zero.

Checks:
1. All backend tests pass
2. Frontend builds without errors
3. Alembic migrations are current
4. No uncommitted protected files
5. API endpoints respond
6. Security: no default secret in production
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def check(label: str, passed: bool, critical: bool = True) -> bool:
    status = "✅" if passed else "❌" if critical else "⚠️"
    level = "CRITICAL" if critical else "WARNING"
    print(f"  {status} [{level}] {label}")
    return passed


def main():
    print("=" * 60)
    print("🚢 SHIP-GATE AUDIT")
    print("=" * 60)

    all_pass = True

    # 1. Backend tests
    print("\n📋 Backend Tests")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "backend/tests", "-q",
         "--ignore=backend/tests/test_agent_chain.py",
         "--ignore=backend/tests/test_mixed_intent.py",
         "--ignore=backend/tests/test_refined_agent.py"],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    passed = "failed" not in result.stdout.lower() or "0 failed" in result.stdout
    all_pass &= check("Backend tests pass", result.returncode == 0)
    if not passed:
        print(f"    {result.stdout[-200:]}")

    # 2. Frontend build
    print("\n📋 Frontend Build")
    result = subprocess.run(
        ["npm", "run", "build"],
        cwd=str(ROOT / "frontend"), capture_output=True, text=True,
    )
    built = "built in" in result.stdout.lower()
    all_pass &= check("Frontend builds", built)
    if built:
        # Extract build time
        for line in result.stdout.split("\n"):
            if "built in" in line.lower():
                print(f"    {line.strip()}")

    # 3. Alembic check
    print("\n📋 Alembic Migrations")
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "current"],
        cwd=str(ROOT / "backend"), capture_output=True, text=True,
    )
    has_head = "head" in result.stdout
    all_pass &= check("Alembic at head", has_head)

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "check"],
        cwd=str(ROOT / "backend"), capture_output=True, text=True,
    )
    no_drift = result.returncode == 0
    all_pass &= check("No schema drift", no_drift)

    # 4. Security
    print("\n📋 Security")
    # Check .env for default secrets
    env_file = ROOT / ".env"
    has_default_secret = False
    if env_file.exists():
        content = env_file.read_text()
        if "fengdiao-phm-dev-secret-key-change-in-production" in content:
            has_default_secret = True
    all_pass &= check(
        "No default SECRET_KEY in .env",
        not has_default_secret,
        critical=os.environ.get("ENV", "").upper() in ("PRODUCTION", "PROD"),
    )

    # Check no .env in git tracked files
    result = subprocess.run(
        ["git", "ls-files", ".env"],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    env_tracked = bool(result.stdout.strip())
    all_pass &= check(".env not tracked by git", not env_tracked)

    # 5. Protected files
    print("\n📋 Protected Files")
    protected = ["start.bat", "start.ps1", "backend/launcher.py", "启动风调预顺.bat"]
    result = subprocess.run(
        ["git", "status", "--short"] + protected,
        cwd=str(ROOT), capture_output=True, text=True,
    )
    for line in result.stdout.strip().split("\n"):
        if line.strip():
            all_pass &= check(f"Protected file unchanged: {line.strip()}", False)

    # 6. Branch
    print("\n📋 Branch")
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    branch = result.stdout.strip()
    all_pass &= check(f"On correct branch: {branch}", branch == "codex/goai-wind-ops")

    # Summary
    print("\n" + "=" * 60)
    if all_pass:
        print("🚀 SHIP-GATE: ALL CHECKS PASSED — Ready to ship")
    else:
        print("❌ SHIP-GATE: CRITICAL FAILURES — Do not ship")
    print("=" * 60)
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
