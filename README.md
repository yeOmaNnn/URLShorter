# URL Shortener

Микросервис для сокращения ссылок на FastAPI + PostgreSQL + Redis.

# Что реализовано

- POST /shorten — создать короткую ссылку (поддерживает custom alias и срок жизни)
- GET /{short_id} — редирект на оригинальный URL, счётчик кликов обновляется атомарно
- GET /stats/{short_id} — статистика: количество переходов, дата создания, срок истечения
- Rate limiting — 10 запросов в минуту на один IP через Redis
- Истёкшие ссылки возвращают - 410 Gone

## Запуск через Docker

```bash
cp .env.example .env
docker-compose up --build
```

После запуска:
- API: http://localhost:8000
- Swagger UI: http://localhost:8000/docs

## Локальный запуск

```bash
python -m venv venv
pip install -r requirements.txt
```

Заполнить .env (указать свои DATABASE_URL и REDIS_URL), затем:
```bash
uvicorn app.main:app --reload
```

