# API guide

Interactive OpenAPI documentation is served at `/docs`. All business endpoints use `/api/v1`.
Errors use `{ "error": { "code", "message", "request_id" } }`; internal database and model errors
are never returned verbatim.

## Start or continue a conversation

```http
POST /api/v1/chat
Content-Type: application/json

{
  "session_id": "8463ee1f-c303-47f4-94c8-c520e82b405a",
  "customer_email": "june@example.com",
  "message": "Return the shirt from ORD-1010. It does not fit."
}
```

A response can contain a `question` with only server-approved options. Submit a button answer:

```http
POST /api/v1/questions/{question_id}/answer
Content-Type: application/json

{
  "session_id": "8463ee1f-c303-47f4-94c8-c520e82b405a",
  "selected_value": "no"
}
```

Free text goes back through `/chat`, where it is extracted and audited. A pending HTTP connection is
never retained while waiting for a customer.

## Structured evaluation

`POST /api/v1/returns/evaluate` accepts trusted, structured inputs for tests and non-chat clients:

```json
{
  "session_id": "8463ee1f-c303-47f4-94c8-c520e82b405a",
  "customer_email": "june@example.com",
  "order_number": "ORD-1010",
  "reason": "does_not_fit",
  "used": false
}
```

## Resume

`GET /api/v1/return-cases/{session_id}` restores the active question or terminal result. Expired
questions are marked `expired` and regenerated against the current case version.

## Order lookup

`GET /api/v1/orders/{order_number}?email={email}` verifies ownership before returning order data.
An existing order with the wrong email returns `IDENTITY_MISMATCH` without exposing order details.

## Stable decision reasons

`ORDER_NOT_DELIVERED`, `OUTSIDE_RETURN_WINDOW`, `FINAL_SALE`, `USED_ITEM`,
`DEFECT_REQUIRES_REVIEW`, `ORDER_ALREADY_RETURNED`, `IDENTITY_MISMATCH`,
`MISSING_ORDER_ID`, `MISSING_ITEM_SELECTION`, `MISSING_RETURN_REASON`,
`MISSING_USAGE_STATUS`, `INFORMATION_CONFLICT`, and `USER_REQUESTED_HUMAN`.
