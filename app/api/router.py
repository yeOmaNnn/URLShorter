from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import service
from app.api.schemas import ShortenRequest, ShortenResponse, StatsResponse
from app.core.config import settings
from app.db.base import get_db

router = APIRouter()


def _format_dt(dt) -> str:
    return dt.isoformat() if dt else None

async def rate_limit_guard(request: Request) -> None:
    client_ip = request.client.host if request.client else "unknown"
    if not await service.check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Слишком много запросов",)

@router.post("/shorten", response_model=ShortenResponse, status_code=201, dependencies=[Depends(rate_limit_guard)])
async def shorten_url(body: ShortenRequest, db: AsyncSession = Depends(get_db)):
    try:
        link = await service.create_short_link(
            db, origin=body.url, custom_alias=body.custom_alias,
            expires_in_hours=body.expires_in_hours,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return ShortenResponse(
        short_id=link.short_id,
        short_url=f"{settings.BASE_URL}/{link.short_id}",
        original_url=link.origin,
        expires_at=_format_dt(link.expires_at),
    )


@router.get("/stats/{short_id}", response_model=StatsResponse)
async def get_stats(short_id: str, db: AsyncSession = Depends(get_db)):
    link = await service.get_link_by_short_id(db, short_id)
    if not link:
        raise HTTPException(status_code=404, detail="Ссылка не найдена")


    click_count = await service.get_click_count(db, short_id)

    return StatsResponse(
        short_id=link.short_id,
        original_url=link.origin,
        click_count=click_count,
        created_at=_format_dt(link.created_at),
        expires_at=_format_dt(link.expires_at),
    )


@router.get("/{short_id}")
async def redirect(short_id: str, db: AsyncSession = Depends(get_db)):
    link = await service.get_link_by_short_id(db, short_id)
    if not link:
        raise HTTPException(status_code=404, detail="Ссылка не найдена")

    if link.expires_at and datetime.utcnow() > link.expires_at:
        raise HTTPException(status_code=410, detail="Ссылка истекла")

    clicked = await service.increment_click_count(db, short_id)
    if clicked is None:
        raise HTTPException(status_code=404, detail="Ссылка была удалена")
    return RedirectResponse(url=link.origin, status_code=307)
