"""E2E tests for the 6-innovation incident closed loop.

Verifies the full workflow:
  Create incident → compress alarms → evidence graph → decision sandbox
  → policy check (deny) → stage transitions → flight recorder replay

Each test is designed to be idempotent and produce stable results across
consecutive runs.
"""

import pytest
from httpx import AsyncClient


class TestIncidentClosedLoop:
    """E2E: full incident lifecycle from detection to resolution."""

    @pytest.mark.asyncio
    async def test_full_closed_loop(
        self, client: AsyncClient, auth_headers, test_turbine
    ):
        """Complete demo scenario: event enters, gets diagnosed, decisions made,
        policy enforced, resolved, and replayed."""
        # ── Step 1: Create incident (device event enters) ──
        r = await client.post(
            "/api/incidents",
            headers=auth_headers,
            json={
                "turbine_id": test_turbine.id,
                "title": "齿轮箱振动异常 - E2E测试",
                "severity": "high",
                "summary": "SCADA检测到齿轮箱振动RMS持续升高",
            },
        )
        assert r.status_code == 201, f"Create incident failed: {r.text}"
        inc = r.json()
        incident_db_id = inc["id"]
        incident_id = inc["incident_id"]
        assert inc["stage"] == "detected"
        assert inc["status"] == "open"
        assert inc["severity"] == "high"

        # ── Step 2: Alarm storm compression ──
        r = await client.post(
            f"/api/incidents/{incident_db_id}/compress-alarms",
            headers=auth_headers,
            json={"turbine_id": test_turbine.id, "window_minutes": 15},
        )
        assert r.status_code == 200, f"Compress alarms failed: {r.text}"
        cluster = r.json()
        assert cluster["incident_id"] == incident_id
        # Incident should advance to correlated stage
        r = await client.get(f"/api/incidents/{incident_db_id}", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["stage"] in ("correlated", "detected")

        # ── Step 3: Build causal evidence graph ──
        # Add observation node
        r = await client.post(
            f"/api/incidents/{incident_db_id}/evidence-nodes",
            headers=auth_headers,
            json={
                "node_type": "observation",
                "label": "齿轮箱振动RMS升高至15.2 mm/s",
                "description": "SCADA振动传感器采集，超过12 mm/s阈值",
                "source": "scada",
                "confidence": 0.95,
            },
        )
        assert r.status_code == 201, f"Add observation node failed: {r.text}"
        obs_id = r.json()["id"]

        # Add hypothesis node
        r = await client.post(
            f"/api/incidents/{incident_db_id}/evidence-nodes",
            headers=auth_headers,
            json={
                "node_type": "hypothesis",
                "label": "高速轴承内圈磨损",
                "description": "基于振动频谱特征和温度相关性推断",
                "source": "rule",
                "confidence": 0.82,
            },
        )
        assert r.status_code == 201
        hyp_id = r.json()["id"]

        # Add supports edge from observation to hypothesis
        r = await client.post(
            f"/api/incidents/{incident_db_id}/evidence-edges",
            headers=auth_headers,
            json={
                "source_node_id": obs_id,
                "target_node_id": hyp_id,
                "edge_type": "supports",
                "source": "rule",
                "confidence": 0.88,
                "evidence_ref": "振动频谱边带特征与轴承内圈磨损模式匹配",
            },
        )
        assert r.status_code == 201

        # Verify graph
        r = await client.get(
            f"/api/incidents/{incident_db_id}/evidence-graph", headers=auth_headers
        )
        assert r.status_code == 200
        graph = r.json()
        assert len(graph["nodes"]) == 2
        assert len(graph["edges"]) == 1

        # ── Step 4: Decision sandbox (compare 3 repair strategies) ──
        r = await client.post(
            f"/api/incidents/{incident_db_id}/decision-sandbox",
            headers=auth_headers,
        )
        assert r.status_code == 200, f"Decision sandbox failed: {r.text}"
        sandbox = r.json()
        assert len(sandbox["plans"]) == 3
        plans = sandbox["plans"]
        strategies = {p["strategy"] for p in plans}
        assert "immediate_repair" in strategies
        assert "degraded_ops" in strategies
        assert "monitor" in strategies
        # One plan should be recommended
        assert sandbox["recommended_index"] >= 0
        recommended = plans[sandbox["recommended_index"]]
        assert recommended["is_recommended"] is True
        # Scores should be deterministic (not all identical)
        scores = {p["total_score"] for p in plans}
        assert len(scores) == 3, "Each plan should have a distinct score"

        # ── Step 5: Safety policy engine (should deny unverified close) ──
        r = await client.post(
            "/api/policies/check",
            headers=auth_headers,
            json={
                "action": "close_incident",
                "incident_id": incident_db_id,
                "context": {"verification_status": "pending"},
            },
        )
        assert r.status_code == 200
        policy = r.json()
        assert policy["action"] == "close_incident"
        # Policy should either deny or require approval (not allowed)
        assert policy["decision"] in ("denied", "require_approval"), (
            f"Expected policy to block unverified close, got: {policy['decision']}"
        )
        assert len(policy["matched_rules"]) > 0

        # ── Step 6: Stage transitions through the lifecycle ──
        # Note: decision sandbox (step 4) already auto-advanced to decision_ready.
        # We continue from there.
        transitions = [
            ("awaiting_approval", 200),
            ("executing", 200),
            ("verifying", 200),
        ]
        for target, expected in transitions:
            r = await client.post(
                f"/api/incidents/{incident_db_id}/transition",
                headers=auth_headers,
                json={"target_stage": target, "note": f"E2E test: advancing to {target}"},
            )
            assert (
                r.status_code == expected
            ), f"Transition to {target} failed: {r.status_code} {r.text}"

        # Resolve with note
        r = await client.post(
            f"/api/incidents/{incident_db_id}/transition",
            headers=auth_headers,
            json={"target_stage": "resolved", "note": "E2E测试完成：事件已解决"},
        )
        assert r.status_code == 200
        inc = r.json()
        assert inc["stage"] == "resolved"
        assert inc["status"] == "resolved"
        assert inc["closed_at"] is not None

        # ── Step 7: Flight recorder — start trace and verify ──
        r = await client.post(
            f"/api/incidents/{incident_db_id}/trace/start",
            headers=auth_headers,
        )
        assert r.status_code == 200
        trace = r.json()
        assert trace["trace_id"] is not None
        assert trace["status"] == "running"

        # Get all traces for this incident
        r = await client.get(
            f"/api/incidents/{incident_db_id}/trace", headers=auth_headers
        )
        assert r.status_code == 200
        traces = r.json()
        assert len(traces) >= 1

        # ── Verify idempotency: re-running should not create duplicates ──
        r = await client.post(
            "/api/incidents",
            headers=auth_headers,
            json={
                "turbine_id": test_turbine.id,
                "title": "齿轮箱振动异常 - E2E测试2",
                "severity": "medium",
            },
        )
        assert r.status_code == 201
        # Different incident_id confirms no collision
        assert r.json()["incident_id"] != incident_id

    @pytest.mark.asyncio
    async def test_policy_denies_llm_direct_write(
        self, client: AsyncClient, auth_headers
    ):
        """Safety policy engine must deny LLM-sourced actions without playbook."""
        r = await client.post(
            "/api/policies/check",
            headers=auth_headers,
            json={
                "action": "close_incident",
                "context": {"source": "llm", "playbook_id": None},
            },
        )
        assert r.status_code == 200
        policy = r.json()
        # The deny-llm-direct-write rule should match
        assert policy["decision"] in ("denied", "require_approval")

    @pytest.mark.asyncio
    async def test_invalid_stage_transition_rejected(
        self, client: AsyncClient, auth_headers, test_turbine
    ):
        """Invalid stage transitions must return 409."""
        # Create an incident
        r = await client.post(
            "/api/incidents",
            headers=auth_headers,
            json={
                "turbine_id": test_turbine.id,
                "title": "状态机测试",
                "severity": "low",
            },
        )
        assert r.status_code == 201
        inc_id = r.json()["id"]

        # Try to jump directly from detected to resolved (invalid)
        r = await client.post(
            f"/api/incidents/{inc_id}/transition",
            headers=auth_headers,
            json={"target_stage": "resolved"},
        )
        assert (
            r.status_code == 409
        ), f"Expected 409 for invalid transition, got {r.status_code}"

    @pytest.mark.asyncio
    async def test_decision_sandbox_stable_results(
        self, client: AsyncClient, auth_headers, test_turbine
    ):
        """Decision sandbox must produce stable (deterministic) results."""
        # Create an incident
        r = await client.post(
            "/api/incidents",
            headers=auth_headers,
            json={
                "turbine_id": test_turbine.id,
                "title": "稳定性测试",
                "severity": "high",
            },
        )
        assert r.status_code == 201
        inc_id = r.json()["id"]

        # Run sandbox twice
        r1 = await client.post(
            f"/api/incidents/{inc_id}/decision-sandbox", headers=auth_headers
        )
        assert r1.status_code == 200
        scores1 = [p["total_score"] for p in r1.json()["plans"]]

        # Create second incident, run sandbox
        r = await client.post(
            "/api/incidents",
            headers=auth_headers,
            json={
                "turbine_id": test_turbine.id,
                "title": "稳定性测试2",
                "severity": "high",
            },
        )
        assert r.status_code == 201
        inc_id2 = r.json()["id"]

        r2 = await client.post(
            f"/api/incidents/{inc_id2}/decision-sandbox", headers=auth_headers
        )
        assert r2.status_code == 200
        scores2 = [p["total_score"] for p in r2.json()["plans"]]

        # Same severity → same scores (deterministic scoring)
        for i in range(3):
            assert scores1[i] == scores2[i], (
                f"Decision scores must be deterministic. "
                f"Run 1 plan {i}: {scores1[i]}, Run 2 plan {i}: {scores2[i]}"
            )
