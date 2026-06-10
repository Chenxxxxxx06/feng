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

from datetime import datetime, timezone, timedelta

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.models import User, Turbine, Fault, WorkOrder, RULPrediction, BladeImage, DataSource, SCADARecord
from app.core.security import hash_password
from app.api.diagnosis import _vibration_diagnosis


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
    async def test_turbine_scada_returns_historical_dataset_window(self, client: AsyncClient, auth_headers, test_turbine, db_session):
        """Test imported historical SCADA data is returned with explicit provenance."""
        old_ts = datetime.now(timezone.utc) - timedelta(days=30)
        db_session.add(DataSource(
            source_type="scada",
            name="care_to_compare_v6",
            status="connected",
            last_connected_at=datetime.now(timezone.utc),
            last_data_at=old_ts,
            connection_params={"dataset_role": "primary_scada_timeline"},
        ))
        db_session.add(SCADARecord(
            turbine_id=test_turbine.id,
            timestamp=old_ts,
            power_kw=1200.0,
            wind_speed_ms=7.2,
            rotor_rpm=11.5,
            extra={
                "source_dataset": "care_to_compare_v6",
                "source_file": "C:/datasets/care/sample.csv",
                "source_row": 2,
                "source_turbine_id": "WT-01",
            },
        ))
        await db_session.commit()

        response = await client.get(f"/api/turbines/{test_turbine.id}/scada?hours=1", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["dataset_window"] == "historical_latest"
        assert data[0]["data_source"] == "real_dataset"
        assert data[0]["source_dataset"] == "care_to_compare_v6"
        assert data[0]["source_row"] == 2

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
        """Test wind endpoint does not synthesize missing weather data."""
        response = await client.get(f"/api/turbines/{test_turbine.id}/wind", headers=auth_headers)
        assert response.status_code == 404


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
        """Test vibration endpoint does not synthesize missing data."""
        response = await client.get(
            f"/api/diagnosis/vibration?turbine_id={test_turbine.id}",
            headers=auth_headers
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_blade_images(self, client: AsyncClient, auth_headers, test_turbine):
        """Test blade image endpoint returns only imported dataset records."""
        response = await client.get(
            f"/api/diagnosis/blade-images?turbine_id={test_turbine.id}",
            headers=auth_headers
        )
        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_blade_diagnosis_explains_imported_annotation(self, client: AsyncClient, auth_headers, test_turbine, db_session):
        """Test blade diagnosis keeps missing confidence and file status explicit."""
        image = BladeImage(
            turbine_id=test_turbine.id,
            timestamp=datetime.now(timezone.utc),
            image_path="blade_images/public_blade_dataset/sample.jpg",
            diagnosis_type="crack",
            diagnosis_confidence=None,
            damage_bbox={
                "x": 10,
                "y": 20,
                "w": 30,
                "h": 40,
                "label_source": "YOLO_public_dataset",
                "source_dataset": "public_blade_dataset",
                "source_file": "C:/datasets/sample.jpg",
                "image_width": 640,
                "image_height": 480,
            },
        )
        db_session.add(image)
        await db_session.commit()

        response = await client.post(
            "/api/diagnosis/blade-diagnosis",
            headers=auth_headers,
            json={"turbine_id": test_turbine.id, "image_path": image.image_path},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["confidence"] is None
        assert data["damage_bbox"] == {"x": 10, "y": 20, "w": 30, "h": 40}
        assert data["quality"]["source_dataset"] == "public_blade_dataset"
        assert data["quality"]["file_exists"] is False
        assert "公开标注未提供模型置信度" in data["evidence"]

    def test_vibration_diagnosis_explains_source_label(self):
        """Test vibration explanation is derived from imported payload metadata."""
        diagnosis = _vibration_diagnosis({
            "sample_count": 4096,
            "sample_rate_hz": 10240,
            "rms": 1.25,
            "fault_detected": True,
            "fault_info": {"type": "damaged", "label_source": "public_dataset_label"},
            "quality": {
                "source_dataset": "nrel_grc_gearbox_cm",
                "source_file": "Healthy.zip/example.csv",
                "label_source": "public_dataset_label",
            },
            "peak_frequencies": [{"frequency_hz": 25.0, "amplitude": 0.3}],
        })
        assert diagnosis["status"] == "source_labeled_fault"
        assert diagnosis["confidence"] is None
        assert any("nrel_grc_gearbox_cm" in item for item in diagnosis["evidence"])
        assert any("源数据标签=damaged" in item for item in diagnosis["evidence"])


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
    async def test_cost_comparison(self, client: AsyncClient, auth_headers, test_turbine, db_session):
        """Test cost comparison returns dynamic decision fields."""
        test_turbine.hi_value = 52.0
        db_session.add_all([
            Fault(
                turbine_id=test_turbine.id,
                detected_at=datetime.now(timezone.utc),
                fault_type="bearing_wear",
                confidence=0.9,
                status="open",
                details={"root_cause": "bearing vibration rising"},
            ),
            RULPrediction(
                turbine_id=test_turbine.id,
                component="main_bearing",
                remaining_life_days=24.0,
                confidence_lower=18.0,
                confidence_upper=36.0,
            ),
            WorkOrder(
                turbine_id=test_turbine.id,
                title="historical bearing repair",
                status="completed",
                cost_estimate=80000,
                cost_actual=90000,
            ),
        ])
        await db_session.commit()

        response = await client.post("/api/prediction/cost-comparison", headers=auth_headers, json={
            "turbine_id": test_turbine.id,
            "fault_type": "bearing_wear",
        })
        assert response.status_code == 200
        data = response.json()
        assert "immediate_repair_cost" in data
        assert "delayed_repair_cost" in data
        assert data["delayed_repair_cost"] > data["immediate_repair_cost"]
        assert 0 < data["failure_probability"] <= 1
        assert data["risk_level"] in {"low", "medium", "high"}
        assert isinstance(data["cost_drivers"], list)
        assert data["cost_drivers"]
        assert "estimated_saving" in data
        assert "recommendation" in data

    @pytest.mark.asyncio
    async def test_cost_comparison_turbine_not_found(self, client: AsyncClient, auth_headers):
        """Test cost comparison rejects unknown turbine ids."""
        response = await client.post("/api/prediction/cost-comparison", headers=auth_headers, json={
            "turbine_id": 99999,
            "fault_type": "bearing_wear",
        })
        assert response.status_code == 404


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

    @pytest.mark.asyncio
    async def test_pipeline_status_counts_imported_scada_records(self, client: AsyncClient, auth_headers, test_turbine, db_session):
        """Test pipeline status reads SCADA availability from imported DB records."""
        ts = datetime.now(timezone.utc) - timedelta(days=1)
        db_session.add(DataSource(
            source_type="scada",
            name="care_to_compare_v6",
            status="connected",
            last_connected_at=datetime.now(timezone.utc),
            last_data_at=ts,
        ))
        db_session.add(SCADARecord(
            turbine_id=test_turbine.id,
            timestamp=ts,
            power_kw=900.0,
            extra={"source_dataset": "care_to_compare_v6", "source_file": "sample.csv", "source_row": 2},
        ))
        await db_session.commit()

        response = await client.get("/api/settings/pipeline-status", headers=auth_headers)
        assert response.status_code == 200
        scada = next(item for item in response.json()["sources"] if item["type"] == "scada")
        assert scada["record_count"] == 1
        assert scada["real_data_available"] is True
        assert scada["status"] == "connected"

    @pytest.mark.asyncio
    async def test_data_integration_plan(self, client: AsyncClient, auth_headers):
        """Test data integration plan exposes corrected dataset scheme."""
        response = await client.get("/api/settings/data-integration-plan", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "plan" in data
        assert "current_counts" in data
        assert "layer_status" in data
        assert data["plan"]["version"] == "2026-06-10"
        assert len(data["plan"]["unreasonable_points"]) >= 4
        layer_ids = {item["id"] for item in data["plan"]["layers"]}
        assert {"operational_core", "diagnostic_sample_library", "weather_context", "business_records"} <= layer_ids


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
