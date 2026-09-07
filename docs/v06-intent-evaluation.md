# V0.6 intent evaluation

## Acceptance scope

V0.6 adds a human preference layer without moving route, POI or ranking authority into a
language model. The test corpus is `backend/fixtures/intent_v1_cases.json`; it is treated as
a versioned semantic fixture rather than prompt examples embedded only in tests.

## Deterministic evaluation

- Corpus: 59 distinct prompts (the minimum acceptance target was 40).
- Result: 59/59 parameterized semantic tests passed on 2026-08-27.
- Coverage: one/two errands, ten leaf categories, canonical brand aliases, exact versus
  preferred brands, substitution language, required versus optional errands, maximum
  detour, walking tolerance, transfer tolerance, consolidated-stop preference, urgency,
  ISO arrival constraint, ambiguous conflicts, unsupported brands, unsupported requests,
  three-errand overflow and a mixed known/invented-brand adversarial request.
- Observed deterministic accuracy on this curated corpus: 100%. This is fixture accuracy,
  not a claim about unrestricted natural language.

## Hybrid and safety tests

- Easy requests make zero LLM calls.
- A fuzzy request is accepted only after `IntentV1` validation and canonical category
  resolution.
- An LLM-invented brand is rejected and returned as unresolved.
- A provider timeout produces a structured deterministic fallback with a validation/error
  metric; it does not run the optimizer.
- Unknown user-supplied intent terms receive HTTP 422 from `/api/optimize-intent`.
- Exact brands are not relaxed. Optional errands can be omitted while all required errands
  remain, and the response is explicitly classified `partial_option`.
- Intent-aware requests remain inside the global hard routing-call budget.
- When a substitutable category has no hard-compliant routed result, the existing catalog
  near miss is exposed as an explicitly unrouted `easier_alternative`; it is never silently
  selected or presented with fabricated transit metrics.

## Instrumentation

`GET /api/intent/metrics` returns process-local aggregates: total, deterministic and LLM
parses/rates; parser and LLM latency; input/output tokens; validation failures; unresolved
terms; fallback, clarification and correction counts/rates; and selected near-miss or
partial/easier-alternative count. Measured cost is nullable because the current Responses
API adapter does not receive a billed-cost field and does not guess model pricing.

## Gating and limitations

The default suite is fully offline. `tests/test_llm_integration.py` requires both
`RUN_LLM_INTEGRATION=true` and `OPENAI_API_KEY`; otherwise it is skipped. The root
environment had no configured OpenAI key during the 2026-08-27 acceptance run, so no live
LLM quality or token/cost result is claimed. OneMap live tests remain independently gated.

There is no multi-turn dialogue, broad world knowledge, route generation by an LLM,
opening-hours inference, or invented POI fallback. Free-form requests outside the local
catalog require clarification. V0.7 work is intentionally absent.

## Acceptance run (2026-08-27)

- Complete offline backend suite: 133 passed, 4 gated tests skipped.
- Deterministic semantic suite: 60 passed (59 prompt fixtures plus one corpus guard).
- Live OneMap integration: 3 passed after explicit opt-in; 134 non-live tests deselected.
- Live LLM integration: skipped because no OpenAI API key was configured; no live quality,
  tokens or cost were fabricated.
- Frontend: ESLint passed; Next.js 16.3.3 production build, TypeScript check and static page
  generation passed.
- Offline query-chain sample, Punggol MRT → Orchard MRT: local parse latency 6.3–8.0 ms,
  optimization latency 41.5–101.3 ms and 6–7 mock routing calls. `KFC and bubble tea`
  resolved to exact KFC plus substitutable bubble tea and returned `best_match`; `Coffee if
  convenient, but pharmacy is compulsory` retained pharmacy as required and coffee as
  optional; `withdraw cash ... toothpaste, minimal walking` consolidated both at Toa Payoh
  HDB Hub.
