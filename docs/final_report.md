# ReturnFlow MVP report

## Research question

Can an agent reduce the information a customer must provide while preserving deterministic,
auditable return decisions? ReturnFlow tests this with trusted order data, persisted conversation
state, one-question-at-a-time interaction, and an extractor that never owns policy.

## Implemented system

The MVP is a FastAPI modular monolith backed by PostgreSQL and Alembic, with a React/Vite client.
Orders, cases, messages, structured questions, tool calls, and simulated return requests are
persisted. Rule-based extraction is the deterministic fast path; Ollama/Qwen3-4B and any
OpenAI-compatible provider share the same validated `ReturnFacts` boundary.

The policy engine checks delivery, the 30-day window, final-sale status, existing returns, return
reason, and usage in a fixed short-circuit order. Defects, identity problems, conflicting facts,
unsupported cases, and explicit human requests are not auto-approved.

## Measured results

The checked-in rules baseline uses 50 independently labeled short inputs. It achieved 100% accuracy
on the labeled slots and 100% exact match on those labeled fields. Over-extraction is reported
separately because a parser may correctly identify additional explicit facts that were not included
in a partial label.

Across the ten seed scenarios, a fixed four-question form asks 4.0 follow-up questions on average.
The state- and policy-aware flow asks 0.9, a 77.5% reduction in this controlled seed benchmark.
This result is a workflow baseline, not a user study: it reflects designed scenarios and must not be
generalized to production traffic.

The same 50 inputs were also evaluated against a locally hosted `qwen3:4b` model through Ollama.
With deterministic decoding, native structured output, and thinking disabled, the model achieved
56.16% labeled-slot accuracy and 48% exact match. Mean latency was 1.10 seconds and p95 latency was
1.42 seconds on the test Apple Silicon machine. Twenty-six inputs had at least one labeled mismatch.
The most common failures were omitted item names, incorrect reason categories, and omitted
used/opened/damaged facts. This is evidence for the implemented rules-first hybrid: the model is a
bounded fallback for phrasing the parser does not understand, while deterministic code retains
ownership of policy and trusted order facts.

Reproduce the numbers with:

```bash
uv run python -m scripts.evaluate --provider rules
uv run python -m scripts.evaluate --provider ollama --model qwen3:4b
```

The checked-in outputs are in `docs/results/rules-baseline.json` and
`docs/results/qwen3-4b.json`. A future run with `qwen3:1.7b` can compare local model sizes. A cloud
provider is intentionally excluded from CI and requires an explicit data-review decision before use.

## Reliability and security evidence

- Database-backed questions survive refresh and API restart.
- Question ownership, status, allowed option, expiry, and case version are checked server-side.
- A confirmation question is bound to the case version; duplicate confirmation creates no second RMA.
- Identity mismatch exposes no order details.
- Invalid or timed-out model output falls back to known rule facts and cannot mutate policy directly.
- Structured logs omit raw messages and full emails; metrics expose aggregate request and decision data.
- CI runs lint, strict type checking, tests, migration checks, frontend build, and container builds.

## Failure analysis and limitations

The deterministic parser is intentionally conservative. Unusual paraphrases, multilingual text, and
ambiguous product references can cause another question rather than a guess. Name matching currently
uses normalized substring matching and will not disambiguate two similarly named items. The four-rule
policy is not suitable for a real retailer, and human review is represented as a terminal status rather
than an operational queue.

The current metrics are offline and scenario-based. The extraction labels are partial, so the reported
over-extraction rate can include valid explicit facts omitted from a label. Before a stronger claim,
collect held-out, multi-author conversations; measure slot precision/recall, decision accuracy,
unnecessary and repeated question rates, completion, p95 latency, and resource use; then compare the
fixed form, rules, Qwen3 1.7B, Qwen3 4B, and hybrid route under identical cases.

## Next steps

1. Add a second, frozen multi-author evaluation set and compare Qwen3 1.7B, Qwen3 4B, and hybrid mode.
2. Add a human-review work queue and resolution audit.
3. Add policy versions and cited explanations while keeping code as the decision authority.
4. Add OpenTelemetry traces, backup/restore testing, rate limiting, and deployment-specific secrets.
5. Run a small usability study focused on question clarity and completion, not just model accuracy.
