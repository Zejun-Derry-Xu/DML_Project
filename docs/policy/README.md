# Versioned MVP policy retrieval

The JSON policy at `mvp-1.0.0.json` restates the current deterministic engine, including
its already-returned and human-review checks. The document is versioned so explanations
can cite stable clause IDs. `PolicyKnowledge` loads the document, rejects a version that
differs from the engine constant, retrieves relevant clauses from a local term index,
and returns cited English explanations. The policy engine remains the only component
that can decide eligibility or create a simulated return request.

`POST /api/v1/policy/explain` accepts a `question`. With `session_id`, it also requires
the matching `customer_email` and reads the saved decision and reason code from the
verified case; callers cannot submit their own decision. Without a session, the route
answers general policy questions and refuses to decide a specific order's eligibility.
Unknown questions, missing case facts, version mismatches, and conflicts have distinct
statuses and do not approve a return.

Example:

```json
{"question":"What is the return window?"}
```

The response includes `policy_version`, `status`, `answer`, and citations with clause
IDs and text. This is a small local lexical retrieval layer with deterministic wording;
it does not use embeddings or generate new policy text. Evaluation of retrieval quality
and decision quality should remain separate in later experiments.
