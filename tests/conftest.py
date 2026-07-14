"""Shared test fixtures and configuration."""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import JSON, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from agentmesh.main import create_app
from agentmesh.persistence import Base, get_db

# Use an in-memory SQLite for tests (fast, no external deps)
# For integration tests against PostgreSQL, set TEST_DATABASE_URL env var
TEST_DATABASE_URL = "sqlite+aiosqlite:///./test.db"

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
test_session_factory = async_sessionmaker(
    test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# SQLite does not support PostgreSQL JSONB — remap to plain JSON before DDL
@event.listens_for(Base.metadata, "before_create")
def _remap_jsonb_for_sqlite(target, connection, **kw):
    if connection.dialect.name == "sqlite":
        from sqlalchemy.dialects.postgresql import JSONB

        for table in target.tables.values():
            for column in table.columns:
                if isinstance(column.type, JSONB):
                    column.type = JSON()


@pytest_asyncio.fixture(autouse=True)
async def setup_database():
    """Create all tables before each test and drop them after."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide a test database session."""
    async with test_session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Provide an async HTTP test client with DB dependency override."""
    app = create_app()

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
