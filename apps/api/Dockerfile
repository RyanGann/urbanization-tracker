FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml requirements.lock requirements.runtime.lock ./
RUN python -m pip install --upgrade pip && python -m pip install -r requirements.runtime.lock

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
RUN python -m pip install --no-deps .

EXPOSE 8000

CMD alembic upgrade head && uvicorn app.main:app --no-proxy-headers --host 0.0.0.0 --port ${PORT:-8000} --workers ${API_WORKERS:-1}
