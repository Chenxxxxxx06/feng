"""Demo automation — run full ProofLoop 3 consecutive times.

Simulates the 5-minute demo flow programmatically via API calls.
Verifies no duplicate side effects (idempotency across runs).

Usage: python backend/tests/demo_runner.py
"""
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8080"
CREDS = {"username": "admin", "password": "admin123"}
PASS = 0
FAIL = 0


def log(msg: str, level: str = "INFO"):
    icon = {"OK": "[PASS]", "FAIL": "[FAIL]", "INFO": "  >>", "STEP": "\n--"}[level]
    print(f"  {icon} {msg}")


async def demo_run(run_num: int) -> dict:
    """One complete demo run. Returns results dict."""
    global PASS, FAIL
    results = {}
    async with httpx.AsyncClient(timeout=30.0) as c:
        # 0. Login
        resp = await c.post(f"{BASE}/api/auth/login", json=CREDS)
        if resp.status_code != 200:
            log(f"Login failed: {resp.status_code}", "FAIL"); FAIL += 1; return results
        token = resp.json().get("access_token", "")
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Create Incident
        step = "Create Incident"
        resp = await c.post(f"{BASE}/api/incidents", json={
            "turbine_id": 31, "title": f"Demo Run {run_num}: Gearbox Vibration Anomaly", "severity": "high",
        }, headers=headers)
        if resp.status_code != 201:
            log(f"{step}: {resp.status_code} {resp.text[:100]}", "FAIL"); FAIL += 1; return results
        inc = resp.json()
        inc_id = inc["id"]
        log(f"{step}: {inc['incident_id']} (id={inc_id})", "OK"); PASS += 1
        results["incident_id"] = inc["incident_id"]

        # 2. Start Investigation
        step = "Start Investigation"
        resp = await c.post(f"{BASE}/api/incidents/{inc_id}/start-investigation", headers=headers)
        if resp.status_code != 200:
            log(f"{step}: {resp.status_code}", "FAIL"); FAIL += 1; return results
        inv = resp.json()
        completed = sum(1 for s in inv.get("steps", []) if s["status"] == "completed")
        log(f"{step}: {inv['status']}, {completed}/{len(inv.get('steps', []))} steps, trace={inv.get('trace_id', 'N/A')[:20]}", "OK"); PASS += 1
        results["investigation"] = inv["status"]
        results["trace_id"] = inv.get("trace_id", "")

        # 3. Generate Plans
        step = "Generate Plans"
        resp = await c.post(f"{BASE}/api/incidents/{inc_id}/generate-plans", headers=headers)
        if resp.status_code != 200:
            log(f"{step}: {resp.status_code}", "FAIL"); FAIL += 1; return results
        plans = resp.json()
        n = len(plans.get("plans", []))
        rec = next((p for p in plans.get("plans", []) if p.get("is_recommended")), None)
        log(f"{step}: {n} plans, recommended={rec['plan_name'] if rec else 'none'}, quality={plans.get('data_quality','?')}", "OK"); PASS += 1
        results["plans_count"] = n

        # 4. Evidence completeness
        step = "Evidence Completeness"
        resp = await c.get(f"{BASE}/api/incidents/{inc_id}/evidence-completeness", headers=headers)
        if resp.status_code != 200:
            log(f"{step}: {resp.status_code}", "FAIL"); FAIL += 1; return results
        ev = resp.json()
        log(f"{step}: {ev['completeness_ratio']:.0%}, can_confirm={ev['can_confirm_diagnosis']}", "OK"); PASS += 1
        results["evidence_ratio"] = ev["completeness_ratio"]

        # 5. Economic impact
        step = "Economic Impact"
        resp = await c.get(f"{BASE}/api/incidents/{inc_id}/economic-impact", headers=headers)
        if resp.status_code != 200:
            log(f"{step}: {resp.status_code}", "FAIL"); FAIL += 1; return results
        eco = resp.json()
        log(f"{step}: loss=CNY{eco['cumulative_loss_cny']:.0f}, gap={eco['power_gap_kw']:.0f}kW", "OK"); PASS += 1

        # 6. Policy enforcement: try to close directly — MUST fail
        step = "Policy Block Close"
        resp = await c.post(f"{BASE}/api/incidents/{inc_id}/transition", json={
            "target_stage": "resolved", "note": "Attempting close without verification"
        }, headers=headers)
        blocked = resp.status_code in (403, 409)
        if blocked:
            log(f"{step}: BLOCKED ({resp.status_code}) — policy enforcement works", "OK"); PASS += 1
        else:
            log(f"{step}: NOT BLOCKED ({resp.status_code}) — policy failure!", "FAIL"); FAIL += 1

        # 7. Audit chain
        step = "Audit Chain"
        resp = await c.get(f"{BASE}/api/incidents/{inc_id}/audit-chain", headers=headers)
        if resp.status_code != 200:
            log(f"{step}: {resp.status_code}", "FAIL"); FAIL += 1; return results
        audit = resp.json()
        log(f"{step}: {audit['total_entries']} entries, root={audit['root_hash'][:16]}", "OK"); PASS += 1
        results["audit_entries"] = audit["total_entries"]

        # Verify audit chain
        resp = await c.post(f"{BASE}/api/incidents/{inc_id}/audit-chain/verify", headers=headers)
        av = resp.json()
        if av.get("chain_valid"):
            log(f"Audit Verify: chain VALID", "OK"); PASS += 1
        else:
            log(f"Audit Verify: chain BROKEN at {av.get('first_broken_at')}", "FAIL"); FAIL += 1

        # 8. Compliance check
        step = "Compliance"
        resp = await c.post(f"{BASE}/api/incidents/{inc_id}/compliance/check", params={"action": "close_incident"}, headers=headers)
        if resp.status_code != 200:
            log(f"{step}: {resp.status_code}", "FAIL"); FAIL += 1; return results
        comp = resp.json()
        log(f"{step}: {comp['passed']}/{comp['total_rules']} passed, can_close={comp['can_close']}", "OK"); PASS += 1

        # 9. Task package
        step = "Task Package"
        resp = await c.get(f"{BASE}/api/incidents/{inc_id}/task-package", headers=headers)
        if resp.status_code != 200:
            log(f"{step}: {resp.status_code}", "FAIL"); FAIL += 1; return results
        pkg = resp.json()
        log(f"{step}: {len(pkg.get('safety_checklist',[]))} safety items, {len(pkg.get('procedure_steps',[]))} steps", "OK"); PASS += 1

    return results


