"""Comprehensive API tests for PHM system.

Tests cover:
- Authentication (register, login, me)
- Turbines (list, detail, SCADA, health)
- Diagnosis (faults, detail, vibration)
- Prediction (RUL, cost comparison)
- Work orders (CRUD, status flow)
- Settings (thresholds, data sources)
- AI services (summary, copilot)
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.models import User, Turbine, Fault, WorkOrder, RULPrediction
from app.core.security import hash_password


# ============================================================
# Authentication Tests
# ============================================================

class TestAuth:
    """Test authentication endpoints."""

    @pytest.mark.asyncio
    async def test_register(self, client: AsyncClient):
        """Test user registration."""
        response = await client.post("/api/auth/register", json={
            "username": "newuser",
            "email": "new@example.com",
            "password": "password123",
            "role": "viewer",
        })
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["user"]["username"] == "newuser"

    @pytest.mark.asyncio
    async def test_register_duplicate(self, client: AsyncClient, test_user):
        """Test duplicate registration fails."""
        response = await client.post("/api/auth/register", json={
            "username": "testuser",
            "email": "another@example.com",
            "password": "password123",
        })
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_login(self, client: AsyncClient, test_user):
        """Test user login."""
        response = await client.post("/api/auth/login", json={
            "username": "testuser",
            "password": "testpass123",
        })
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["user"]["username"] == "testuser"

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, client: AsyncClient, test_user):
        """Test login with wrong password fails."""
        response = await client.post("/api/auth/login", json={
            "username": "testuser",
            "password": "wrongpassword",
        })
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_me(self, client: AsyncClient, auth_headers, test_user):
        """Test get current user info."""
        response = await client.get("/api/auth/me", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "testuser"

    @pytest.mark.asyncio
    async def test_me_unauthorized(self, client: AsyncClient):
        """Test get me without auth fails."""
        response = await client.get("/api/auth/me")
        assert response.status_code == 401


# ============================================================
# Turbine Tests
# ============================================================

class TestTurbines:
    """Test turbine endpoints."""

    @pytest.mark.asyncio
    async def test_list_turbines(self, client: AsyncClient, auth_headers, test_turbine):
        """Test list turbines."""
        response = await client.get("/api/turbines/", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "turbines" in data
        assert data["total"] >= 1

    @pytest.mark.asyncio
    async def test_get_turbine(self, client: AsyncClient, auth_headers, test_turbine):
        """Test get single turbine."""
        response = await client.get(f"/api/turbines/{test_turbine.id}", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "TEST-001"

    @pytest.mark.asyncio
    async def test_get_turbine_not_found(self, client: AsyncClient, auth_headers):
        """Test get non-existent turbine."""
        response = await client.get("/api/turbines/99999", headers=auth_headers)
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_turbine_scada(self, client: AsyncClient, auth_headers, test_turbine):
        """Test get turbine SCADA data."""
        response = await client.get(f"/api/turbines/{test_turbine.id}/scada?hours=1", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_turbine_health(self, client: AsyncClient, auth_headers, test_turbine):
        """Test get turbine health index."""
        response = await client.get(f"/api/turbines/{test_turbine.id}/health", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "hi_value" in data
        assert "status" in data

    @pytest.mark.asyncio
    async def test_turbine_wind(self, client: AsyncClient, auth_headers, test_turbine):
        """Test get turbine wind data."""
        response = await client.get(f"/api/turbines/{test_turbine.id}/wind", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "wind_speed_ms" in data


# ============================================================
# Diagnosis Tests
# ============================================================

class TestDiagnosis:
    """Test diagnosis endpoints."""

    @pytest.mark.asyncio
    async def test_list_faults(self, client: AsyncClient, auth_headers):
        """Test list faults."""
        response = await client.get("/api/diagnosis/faults", headers=auth_headers)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_vibration_data(self, client: AsyncClient, auth_headers, test_turbine):
        """Test get vibration data."""
        response = await client.get(
            f"/api/diagnosis/vibration?turbine_id={test_turbine.id}",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert "waveform" in data or "rms" in data

    @pytest.mark.asyncio
    async def test_blade_images(self, client: AsyncClient, auth_headers, test_turbine):
        """Test get blade images."""
        response = await client.get(
            f"/api/diagnosis/blade-images?turbine_id={test_turbine.id}",
            headers=auth_headers
        )
        assert response.status_code == 200


# ============================================================
# Prediction Tests
# ============================================================

class TestPrediction:
    """Test prediction endpoints."""

    @pytest.mark.asyncio
    async def test_list_rul(self, client: AsyncClient, auth_headers):
        """Test list RUL predictions."""
        response = await client.get("/api/prediction/rul", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "predictions" in data

    @pytest.mark.asyncio
    async def test_cost_comparison(self, client: AsyncClient, auth_headers, test_turbine):
        """Test cost comparison."""
        response = await client.post("/api/prediction/cost-comparison", headers=auth_headers, json={
            "turbine_id": test_turbine.id,
            "fault_type": "bearing_wear",
        })
        assert response.status_code == 200
        data = response.json()
        assert "immediate_repair_cost" in data
        assert "recommendation" in data


# ============================================================
# Work Order Tests
# ============================================================

class TestWorkOrders:
    """Test work order endpoints."""

    @pytest.mark.asyncio
    async def test_list_workorders(self, client: AsyncClient, auth_headers):
        """Test list work orders."""
        response = await client.get("/api/workorders/", headers=auth_headers)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_create_workorder(self, client: AsyncClient, auth_headers, test_turbine):
        """Test create work order."""
        response = await client.post("/api/workorders/", headers=auth_headers, json={
            "turbine_id": test_turbine.id,
            "title": "测试工单",
            "description": "测试描述",
            "cost_estimate": 10000,
        })
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "测试工单"

    @pytest.mark.asyncio
    async def test_update_workorder(self, client: AsyncClient, auth_headers, test_turbine):
        """Test update work order status."""
        # Create first
        create_resp = await client.post("/api/workorders/", headers=auth_headers, json={
            "turbine_id": test_turbine.id,
            "title": "更新测试",
        })
        wo_id = create_resp.json()["id"]

        # Update
        response = await client.put(f"/api/workorders/{wo_id}", headers=auth_headers, json={
            "status": "assigned",
        })
        assert response.status_code == 200
        assert response.json()["status"] == "assigned"


# ============================================================
# Settings Tests
# ============================================================

class TestSettings:
    """Test settings endpoints."""

    @pytest.mark.asyncio
    async def test_get_thresholds(self, client: AsyncClient, auth_headers):
        """Test get thresholds."""
        response = await client.get("/api/settings/thresholds", headers=auth_headers)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_pipeline_status(self, client: AsyncClient, auth_headers):
        """Test get pipeline status."""
        response = await client.get("/api/settings/pipeline-status", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "sources" in data


# ============================================================
# AI Tests
# ============================================================

class TestAI:
    """Test AI endpoints."""

    @pytest.mark.asyncio
    async def test_summary(self, client: AsyncClient, auth_headers):
        """Test AI summary (uses fallback)."""
        response = await client.post("/api/ai/summary", headers=auth_headers, json={
            "page_type": "dashboard",
            "page_data": {},
        })
        assert response.status_code == 200
        data = response.json()
        assert "conclusions" in data
        assert "suggestions" in data

    @pytest.mark.asyncio
    async def test_copilot(self, client: AsyncClient, auth_headers):
        """Test AI copilot (uses fallback)."""
        response = await client.post("/api/ai/copilot", headers=auth_headers, json={
            "messages": [{"role": "user", "content": "你好"}],
            "page_context": {"page_type": "dashboard"},
        })
        assert response.status_code == 200
        data = response.json()
        assert "reply" in data


# ============================================================
# Health Check
# ============================================================

class TestHealth:
    """Test health endpoint."""

    @pytest.mark.asyncio
    async def test_health_check(self, client: AsyncClient):
        """Test health check endpoint."""
        response = await client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "version" in data
