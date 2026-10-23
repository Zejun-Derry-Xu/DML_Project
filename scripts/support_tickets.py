"""Read-only support export for an authorized server operator; contains demo case data."""

import json

from sqlalchemy import select

from app.db.models import SupportTicketRecord
from app.db.session import SessionLocal


def main() -> None:
    with SessionLocal() as db:
        tickets = db.scalars(select(SupportTicketRecord).order_by(SupportTicketRecord.created_at))
        for ticket in tickets:
            print(
                json.dumps(
                    {
                        "id": str(ticket.id),
                        "status": ticket.status,
                        "created_at": ticket.created_at.isoformat(),
                        "snapshot": ticket.snapshot,
                    }
                )
            )


if __name__ == "__main__":
    main()
