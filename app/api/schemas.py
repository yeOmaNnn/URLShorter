from typing import Optional
from pydantic import BaseModel, field_validator


class ShortenResponse(BaseModel):
    short_id: str
    short_url: str
    origin: str
    expires_at: Optional[str] = None


class StatsResponse(BaseModel):
    short_id: str
    origin: str
    click_count: int
    created_at: str
    expires_at: Optional[str] = None


class ShortenRequest(BaseModel):
    url: str
    custom_alias: Optional[str] = None
    expires_in_hours: Optional[int] = None


    @field_validator("url")
    @classmethod
    def validator_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("url должен начинаться http:// или https://")
        return v


    @field_validator("custom_alias")
    @classmethod
    def validator_alias(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not v.isalnum() or len(v) < 3 or len(v) > 32:
            raise ValueError("alias должен быть по размеру в диапазоне от 3 до 32 символов")
        return v


    @field_validator("expires_in_hours")
    @classmethod
    def validate_expiry(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v <= 0:
            raise ValueError("expires_in_hours должен быть больше нуля")
        return v



