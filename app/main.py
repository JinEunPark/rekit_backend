import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_v1
from app.common.storage import storage_service
from app.core.config import settings
from app.core.database import async_session_factory, engine
from app.core.deps import build_payment_gateway, get_email_sender
from app.core.exceptions import register_exception_handlers
from app.db import registry  # noqa: F401  # 모든 SQLAlchemy 모델 로드 — string ref resolve 용
from app.order.abandoned_order_sweeper import run_periodically, sweep_abandoned_orders


def _start_abandoned_order_sweeper() -> asyncio.Task[None] | None:
    interval = settings.pending_order_sweep_interval_seconds
    if interval <= 0:
        return None
    return asyncio.create_task(
        run_periodically(
            lambda: sweep_abandoned_orders(
                async_session_factory, build_payment_gateway(), get_email_sender()
            ),
            interval_seconds=interval,
        )
    )


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await storage_service.ensure_bucket()
    sweeper = _start_abandoned_order_sweeper()
    yield
    if sweeper is not None:
        sweeper.cancel()
        with suppress(asyncio.CancelledError):
            await sweeper
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        debug=settings.debug,
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=None if settings.is_production else "/openapi.json",
    )

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    register_exception_handlers(app)

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(api_v1)

    return app


app = create_app()
