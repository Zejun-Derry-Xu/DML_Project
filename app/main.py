import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.base import RequestResponseEndpoint

from app.api.v1.chat import router as chat_router
from app.api.v1.orders import router as orders_router
from app.api.v1.questions import router as questions_router
from app.api.v1.returns import router as returns_router
from app.config import get_settings
from app.db.session import SessionLocal, database_is_ready
from app.errors import AppError
from app.observability.logging import configure_logging
from app.observability.metrics import HTTP_LATENCY, HTTP_REQUESTS
from app.services.question_cleanup_service import cleanup_loop

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    stop = asyncio.Event()
    cleanup = asyncio.create_task(
        cleanup_loop(stop, settings.question_cleanup_interval_seconds),
        name="expired-question-cleanup",
    )
    try:
        yield
    finally:
        stop.set()
        await cleanup


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    application = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(chat_router, prefix="/api/v1")
    application.include_router(orders_router, prefix="/api/v1")
    application.include_router(questions_router, prefix="/api/v1")
    application.include_router(returns_router, prefix="/api/v1")

    @application.middleware("http")
    async def observe_request(request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid4()))
        started = perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            route_object = request.scope.get("route")
            route = getattr(route_object, "path", request.url.path)
            elapsed = perf_counter() - started
            HTTP_REQUESTS.labels(method=request.method, route=route, status=str(status_code)).inc()
            HTTP_LATENCY.labels(method=request.method, route=route).observe(elapsed)
            logger.info(
                "http_request_completed",
                service="returnflow-api",
                request_id=request_id,
                method=request.method,
                route=route,
                status_code=status_code,
                latency_ms=round(elapsed * 1000),
                success=status_code < 500,
            )

    @application.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError) -> Response:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {"code": exc.code, "message": exc.message, "request_id": str(uuid4())}
            },
        )

    @application.exception_handler(SQLAlchemyError)
    async def database_error_handler(_: Request, __: SQLAlchemyError) -> Response:
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "DATABASE_UNAVAILABLE",
                    "message": "The service is temporarily unavailable.",
                    "request_id": str(uuid4()),
                }
            },
        )

    @application.get("/health", tags=["operations"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/metrics", tags=["operations"], response_model=None)
    def metrics() -> Response:
        return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @application.get("/ready", tags=["operations"], response_model=None)
    def ready() -> Response:
        try:
            with SessionLocal() as session:
                database_is_ready(session)
            return JSONResponse(content={"status": "ready"})
        except SQLAlchemyError:
            return JSONResponse(status_code=503, content={"status": "not_ready"})

    return application


app = create_app()