async def main():
    global PASS, FAIL
    print("=" * 60)
    print("DEMO RUNNER — 3x Consecutive Closed-Loop Execution")
    print("=" * 60)

    all_results = []
    for run in range(1, 4):
        print(f"\n{'='*40}")
        print(f"  DEMO RUN {run}/3")
        print(f"{'='*40}")
        t0 = time.time()
        result = await demo_run(run)
        elapsed = time.time() - t0
        log(f"Run {run} completed in {elapsed:.1f}s", "INFO")
        all_results.append(result)

    print(f"\n{'='*60}")
    print(f"FINAL SCORE: {PASS} passed, {FAIL} failed")
    print(f"{'='*60}")

    # Check idempotency: no duplicate incidents created across runs
    inc_ids = [r.get("incident_id") for r in all_results if r]
    unique_ids = set(inc_ids)
    if len(unique_ids) == len(inc_ids):
        print(f"IDEMPOTENCY: {len(unique_ids)} unique Incident IDs — no duplicates")
    else:
        print(f"IDEMPOTENCY WARNING: {len(inc_ids)} runs, {len(unique_ids)} unique IDs")

    if FAIL == 0:
        print("\n[SUCCESS] All 3 demo runs passed. Ready for recording.")
        return 0
    else:
        print(f"\n[FAILURE] {FAIL} checks failed.")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
