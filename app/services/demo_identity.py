"""Signed, short-lived identities for fictional accounts only. Not real authentication."""

import hashlib
import hmac
import secrets
import time
from uuid import UUID

from fastapi import Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import CustomerRecord
from app.db.session import get_db
from app.errors import AppError

COOKIE = "returnflow_demo"
SESSION_TTL = 7200


def demo_secret() -> bytes:
    settings = get_settings()
    if not settings.demo_enabled or len(settings.demo_session_secret) < 32:
        raise AppError("DEMO_DISABLED", "Demo accounts are not configured.", 503)
    return settings.demo_session_secret.encode()


def set_demo_cookie(response: Response, customer_id: UUID) -> None:
    value = f"{customer_id}.{int(time.time()) + SESSION_TTL}.{secrets.token_hex(16)}"
    signature = hmac.new(demo_secret(), value.encode(), hashlib.sha256).hexdigest()
    response.set_cookie(
        COOKIE,
        value=f"{value}.{signature}",
        max_age=SESSION_TTL,
        httponly=True,
        secure=get_settings().demo_cookie_secure,
        samesite="strict",
    )
    response.headers["Cache-Control"] = "no-store"


def current_demo_customer(request: Request, db: Session = Depends(get_db)) -> CustomerRecord:
    secret = demo_secret()
    try:
        value, signature = request.cookies.get(COOKIE, "").rsplit(".", 1)
        customer, expires, _ = value.split(".")
        expected = hmac.new(secret, value.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected) or int(expires) <= time.time():
            raise ValueError("Invalid demo session")
        customer_id = UUID(customer)
    except (ValueError, TypeError) as error:
        raise AppError(
            "DEMO_SESSION_REQUIRED", "Select a fictional demo account first.", 401
        ) from error
    record = db.scalar(
        select(CustomerRecord).where(
            CustomerRecord.id == customer_id, CustomerRecord.is_demo.is_(True)
        )
    )
    if record is None:
        raise AppError("DEMO_SESSION_REQUIRED", "Select a fictional demo account first.", 401)
    return record


def optional_demo_customer(
    request: Request, db: Session = Depends(get_db)
) -> CustomerRecord | None:
    if get_settings().workflow_mode == "legacy":
        return None
    return current_demo_customer(request, db)
