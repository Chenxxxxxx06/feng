"""Pytest configuration and fixtures for PHM system tests."""

import asyncio
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.models import User, Turbine, Fault, WorkOrder, RULPrediction
from app.core.security import hash_password, create_access_token


# Test database URL (SQLite in memory with StaticPool for shared state across connections)
TEST_DATABASE_URL = "sqlite+aiosqlite://"

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def dispose_test_engine_after_suite():
    """Close aiosqlite worker resources so pytest exits cleanly on Windows."""
    yield
    await test_engine.dispose()


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(autouse=True)
async def setup_database():
    """Create tables before each test, drop after."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def override_get_db():
    """Override database dependency for testing."""
    async with TestSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


app.dependency_overrides[get_db] = override_get_db


@pytest_asyncio.fixture
async def db_session():
    """Provide a test database session."""
    async with TestSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession):
    """Create a test user."""
    user = User(
        username="testuser",
        email="test@example.com",
        password_hash=hash_password("testpass123"),
        role="admin",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def auth_headers(test_user: User):
    """Get authentication headers for test user."""
    token = create_access_token({"sub": str(test_user.id)})
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def test_turbine(db_session: AsyncSession):
    """Create a test turbine."""
    turbine = Turbine(
        name="TEST-001",
        model="GW150-3MW",
        power_mw=3.0,
        lat=37.325,
        lng=107.598,
        region="陕北",
        status="normal",
        hi_value=85.0,
        source_dataset="care_to_compare_v6",
        source_asset_id="TEST-ASSET-001",
    )
    db_session.add(turbine)
    await db_session.commit()
    await db_session.refresh(turbine)
    return turbine


@pytest_asyncio.fixture
async def client():
    """Provide async test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def test_rul_prediction(db_session: AsyncSession, test_turbine: Turbine):
    """Create a test RUL prediction."""
    from datetime import datetime, timezone
    pred = RULPrediction(
        turbine_id=test_turbine.id,
        component="主轴承",
        predicted_at=datetime.now(timezone.utc),
        remaining_life_days=180.0,
        confidence_lower=120.0,
        confidence_upper=240.0,
    )
    db_session.add(pred)
    await db_session.commit()
    await db_session.refresh(pred)
    return pred
