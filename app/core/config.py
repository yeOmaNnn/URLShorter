from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    REDIS_URL: str = "redis://localhost:6379/0"
    SHORT_ID_LENGTH: int = 8
    BASE_URL: str = "http://localhost:8000"
    RATE_LIMIT_MAX = 10
    RATE_LIMIT_WINDOW = 60
    RATE_LIMIT_KEY_PREFIX: str = "rate_limit"
    CLICKS_KEY_PREFIX: str = "clicks"

    class Config:
        env_file = ".env"


settings = Settings()
