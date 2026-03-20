import random
import string
from typing import Optional
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Link
from app.core.config import settings
from app.db.redis_client import get_redis


def generate_short_id(length: int = None) -> str:
    length = length or settings.SHORT_ID_LENGTH
    alphabet = string.ascii_letters + string.digits
    return "".join(random.choices(alphabet, k=length))

def _rate_limit_key(client_ip: str) -> str:
    return f"{settings.RATE_LIMIT_KEY_PREFIX}:{client_ip}"

def _clicks_key(short_id: str) -> str:
    return f"{settings.CLICKS_KEY_PREFIX}:{short_id}"


async def check_rate_limit(client_ip: str) -> bool:
    redis = get_redis()
    key = _rate_limit_key(client_ip)
    count = await redis.incr(key)

    if count == 1:
        await redis.expire(key, settings.RATE_LIMIT_WINDOW)

    return count <= settings.RATE_LIMIT_MAX


async def increment_click_count(db: AsyncSession, short_id: str) -> int:
    redis = get_redis()
    key = _clicks_key(short_id)
    result = await db.execute(
        update(Link).where(Link.short_id == short_id).values(click_count=Link.click_count + 1).returning(Link.click_count))
    await db.commit()
    current_clicks = result.scalar_one_or_none()
    if current_clicks is None:
        return None
    await redis.set(key, current_clicks)
    return await redis.incr(key)


async def get_click_count(db: AsyncSession, short_id: str) -> int:
    redis = get_redis()
    key = _clicks_key(short_id)

    cached = await redis.get(key)
    if cached is not None:
        return int(cached)

    link = await db.scalar(select(Link).where(Link.short_id == short_id))
    if not link:
        return 0

    await redis.set(key, link.click_count)
    return link.click_count


async def create_short_link(db: AsyncSession, origin: str,
                            custom_alias: Optional[str] = None, expires_in_hours: Optional[int] = None) -> Link:
    if custom_alias:
        normalized_alias = custom_alias.strip().lower()
        existing = await db.scalar(select(Link).where(Link.short_id == normalized_alias))
        if existing:
            raise ValueError(f"Alias '{custom_alias}' уже занят")
        short_id = normalized_alias
    else:
        for _ in range(5):
            short_id = generate_short_id()
            existing = await db.scalar(select(Link).where(Link.short_id == short_id))
            if not existing:
                break
        else:
            raise RuntimeError("Ошибка генерации ссылки. ")

    expires_at = None
    if expires_in_hours:
        expires_at = datetime.utcnow() + timedelta(hours=expires_in_hours)

    link = Link(short_id=short_id, origin=origin, expires_at=expires_at)
    db.add(link)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ValueError("Alias уже занят") from exc
    await db.refresh(link)
    return link


async def get_link_by_short_id(db: AsyncSession, short_id: str) -> Optional[Link]:
    return await db.scalar(select(Link).where(Link.short_id == short_id))
