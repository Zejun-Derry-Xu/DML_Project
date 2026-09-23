from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.api.v1.orders import router as orders_router
from app.api.v1.questions import router as questions_router
from app.api.v1.returns import router as returns_router
from app.config import get_settings
from app.db.session import SessionLocal, database_is_ready
from app.errors import AppError


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(orders_router, prefix="/api/v1")
    application.include_router(questions_router, prefix="/api/v1")
    application.include_router(returns_router, prefix="/api/v1")

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
