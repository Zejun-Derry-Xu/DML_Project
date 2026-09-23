import asyncio
from contextlib import suppress

import structlog
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import SessionLocal
from app.repositories.return_repository import ReturnRepository

logger = structlog.get_logger()


def expire_questions() -> int:
    with SessionLocal.begin() as session:
        return ReturnRepository(session).expire_due_questions()


async def cleanup_loop(stop: asyncio.Event, interval_seconds: int) -> None:
    while not stop.is_set():
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
            continue
        try:
            expired = await asyncio.to_thread(expire_questions)
            if expired:
                logger.info("question_cleanup_completed", expired_count=expired)
        except SQLAlchemyError:
            logger.warning("question_cleanup_failed", error_code="DATABASE_UNAVAILABLE")
