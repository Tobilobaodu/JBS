# Project Status and Roadmap

This replaces the developer-submitted implementation plan as the canonical status tracker. That plan was reviewed against the actual codebase (not just the developer's own account of it) before being accepted — one claim didn't hold up, and it's corrected below rather than carried forward silently. Everything else in the submitted plan was verified accurate and is preserved here with source-code confirmation noted.

## How this document was verified

Claims below are marked with how they were checked:
- **Code-verified** — read directly against the actual repository, not taken on the developer's word.
- **Doc-verified** — cross-checked against the pack files (`01`–`11`) for consistency.
- **Unverified** — no source available yet to confirm; flagged explicitly rather than assumed.

---

## Phase 1 — Foundations — ✅ COMPLETE, with one correction

### Sprint 1: Project setup and auth — ✅ Code-verified
- Repo/environment scaffolding, Alembic migrations for `users`/`user_sessions` — present.
- `POST /auth/register`, `POST /auth/login`, `POST /auth/logout`, `GET /auth/me` — all four routes present in `app/api/v1/auth.py`, matching `05-openapi.yaml`.
- Object storage integration, secrets management — present per `app/core/storage.py` and `app/core/config.py`.

### Sprint 2: CV upload and processing job scaffolding — ✅ Code-verified
- `cv_files`/`processing_jobs` tables, `POST /cvs` with magic-byte validation, non-guessable storage keys — present.
- **Malware scanning (ClamAV)** — present and correctly implemented (`app/services/malware_scan.py` uses the correct `cd.instream(io.BytesIO(...))` signature). Security gap #1 from `10-security-plan.md` §13 is genuinely closed.
- `GET /cvs`, `GET /cvs/{cvId}`, `DELETE /cvs/{cvId}` — present, and IDOR-safe: every query scopes by `user_id == current_user.id` at the data-access layer, not just the route layer, matching the pattern `10-security-plan.md` §3 requires.
- `GET /jobs/{jobId}`, Celery/Redis queue with retry/backoff and dead-letter handling — present.

### Sprint 3: Extraction pipeline — ✅ Code-verified, with **one correction**

Everything here is genuinely built and matches the pack, **except one claim**:

> ⚠️ **Correction: `confidence_score` is NOT yet fixed.** The submitted plan states Sprint 3 produces a "genuine `confidence_score` (not a proxy heuristic)." This is not accurate as of the reviewed code. `app/extraction/docling_parser.py` still computes confidence as `min(1.0, max(0.1, 50 / char_count))` — the exact length-based heuristic identified as a bug in the prior review (see `02-architecture-overview.md` §4 for the full account of why this silently breaks the merge layer's "highest confidence wins" logic). This needs to be fixed and re-verified — specifically, tested against a deliberately garbled/low-quality document to confirm the score actually drops — before Sprint 3 is marked complete. See the corresponding task in the current sprint tracker.

Everything else in Sprint 3 holds up: the `DocumentParser` interface is correctly implemented and Docling-specific types don't leak past it; the Textract worker correctly uses the async `start_document_text_detection` → poll → paginated-collection flow (required because the sync API doesn't support PDFs); the MinIO→AWS-S3 bridge and `finally`-block cleanup are present; the merge/structural-validation worker produces `cv_raw_text` with `structural_validation_result` populated (section count, heading alignment, reading order, date consistency, bullet preservation, anomaly detection) — though note the anomaly-detection logic itself currently depends partly on the same flawed confidence comparison and should be re-checked once the fix above lands, not assumed fine by association.

### Sprint 4: Observability and Phase 1 close-out — ✅ Code-verified
- Structured logging (structlog, JSON in non-local environments) with correlation IDs bound via `contextvars` — present in `app/core/logging.py` and used consistently across all three workers.
- The five named Prometheus metrics (`processing_jobs_total`, `processing_job_duration_seconds`, `extraction_characters`, `merge_strategy_used_total`, `structural_anomalies_total`) are defined in `app/core/metrics.py` and correctly registered via the `main.py` import trick (`from app.core import metrics as _metrics  # noqa: F401`).
- Error handling audit — plausible from code structure (every worker's `except` block populates `last_error`) but the "manually triggered and verified" claim for each failure mode is **unverified** — no test output or log evidence was reviewed, only that the code paths exist.

**Phase 1 status: complete pending the confidence-score fix above.** Don't treat Sprint 3 as closed until that's resolved and retested — it's a correctness bug in a component every later phase depends on (matching, in Phase 3, ultimately traces evidence back through the merge layer this bug affects).

---

## Phase 2 — Structured Parsing and Job Post Ingestion — ⬜ NOT STARTED

No code for this phase exists in the reviewed repository snapshot. The submitted plan's Phase 2 scope is accurate as a restatement of `01-implementation-plan.md` and `03-data-model.md` — CV parser/normaliser, section-heading canonicalization, job post URL/text ingestion — and is carried forward unchanged. One addition:

- **SSRF protections are Phase 2's highest-risk item and currently have no implementation to review.** `10-security-plan.md` §4 specifies the requirement in full (IP/scheme validation, redirect re-validation, network-level egress isolation, timeout/size caps) but nothing in the codebase touches job post ingestion yet. This is correctly flagged as "must be built in from the first line" in the existing pack — worth repeating here because Phase 2 is the very next phase of work.
- No Phase-2-specific sprint-tasks file exists yet (only Phase 1 has one, `07-first-sprint-tasks.md`). See the sprint-tracker note at the end of this document.

---

## Phase 3 — Matching and Tailored CV Drafting — ⬜ NOT STARTED

No code exists yet. Scope as submitted is accurate against `03-data-model.md` and `11-product-extensions.md` and is carried forward: matching engine with the five support levels (`supported`/`partially_supported`/`unsupported`/`contradictory`/`unclear`), tailored CV generation with evidence-reference enforcement, provenance columns, ATS structural validation (extension #1), and the fix-it checklist (extension #3) built alongside.

One clarification on sequencing, since the submitted plan lists ATS validation and the fix-it checklist as "build in parallel" without specifying with what: per `11-product-extensions.md` §1, the ATS check has **no dependency on job post data** and could technically start as soon as Phase 2's CV parsing lands, in parallel with Phase 3's matching engine work rather than strictly inside Phase 3 — worth deciding explicitly if there's a second developer or spare capacity, rather than defaulting to sequential.

---

## Phase 4 — Guided Cover Letter Workflow — ⬜ NOT STARTED

No code exists yet. Scope as submitted matches the existing pack and is carried forward unchanged.

---

## Phase 5 — Hardening and Release Readiness — ⬜ NOT STARTED

No code exists yet. Scope as submitted matches the existing pack and is carried forward unchanged, including exports, multi-job-post coverage reporting (extension #2), the full security/test pass, and the incident-response tabletop.

---

## Open decisions — status check

| Decision | Needed by | Status | Note |
|---|---|---|---|
| LLM provider and model | Phase 3 | Unresolved | `OPENAI_API_KEY`/`OPENAI_MODEL` exist as config fields with `gpt-4o` as a placeholder default — this is scaffolding for the *shape* of the config, not a pinned decision. Still needs an explicit choice before Phase 3 generation work starts. |
| Export file formats/templates | Phase 5 | Unresolved | No change. |
| Cost alert thresholds | Phase 5 | Unresolved | No change. |
| Endpoint-tier rate limit values | Phase 1/3 | Partially done | Config fields exist (`rate_limit_auth_requests` etc. in `app/core/config.py`) with the tiered structure correctly separated from the general limit — **code-verified**. But nothing in `app/api/` actually enforces them yet; no rate-limiting middleware or dependency is wired in. "Partially done" is accurate: the config shape exists, the enforcement doesn't. |
| Malware scanner selection | Phase 1 | ✅ Done | Code-verified, see Sprint 2 above. |

---

## Security plan gaps (`10-security-plan.md` §13) — corrected

| # | Gap | Status | Note |
|---|---|---|---|
| 1 | Malware scanning on upload | ✅ Done | Code-verified. |
| 2 | SSRF protection on job post URL fetch | ⬜ Pending | Correct — Phase 2, not yet started, no code exists. |
| 3 | Evidence-reference content verification | ⬜ Pending | Correct — Phase 3, not yet started. Worth restating precisely: the requirement is that a validation step confirms the referenced source (e.g. a specific `cv_experience_items.id`) *actually contains text supporting the specific claim it's attached to* — not merely that a syntactically valid reference ID was supplied. A check that only confirms "a UUID was provided" satisfies the schema but not the security requirement. |
| 4 | Security tests cross-referenced into test plan | ✅ Done | **This was marked pending in the developer's submitted plan — that's incorrect.** `09-test-plan.md` §9 was rewritten to explicitly point into `10-security-plan.md` §1, §2, §3, §4, §5, §10, and §14 by section number, and states plainly that the security plan "should be run as part of this test plan, not treated as a separate pen-test-only activity." This is a documentation-only item and it's already resolved — no further action needed unless the cross-references drift out of sync with future edits. |
| 5 | Endpoint-tier rate limit granularity | ✅ Done (structure) / ⬜ Pending (enforcement + tuning) | **Also marked simply "pending" in the developer's submitted plan — more precise status needed.** The *granularity* (separate limits per endpoint tier, rather than one global limit) is done, both in the pack (`08-deployment-guide.md` §5) and now confirmed in code (`app/core/config.py` has all five tiers as distinct settings). What's still pending: (a) actual enforcement — no middleware currently reads these settings and applies them, and (b) tuning the placeholder values against real traffic, which can only happen post-launch. Track these as two separate items, not one. |

---

## Product extensions — unchanged

The submitted plan's product-extensions table is accurate against `11-product-extensions.md` and is carried forward without correction: extensions #1 and #3 build in/around Phase 3, #2 lands in Phase 5, #4 and #5 are schema-only reservations already specified but not yet built, #6 remains explicitly flagged as needing a separate go/no-go conversation before any design work starts.

---

## Immediate next actions, in order

1. **Fix the `confidence_score` heuristic in `docling_parser.py`** and re-verify against the test case in `09-test-plan.md` §2 (garbled document → score should drop) before treating Sprint 3, and therefore Phase 1, as genuinely closed.
2. **Re-run the merge-outcome sanity test** (`09-test-plan.md` §2) once the fix lands, since `merge.py`'s anomaly detection partly depends on the same confidence values.
3. **Create a Phase 2 sprint-tasks file** (ticket-sized, matching the style of `07-first-sprint-tasks.md`) before starting Phase 2 work — none exists yet, and Phase 2's highest-risk item (SSRF) deserves the same explicit, checkable "done when" treatment Phase 1's malware-scanning task got.
4. **Begin Phase 2**, starting with SSRF-safe job post URL fetching before the CV parser/normaliser — not because it's more urgent functionally, but because `01-implementation-plan.md` §5 already flags it as a "build correctly from the first line, don't retrofit" item, and starting there removes the temptation to bolt security on after a working happy-path fetch already exists.
5. **Timeline**: with Phase 1 substantively complete (pending the one fix above), the remaining indicative timeline from `01-implementation-plan.md` is Phases 2–5, originally estimated ~17–21 weeks combined for a single developer working sequentially — unchanged by this review, since no scope was added or removed, only one status corrected.
