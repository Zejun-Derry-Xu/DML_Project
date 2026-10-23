# Single-call 4B extraction harness experiment

This is an opt-in offline experiment, NOT a new production default or model
qualification. The normal apparel API continues using `LLMFactExtractor` with its
original prompt/schema. No new business endpoint, database field or policy rule.

## What changed

1. `legacy`: the existing request payload, with opt-in in-memory diagnostics.
2. `typed`: constrained field enums and state/value branches at generation time,
   also validated locally. Unknown never silently becomes false. Uses exact quotes.
3. `span_ids`: the same typed contract and semantic prompt, but selects IDs for
   losslessly partitioned current-message source segments. Code reconstructs exact
   source text/positions; models do not generate offsets. Invalid or duplicate IDs
   are rejected, not repaired. Referencing nonadjacent segments recovers their
   contiguous cover, retaining intervening qualifiers/negations.

The typed/span variants use the same semantic instructions, but the typed variant
also changes instructions relative to legacy. Thus legacy-vs-typed is a combined
contract/prompt intervention, not evidence that schemas alone caused an improvement.
Span-vs-typed is the narrower evidence-representation comparison. No more variants
or tuning cycles are added after seeing the frozen validation results.

The model still determines meaning. A valid evidence ID does NOT prove entailment,
correct subject, correct polarity, resistance to injection or eligibility. No new
keyword classifier or semantic fuzzy matching is used. Existing deterministic
policy decisions, ownership checks, unknown handling and confirmation remain.

## Trace boundary

`capture_diagnostics=False` by default. When enabled for authored offline samples,
`last_trace` retains the actual request, raw response content, parsed candidates,
source mapping, accepted observations, failure stage and specific rejection codes.
It does not request or retain hidden reasoning. Usage returned on truncated responses
is retained. Normal API logs do not serialize raw traces or customer text.

The runner permits private output only under Git-ignored `data/evaluation_runs`,
sets restrictive file creation permissions, takes a process lock and freezes
model/runtime/data/prompt/source/runner identities. Resumes reuse matching records
and reject changed identities. The shared inference budget is 90 minutes, reserved
before each 60-second request; interruption cannot silently reset it. Every variant
uses at most one transport attempt: no repair, reflection or 8B fallback.

## Reproduce locally (no Docker)

Use the already-installed local Ollama and existing `qwen3:4b`. Start it bound to
loopback with one loaded model and parallelism 1. Do not launch a second Ollama if
one is already serving, and do not stop a server owned by another task.

```bash
env OLLAMA_HOST=127.0.0.1:11434 OLLAMA_NUM_PARALLEL=1 \
  OLLAMA_MAX_LOADED_MODELS=1 OLLAMA_CONTEXT_LENGTH=4096 \
  OLLAMA_KEEP_ALIVE=2m ollama serve
```

From a second terminal in the repository:

```bash
.venv/bin/python -m scripts.evaluate_apparel_harness \
  --output data/evaluation_runs/harness-local-v1
```

Use the same output path to resume only if identity is unchanged. Use a NEW output
directory for any code, prompt, model or data change, and retain previous results.
Stop this experiment's own Ollama with Ctrl+C after the run; no data deletion.

Inspect raw-vs-accepted attribution without another inference call:

```bash
.venv/bin/python -m scripts.analyze_apparel_harness \
  --run data/evaluation_runs/harness-local-v1
```

`attribution.json` distinguishes exact typed candidates lost during validation from
strings such as `"false"` that resemble the label but remain invalid and unscored.
Neither category establishes semantic correctness beyond the provisional labels.

## Frozen evaluation protocol

- Compare all three variants on the existing 24 development messages.
- Select an experimental candidate using development data only: known accuracy,
  reviewed-null assertions and errors must not regress versus legacy to pass
  development nonregression. Among passing candidates, prioritize fewer unsupported
  assertions, fewer request errors, higher macro accuracy, then lower mean latency.
  If neither passes, still inspect the best candidate but explicitly record failure.
- Complete legacy and selected-candidate results on all 48 historical diagnostics;
  previously completed development calls are reused, not rerun.
- Freeze selection before either variant processes the 48 new validation messages.
  The new set includes use, stains, garment damage, tag attachment, tag integrity
  and origin, with explicit null/unknown/instruction boundaries. Only specified
  labels are scored; other fields remain unreviewed, not gold null.
- Maximum scheduled calls: 216. Parameters remain thinking off, temperature/seed 0,
  context 4096, output 512, deadline 60 seconds. Budget expiry reports unfinished
  rows; errors are not removed from accuracy/latency denominators.
- Labels are assistant-authored and provisional, requiring human review. Historical
  validation is now regression, NOT a new blind test. No ABCD or tau2 quality claim.
- Report known macro and per-field counts separately from reviewed-null assertions,
  errors, validation losses, tokens with missing usage, cold/first and warm-proxy
  latency. An all-null extractor must not pass via a null-heavy overall average.

Mac/Metal and Jetstream/Linux CPU measurements are separate experiments. A later
claim of “4B near 8B and more economical” requires same-environment/new-data paired
evaluation, macro difference at most three percentage points, no increase in
unsupported values and actually lower latency. A private local result cannot pass
the cloud deployment's qualification gates or automatically switch serving models.

## Sources for design, not guaranteed Qwen performance

- [Google LangExtract: source grounding and examples](https://github.com/google/langextract).
- [Anthropic: simple workflows and programmatic gates](https://www.anthropic.com/research/building-effective-agents).
- [Structured outputs still permit content mistakes](https://developers.openai.com/api/docs/guides/structured-outputs).
- [LangChain: traces and harness ablations with a fixed model](https://www.langchain.com/blog/improving-deep-agents-with-harness-engineering).

No framework dependency or hosted tracing service is introduced. Public branch CI
tests code; raw model traces and local operational results stay ignored/private.
