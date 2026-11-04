FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --upgrade pip \
    && pip install -e .

COPY . .

EXPOSE 8000

# 워커 클래스·워커 수·바인드·로그 설정은 gunicorn.conf.py 한 곳에서
CMD ["gunicorn", "-c", "gunicorn.conf.py", "app.main:app"]
