from uuid import UUID

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CustomerRecord
from app.db.session import get_db
from app.errors import AppError
from app.services.demo_identity import demo_secret, set_demo_cookie

router = APIRouter(prefix="/demo", tags=["fictional-demo"])


class DemoSelection(BaseModel):
    customer_id: UUID


@router.get("/customers")
def customers(db: Session = Depends(get_db)) -> list[dict[str, str]]:
    demo_secret()
    return [
        {"id": str(c.id), "name": c.name}
        for c in db.scalars(
            select(CustomerRecord)
            .where(CustomerRecord.is_demo.is_(True))
            .order_by(CustomerRecord.name)
        )
    ]


@router.post("/session")
def select_customer(
    payload: DemoSelection, response: Response, db: Session = Depends(get_db)
) -> dict[str, str]:
    demo_secret()
    customer = db.get(CustomerRecord, payload.customer_id)
    if customer is None or not customer.is_demo:
        raise AppError("DEMO_ACCOUNT_NOT_FOUND", "Unknown fictional account.", 404)
    set_demo_cookie(response, customer.id)
    return {"id": str(customer.id), "name": customer.name, "notice": "Fictional demo identity only"}
