from fastapi import FastAPI
from contextlib import asynccontextmanager

from app.api.router import router
from app.db.base import Base, engine
from app.db.redis_client import init_redis, close_redis

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await init_redis()

    yield

    await close_redis()

app = FastAPI(title="URL Shorter", description="Микросервис для сокращения ссылок")

app.include_router(router)

