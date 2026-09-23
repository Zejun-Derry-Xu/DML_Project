# ReturnFlow demo script

## Setup

Run `docker compose up --build`, open <http://localhost:5173>, and keep `/docs` available in a
second tab. Use the rules provider for a deterministic classroom demo.

## Demo 1: minimal questions and successful RMA

1. Enter `june@example.com`.
2. Send: `Return ORD-1010 because the shirt does not fit and it is unused.`
3. Point out that order, item, reason, and usage were already understood; only confirmation appears.
4. Select **Confirm return**.
5. Show the RMA reference and explain that it is simulated and idempotent.

## Demo 2: trusted order data short-circuits the conversation

1. Start a new return and enter `dev@example.com`.
2. Send: `I want to return ORD-1004.`
3. The system returns `FINAL_SALE` without asking reason or usage because those answers cannot change
   the result.

## Demo 3: multiple items and persistent ask-and-wait

1. Start a new return and enter `emma@example.com`.
2. Send: `I want to return ORD-1005.`
3. Show that the item options come only from the order service.
4. Refresh the page; the same pending question returns from PostgreSQL.
5. Continue with **Noise-Cancelling Headphones**, **No longer wanted**, and **No**.

## Demo 4: human-review boundary

Use `farah@example.com` and send `The kettle from ORD-1006 is defective.` The deterministic policy
routes the case to human review instead of allowing a model to approve or reject a safety issue.

## Engineering evidence

- Open `/metrics` to show HTTP and decision counters.
- Open `/docs` to show versioned API schemas.
- Run `make check` to show lint, type checking, frontend build, and tests.
- Run `uv run python -m scripts.evaluate --provider rules` to reproduce evaluation metrics.

