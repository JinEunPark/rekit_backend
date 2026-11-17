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

# 빌드 게이트 — Jenkins build-was 가 `--target test` 로 먼저 빌드한다. 하나라도 실패하면
# 잡이 멈춰 운영 이미지가 registry 에 올라가지 않고, 따라서 그 태그는 배포할 이미지가 없다.
# 실제 PostgreSQL·Redis 가 필요한 테스트(tests/integration 과 infra 마커)는 여기서 제외한다.
FROM base AS test
RUN pip install -e ".[dev]"
# 빌드 단계에는 .env 가 없다 — 기본값 없는 설정을 테스트 전용 더미 값으로 채운다 (이 단계에만 존재)
ENV DATABASE_URL=postgresql+asyncpg://test:test@localhost:5432/test \
    JWT_SECRET=test-only-jwt-secret \
    TOSS_SECRET_KEY=test_sk_dummy \
    S3_ENDPOINT_URL=http://localhost:8333 \
    S3_BUCKET=test-bucket \
    S3_ACCESS_KEY=test \
    S3_SECRET_KEY=test \
    S3_PUBLIC_URL_BASE=http://localhost:8333/test-bucket
RUN ruff check app tests \
    && mypy app \
    && pytest --ignore=tests/integration -m "not infra" -q -p no:cacheprovider

# 운영 이미지 — 마지막 단계라 기본 build 대상. test 단계의 dev 도구·더미 env 는 들어가지 않는다
FROM base AS runtime

EXPOSE 8000

# 워커 클래스·워커 수·바인드·로그 설정은 gunicorn.conf.py 한 곳에서
CMD ["gunicorn", "-c", "gunicorn.conf.py", "app.main:app"]
