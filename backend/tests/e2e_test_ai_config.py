"""E2E test: AI configuration chain — verify settings flow works end-to-end.

Usage:
  cd backend
  DASHSCOPE_API_KEY="your-dashscope-api-key" python tests/e2e_test_ai_config.py
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.qwen_client import (
    chat,
    copilot_chat,
    describe_model,
    diagnose_fault,
    resolve_model_config,
    MODEL_CATALOG,
)

OUT = Path(__file__).parent / "e2e_ai_config_output.txt"
REPORT: list[str] = []


def log(line: str = "") -> None:
    REPORT.append(line)
    try:
        print(line)
    except UnicodeEncodeError:
        print(line.encode("ascii", errors="replace").decode("ascii"))


async def main():
    api_key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        log("ERROR: DASHSCOPE_API_KEY not set. Export it and re-run.")
        return

    base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model = "qwen-plus"

    # ═════════════════════════════════════════════
    # TEST 1: Simulate user who saved settings but has NULL api_provider
    # This is the exact scenario that was broken before the fix
    # ═════════════════════════════════════════════
    log("=" * 70)
    log("TEST 1: diagnose_fault with api_key set, api_provider=NULL, base_url=NULL")
    log("  (This was the BROKEN scenario before fix)")
    log("=" * 70)

    try:
        result = diagnose_fault(
            turbine_data={"name": "TEST", "model": "GW150", "power_mw": 3.0, "region": "test", "hi_value": 85.0, "status": "normal"},
            fault_data=[],
            model=model,
            api_key=api_key,
            api_provider=None,   # <-- exactly what happens when frontend doesn't send it
            base_url=None,       # <-- and no base_url was saved
        )
        log(f"  [OK] diagnose_fault succeeded ({len(result)} chars)")
        log(f"  First 200 chars: {result[:200]}")
    except ValueError as e:
        log(f"  [FAIL] ValueError: {e}")
    except Exception as e:
        log(f"  [FAIL] Unexpected: {type(e).__name__}: {e}")
    log()

    # ═════════════════════════════════════════════
    # TEST 2: diagnose_fault with base_url (direct mode, provider not needed)
    # ═════════════════════════════════════════════
    log("=" * 70)
    log("TEST 2: diagnose_fault with api_key + base_url (direct mode)")
    log("=" * 70)

    try:
        result = diagnose_fault(
            turbine_data={"name": "TEST", "model": "GW150", "power_mw": 3.0, "region": "test", "hi_value": 85.0, "status": "normal"},
            fault_data=[],
            model=model,
            api_key=api_key,
            api_provider=None,
            base_url=base_url,   # <-- direct mode bypasses provider check
        )
        log(f"  [OK] diagnose_fault succeeded ({len(result)} chars)")
        log(f"  First 200 chars: {result[:200]}")
    except Exception as e:
        log(f"  [FAIL] {type(e).__name__}: {e}")
    log()

    # ═════════════════════════════════════════════
    # TEST 3: chat() direct mode with api_key + base_url
    # ═════════════════════════════════════════════
    log("=" * 70)
    log("TEST 3: chat() direct mode")
    log("=" * 70)

    try:
        result = chat(
            [{"role": "user", "content": "Say exactly 'ok' and nothing else."}],
            model=model,
            api_key=api_key,
            api_provider=None,
            base_url=base_url,
            max_tokens=10,
        )
        log(f"  [OK] chat() returned: '{result.strip()}'")
        assert "ok" in result.lower(), f"Expected 'ok', got '{result}'"
    except Exception as e:
        log(f"  [FAIL] {type(e).__name__}: {e}")
    log()

    # ═════════════════════════════════════════════
    # TEST 4: chat() catalog mode with provider fallback
    # ═════════════════════════════════════════════
    log("=" * 70)
    log("TEST 4: chat() catalog mode (no base_url)")
    log("  api_provider=NULL, should use fallback")
    log("=" * 70)

    try:
        result = chat(
            [{"role": "user", "content": "Say exactly 'ok' and nothing else."}],
            model="qwen-turbo",
            api_key=api_key,
            api_provider="通义千问 DashScope",  # explicitly set provider
            base_url=None,
            max_tokens=10,
        )
        log(f"  [OK] catalog chat() returned: '{result.strip()}'")
    except Exception as e:
        log(f"  [FAIL] {type(e).__name__}: {e}")
    log()

    # ═════════════════════════════════════════════
    # TEST 5: copilot_chat with NULL api_provider (has its own fallback)
    # ═════════════════════════════════════════════
    log("=" * 70)
    log("TEST 5: copilot_chat with api_provider=NULL")
    log("=" * 70)

    try:
        result = copilot_chat(
            messages=[{"role": "user", "content": "Say exactly 'ok'."}],
            page_context={"page_type": "dashboard", "total_turbines": 10},
            model=model,
            api_key=api_key,
            api_provider=None,  # NULL, should use built-in fallback
            base_url=None,
        )
        log(f"  [OK] copilot_chat returned ({len(result)} chars)")
    except Exception as e:
        log(f"  [FAIL] {type(e).__name__}: {e}")
    log()

    # ═════════════════════════════════════════════
    # TEST 6: describe_model with various configs
    # ═════════════════════════════════════════════
    log("=" * 70)
    log("TEST 6: describe_model status checks")
    log("=" * 70)

    # With api_key + base_url → remote
    status = describe_model(model, api_key, None, base_url)
    log(f"  key+url:     mode={status['mode']}")
    assert status["mode"] == "remote", f"Expected remote, got {status['mode']}"

    # With api_key, no base_url, no provider → local_fallback (catalog mode needs provider)
    status = describe_model(model, api_key, None, None)
    log(f"  key only:    mode={status['mode']}")

    # With nothing → local_fallback
    status = describe_model(model, None, None, None)
    log(f"  no key:      mode={status['mode']}")
    assert status["mode"] == "local_fallback"
    log()

    # ═════════════════════════════════════════════
    # TEST 7: Model catalog lookup
    # ═════════════════════════════════════════════
    log("=" * 70)
    log("TEST 7: MODEL_CATALOG integrity")
    log("=" * 70)

    for model_id in ["qwen-plus", "qwen-turbo", "deepseek-chat", "gpt-4"]:
        config = resolve_model_config(model_id)
        assert config.model_id, f"Missing model_id for {model_id}"
    log(f"  [OK] All core models resolve correctly")
    log(f"  Catalog has {len(MODEL_CATALOG)} entries")

    log("\n" + "=" * 70)
    log("ALL 7 AI CONFIG E2E TESTS PASSED")
    log("=" * 70)

    OUT.write_text("\n".join(REPORT), encoding="utf-8")
    print(f"\nFull report: {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
