from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.api import service
from app.db.base import Base, get_db
from app.db.models import Link
from app.main import app


class FakeRedis:
    def __init__(self):
        self.store = {}
        self.expire_calls = []
        self.set_calls = []

    async def incr(self, key: str) -> int:
        value = int(self.store.get(key, 0)) + 1
        self.store[key] = value
        return value

    async def expire(self, key: str, ttl: int) -> None:
        self.expire_calls.append((key, ttl))

    async def get(self, key: str):
        return self.store.get(key)

    async def set(self, key: str, value) -> None:
        self.store[key] = value
        self.set_calls.append((key, value))

    async def close(self) -> None:
        pass


class FakeScalarResult:
    def __init__(self, value: int):
        self.value = value

    def scalar_one(self) -> int:
        return self.value


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    factory = async_sessionmaker(bind=db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_engine):
    factory = async_sessionmaker(bind=db_engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    import app.db.redis_client as redis_module
    redis_module.redis_client = FakeRedis()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    redis_module.redis_client = None


@pytest_asyncio.fixture
async def created_link(client):
    response = await client.post("/shorten", json={"url": "https://example.com"})
    return response.json()["short_id"]


@pytest.mark.asyncio
async def test_shorten_creates_short_link_and_returns_201(client, db_session):
    response = await client.post("/shorten", json={"url": "https://example.com"})

    assert response.status_code == 201
    data = response.json()
    assert "short_id" in data and "short_url" in data
    assert data["original_url"] == "https://example.com"

    link = await db_session.scalar(select(Link).where(Link.short_id == data["short_id"]))
    assert link is not None and link.origin == "https://example.com"


@pytest.mark.asyncio
async def test_redirect_returns_307_with_location(client, created_link):
    response = await client.get(f"/{created_link}", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "https://example.com"


@pytest.mark.asyncio
async def test_redirect_increments_click_count(client, created_link, db_session):
    for _ in range(3):
        await client.get(f"/{created_link}", follow_redirects=False)

    link = await db_session.scalar(select(Link).where(Link.short_id == created_link))
    await db_session.refresh(link)
    assert link.click_count == 3


@pytest.mark.asyncio
async def test_stats_returns_correct_click_count(client, created_link):
    for _ in range(2):
        await client.get(f"/{created_link}", follow_redirects=False)

    response = await client.get(f"/stats/{created_link}")
    assert response.status_code == 200
    data = response.json()
    assert data["click_count"] == 2
    assert data["short_id"] == created_link
    assert data["original_url"] == "https://example.com"


@pytest.mark.parametrize("path", [
    "/stats/not_exists",
    "/not_exists",
])
@pytest.mark.asyncio
async def test_returns_404_for_unknown_short_id(client, path):
    response = await client.get(path, follow_redirects=False)
    assert response.status_code == 404


@pytest.mark.parametrize("bad_url", [
    "ftp://files.example.com",
    "not-a-url",
    "just text",
])
@pytest.mark.asyncio
async def test_shorten_rejects_invalid_url(client, bad_url):
    response = await client.post("/shorten", json={"url": bad_url})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_custom_alias_conflict_returns_400(client):
    payload = {"url": "https://example.com", "custom_alias": "myalias"}
    assert (await client.post("/shorten", json=payload)).status_code == 201
    response = await client.post("/shorten", json=payload)
    assert response.status_code == 400
    assert "уже занят" in response.json()["detail"]


@pytest.mark.asyncio
async def test_expired_link_returns_410(client, created_link, db_session):
    link = await db_session.scalar(select(Link).where(Link.short_id == created_link))
    link.expires_at = datetime.utcnow() - timedelta(hours=1)
    await db_session.commit()

    response = await client.get(f"/{created_link}", follow_redirects=False)
    assert response.status_code == 410


@pytest.mark.asyncio
async def test_rate_limit_returns_429_after_limit(client):
    responses = [await client.post("/shorten", json={"url": "https://example.com"}) for _ in range(11)]
    assert all(r.status_code == 201 for r in responses[:10])
    assert responses[10].status_code == 429


@pytest.mark.parametrize("length,expected", [(None, 8), (12, 12)])
def test_generate_short_id_length(length, expected):
    result = service.generate_short_id(length=length) if length else service.generate_short_id()
    assert len(result) == expected


@pytest.mark.asyncio
async def test_check_rate_limit_blocks_after_limit(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(service, "get_redis", lambda: redis)
    monkeypatch.setattr(service.settings, "RATE_LIMIT_KEY_PREFIX", "rate")
    monkeypatch.setattr(service.settings, "RATE_LIMIT_WINDOW", 15)
    monkeypatch.setattr(service.settings, "RATE_LIMIT_MAX", 2)

    assert await service.check_rate_limit("127.0.0.1") is True
    assert await service.check_rate_limit("127.0.0.1") is True
    assert await service.check_rate_limit("127.0.0.1") is False
    assert redis.expire_calls == [("rate:127.0.0.1", 15)]


@pytest.mark.asyncio
async def test_create_short_link_normalizes_custom_alias():
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = lambda *_: None

    link = await service.create_short_link(db, origin="https://example.com", custom_alias="  MyAlias  ")

    assert link.short_id == "myalias"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_short_link_raises_when_alias_exists():
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=object())

    with pytest.raises(ValueError, match="уже занят"):
        await service.create_short_link(db, origin="https://example.com", custom_alias="taken")


@pytest.mark.asyncio
async def test_increment_click_count_updates_db_and_cache(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(service, "get_redis", lambda: redis)
    monkeypatch.setattr(service.settings, "CLICKS_KEY_PREFIX", "clicks")

    db = AsyncMock()
    db.execute = AsyncMock(return_value=FakeScalarResult(3))
    db.commit = AsyncMock()

    result = await service.increment_click_count(db, "abc123")

    assert result == 3
    assert redis.set_calls == [("clicks:abc123", 3)]


@pytest.mark.asyncio
async def test_get_click_count_cache_miss_reads_db(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(service, "get_redis", lambda: redis)
    monkeypatch.setattr(service.settings, "CLICKS_KEY_PREFIX", "clicks")

    db = AsyncMock()
    db.scalar = AsyncMock(return_value=SimpleNamespace(click_count=7))

    count = await service.get_click_count(db, "x1")

    assert count == 7
    assert redis.store["clicks:x1"] == 7