# Project Status and Roadmap

This is the single canonical status tracker for the project — status history, current state, and the forward sprint plan, all in one place. It previously existed as two documents (this file, plus a separately-circulated "Project Update and Sprint Plan" review); the second has been folded in here as of **2026-08-10** so there is one source instead of two that can drift out of sync with each other. Nothing from either source was dropped silently: where the two disagreed, or where a claim in either one didn't hold up against a fresh code check, it's corrected below with the correction visible, not quietly merged away.

Base commit for everything in this document: `64cfbbd`, **plus** Sprint 1 (2026-08-10) and Sprint 2 (2026-08-11), both now committed on local `main` as `53f3452` (Sprint 1) and `25ad817` (Sprint 2). Local history was subsequently squashed to drop a Claude co-author trailer and collapse a 3x-duplicated merge history that came from parallel sessions redoing the same work — the two commits above replaced the original `9b612f7`/`0d8a864` (and their duplicates) with identical trees, same authorship/timestamps, cleaner history. **Not yet pushed** — `origin/main` still has the old (trailer-bearing, tangled-merge) history; local `main` is `ahead 2, behind 8` until a force-push is explicitly authorized.

## How this document was verified

Claims below are marked with how they were checked:
- **Code-verified** — read directly against the actual repository, not taken on anyone's word.
- **Doc-verified** — cross-checked against the pack files (`01`–`11`) for consistency.
- **Unverified** — no source available yet to confirm; flagged explicitly rather than assumed.

---

## Status at a glance

| Phase | Status | One-line reality |
|---|---|---|
| 1 — Foundations | ✅ Complete | Confidence-score bug (see below) is fixed as of this review — Phase 1 has no open corrections left. |
| 2 — Job post ingestion / SSRF | ✅ Complete | Job post URL/text ingestion and SSRF-safe fetch (DNS pinning, streaming size cap) both exist and are code-verified. |
| 3 — Matching and tailored CV drafting | ⚠️ Half built | Matching engine (5 support levels) is genuinely done. **Tailored CV generation does not exist at all** — see below, this is the most important line in this table. |
| 4 — Guided cover letter workflow | ⚠️ Half built | All 6 endpoints exist and are ownership-checked. The draft itself is template-assembled text, not AI-generated. |
| 5 — Hardening and release readiness | ⚠️ In progress | Tasks 2.1–2.4 (rate-limit identity, SSRF streaming, concurrency limit, tiered rate limits) are all done as of Sprint 1 (2026-08-10). Exports, ATS check, full security/test-plan pass, and incident-response tabletop are not started. |
| — Anonymous trial support | ✅ Complete, verified live, committed | Sprint 2 (2026-08-11): schema, dependency, route wiring, claim-on-registration, abuse controls, and expiry cleanup all written and verified against a real Postgres instance — migration round-trip, CHECK constraints, concurrency race, claim-transaction atomicity, IDOR, and the cleanup task's full delete order all confirmed. Two pre-existing ownership gaps found and fixed along the way. Committed as `25ad817`, not yet pushed; no scheduler exists yet to invoke the cleanup task periodically. |

---

## Phase 1 — Foundations — ✅ COMPLETE

### Sprint 1: Project setup and auth — ✅ Code-verified
- Repo/environment scaffolding, Alembic migrations for `users`/`user_sessions` — present.
- `POST /auth/register`, `POST /auth/login`, `POST /auth/logout`, `GET /auth/me` — all four routes present in `app/api/v1/auth.py`, matching `05-openapi.yaml`.
- Object storage integration, secrets management — present per `app/core/storage.py` and `app/core/config.py`.

### Sprint 2: CV upload and processing job scaffolding — ✅ Code-verified
- `cv_files`/`processing_jobs` tables, `POST /cvs` with magic-byte validation, non-guessable storage keys — present.
- **Malware scanning (ClamAV)** — present and correctly implemented (`app/services/malware_scan.py` uses the correct `cd.instream(io.BytesIO(...))` signature). Security gap #1 from `10-security-plan.md` §13 is genuinely closed.
- `GET /cvs`, `GET /cvs/{cvId}`, `DELETE /cvs/{cvId}` — present, and IDOR-safe: every query scopes by `user_id == current_user.id` at the data-access layer, not just the route layer, matching the pattern `10-security-plan.md` §3 requires.
- `GET /jobs/{jobId}`, Celery/Redis queue with retry/backoff and dead-letter handling — present.

### Sprint 3: Extraction pipeline — ✅ Code-verified, correction resolved
- The `DocumentParser` interface is correctly implemented and Docling-specific types don't leak past it; the Textract worker correctly uses the async `start_document_text_detection` → poll → paginated-collection flow (required because the sync API doesn't support PDFs); the MinIO→AWS-S3 bridge and `finally`-block cleanup are present; the merge/structural-validation worker produces `cv_raw_text` with `structural_validation_result` populated (section count, heading alignment, reading order, date consistency, bullet preservation, anomaly detection).

> ✅ **Previously flagged, now confirmed fixed: `confidence_score` is genuine, not a length proxy.** Earlier reviews of this document flagged `app/extraction/docling_parser.py` computing confidence as `min(1.0, max(0.1, 50 / char_count))` — a heuristic that always returns ~1.0 for normal-length CVs and silently broke the merge layer's "highest confidence wins" comparison against Textract's real, calibrated confidence (see `02-architecture-overview.md` §4 for the full account). **Re-checked directly against current code (2026-08-10): this is fixed.** `_compute_confidence()` now derives a score from structural signals — a completeness sigmoid over character count, item count, and average characters per item — not output length alone. No further action needed here; this closes the last open item in Phase 1.

### Sprint 4: Observability and Phase 1 close-out — ✅ Code-verified
- Structured logging (structlog, JSON in non-local environments) with correlation IDs bound via `contextvars` — present in `app/core/logging.py` and used consistently across all three workers.
- The five named Prometheus metrics (`processing_jobs_total`, `processing_job_duration_seconds`, `extraction_characters`, `merge_strategy_used_total`, `structural_anomalies_total`) are defined in `app/core/metrics.py` and correctly registered via the `main.py` import trick (`from app.core import metrics as _metrics  # noqa: F401`).
- Error handling audit — plausible from code structure (every worker's `except` block populates `last_error`) but the "manually triggered and verified" claim for each failure mode remains **unverified** — no test output or log evidence has been reviewed, only that the code paths exist.

**Phase 1 status: complete, no open corrections.**

---

## Phase 2 — Structured Parsing and Job Post Ingestion — ✅ COMPLETE

Previously tracked as "not started" — that was stale. **Code-verified as of this review:**

- `JobPost`/`JobPostProfile` models, `POST /job-posts/url`, `POST /job-posts/text`, `GET /job-posts`, `GET /job-posts/{jobPostId}`, `POST /job-posts/{jobPostId}/reprocess` all exist in `app/api/v1/job_posts.py`, matching `05-openapi.yaml`.
- **SSRF protection — the phase's highest-risk item — is built correctly and thoroughly.** `app/services/ssrf_safe_fetch.py`: scheme allowlist, private/reserved-IP rejection (including link-local/cloud-metadata range), redirect-chain re-validation at every hop (max 5), DNS pinning via a process-local `socket.getaddrinfo` patch to close the DNS-rebinding TOCTOU gap, and — as of Task 2.2 — `httpx` response streaming with an incremental size check that aborts as soon as the cumulative body exceeds the cap, so an oversized response never fully accumulates in worker memory.
- CV section-heading canonicalization — present (`app/extraction/heading_canonicalizer.py`), covered by `test_heading_canonicalizer_bare_skills.py`.

No open items in this phase.

---

## Phase 3 — Matching and Tailored CV Drafting — ⚠️ HALF BUILT

### Matching engine — ✅ Code-verified, done
`app/extraction/match_engine.py` implements all five documented support levels (`supported`/`partially_supported`/`unsupported`/`contradictory`/`unclear`) with a weighted scoring model. Contradictory-evidence detection compares same-company role titles for conflicting families (`_roles_conflict`).

> ✅ **Previously flagged docstring/code mismatch — fixed 2026-08-10 (Sprint 1).** `_build_consistency_map()`'s docstring claimed date-overlap detection ("overlapping date ranges with conflicting titles") that the code didn't actually implement — it only compared company and title, meaning any title change at the same company got flagged regardless of timing, including ordinary sequential job changes. This was flagged three times across review cycles without being fixed. As of Sprint 1: `_parse_cv_date()` and `_date_ranges_overlap()` were added, and a title conflict is now only flagged when the date ranges are confirmed to overlap; missing/unparseable dates stay conservative (no flag), consistent with the module's own stated "false positives are worse than missed contradictions" design. Covered by new tests in `test_match_contradictory_unclear.py` (`test_sequential_roles_with_no_overlap_are_not_a_conflict`, `test_missing_dates_are_conservative_no_flag`, plus direct tests of both new helper functions). All 22 tests in that file pass.

### Tailored CV generation — ⬜ Does not exist. This is the most important line in this document.

**There is no AI generation anywhere in this codebase.** Not a bug, not a partial implementation — a complete absence, confirmed by searching the entire `app/` directory for any OpenAI, Anthropic, or generic LLM client usage. The only hits are two unused config fields (`openai_api_key`, `openai_model`) that are never referenced anywhere else in the code — scaffolding for the *shape* of the config, not a real integration.

Concretely: the actual rewrite step that would take a `match_run`'s evidence and produce a job-tailored CV draft — the thing the product is named for — has no module, no implementation, nothing. There is no `tailored_cv_drafts` table row ever created by any code path today.

This is not a criticism of what's been built. The infrastructure around generation (extraction, matching with genuine 4-of-5 support levels, concurrency control, security hardening) is substantial, mostly high-quality, and exactly the kind of foundation that makes adding real generation safe once it happens. But every plan up to now has implicitly treated "Phase 3/4" as sequencing detail, when the reality is: **the actual product hasn't started being built yet.** See the Sprint plan below — this is Sprint 3.

---

## Phase 4 — Guided Cover Letter Workflow — ⚠️ HALF BUILT

**API layer — ✅ Code-verified, done.** All six endpoints exist in `app/api/v1/cover_letters.py` and are wired correctly: `POST /cover-letters/start`, `GET /cover-letters/{workflowId}/questions`, `POST /cover-letters/{workflowId}/answers`, `GET /cover-letters/{workflowId}/draft`, `POST /cover-letters/{workflowId}/regenerate`, `POST /cover-letters/{workflowId}/approve` — every one that operates on an existing workflow calls `_verify_ownership()` (IDOR-safe, matching the pattern established elsewhere).

Question generation (`generate_questions()` in `app/services/cover_letter.py`) is correctly evidence-driven: it only asks a clarifying question for evidence flagged `unsupported`/`contradictory`/`unclear`, never inventing a claim — the non-fabrication rule holds here.

**Draft content — ⬜ not AI-generated.** `assemble_draft()` builds the letter from fixed text templates filled in with the user's answers and match data (string concatenation and f-strings, no model call). This is evidence-safe — it can't fabricate, because it isn't generating language freely — but it is not what the product is supposed to be: a template-filled letter is not "AI-tailored." See Sprint 4 below.

---

## Phase 5 — Hardening and Release Readiness — ⚠️ IN PROGRESS

- ✅ **Task 2.1 — Auth rate-limit identity** (code-verified): `get_client_key()` in `app/core/rate_limit.py` no longer trusts `X-Forwarded-For` at all; falls back to TCP peer address only, with a docstring explaining why (no verified-proxy configuration exists to make a forwarded header trustworthy).
- ✅ **Task 2.2 — SSRF streamed response-size limit** (code-verified, commit `94321c0`): covered under Phase 2 above.
- ✅ **Task 2.3 — Per-user concurrent job limit** (code-verified, commit `64cfbbd`, current HEAD): `enforce_concurrent_job_limit()` in `app/services/orchestration.py` uses race-safe `SELECT ... FOR UPDATE` locking on the user row before counting active jobs; `mark_job_publish_failed()` is a shared helper called from all four publish-failure sites (`job_posts.py` ×3, `matches.py` ×1); `test_job_concurrency_limit.py` includes a genuine `asyncio.gather()` race test against a real Postgres connection. This was the most heavily-scrutinized fix in the project's history, went through three correction cycles, and the final version holds up.
- ✅ **Task 2.4 — Upload/generation/URL-fetch tiered rate limits** (code-verified, Sprint 1, 2026-08-10): `check_upload_rate_limit`, `check_generation_rate_limit`, `check_url_fetch_rate_limit` added to `rate_limit.py`, using isolated state per tier (a tier-prefixed bucket key) so exhausting one tier never affects another or the auth limiter. Wired into every job-creating endpoint: upload tier on `POST /cvs` and `/cvs/{id}/reprocess`; url_fetch tier on `POST /job-posts/url`; generation tier on `POST /job-posts/text`, `/job-posts/{id}/reprocess`, `POST /matches`, `POST /cover-letters/start`, `/cover-letters/{id}/regenerate`. 11 new tests in `test_tiered_rate_limits.py`, all passing.
- ✅ **`job_type` documentation note** (Sprint 1, 2026-08-10): added to `03-data-model.md` — clarifies which `job_type` values are multi-stage-pipeline stages vs. one-shot values, and why the column is `VARCHAR` rather than an enum/`CHECK`. This had been flagged three times across prior reviews without being done; it's done now.

> ⚠️ **Partial, early Phase 5 work: commit `8cd1eff`, "Phase 5: Rate limiting, parser resource limits, regression test."** Audited 2026-08-10 (Sprint 1) by reading the actual diff, not the commit message alone. It sits chronologically before the Task 2.1–2.3 hardening commits:
> - `app/core/rate_limit.py` (new, first version): a single-tier sliding-window limiter for `/auth/register` and `/auth/login`. Its `get_client_key()` trusted a caller-supplied `X-Forwarded-For` header directly — this was the spoofable identity bug Task 2.1 (`d91ee16`) later fixed by switching to TCP-peer-address-only. Nothing from this original version remains in the current limiter except the sliding-window/blocklist algorithm shape.
> - `app/api/v1/auth.py`: wired the above limiter into register/login (+19 lines) — this part held up and is still in place today, just behind the hardened `get_client_key()`.
> - `tests/test_regression_full_chain.py` (new): a full register → upload → parse → match → cover-letter-workflow regression test, plus a basic 6th-attempt-gets-429 rate-limit test. Still present and still the project's only true end-to-end regression test.
> - The commit message's "parser resource limits" is **not substantiated by this diff** — the three files above are the entire change. Don't treat parser resource limits as covered on the strength of this commit title alone.

**Still not started in Phase 5:** exports (`POST /exports/*` — no routes exist), ATS structural-readability check (extension #1), multi-job-post coverage reporting (extension #2), a full pass of `09-test-plan.md` §1–13, a full adversarial pass of `10-security-plan.md` §1–9, the `10-security-plan.md` §14 "what hardened means" sign-off, an incident-response tabletop, load/soak testing the queue and worker layer, and an external security review. These are Sprints 5 and 6 below.

---

## Anonymous trial support — ✅ Sprint 2 implemented and verified against a live Postgres instance (2026-08-11)

Implemented per the Sprint 2 design below, then verified end-to-end against a real, running Postgres instance (not just compile/import-checked) — migration round-trip, every new CHECK constraint, the concurrency race, the claim-trial transaction's atomicity, IDOR isolation, and the trial-cleanup task's full FK-dependency delete order all confirmed working against actual database behavior, not just code inspection.

> ✅ **Live-DB verification results (2026-08-11).** Postgres brought up via `docker compose up -d postgres`; verified against a fresh, isolated database (`cv_tailoring_verify`), not the project's existing dev database, which was found to already hold real accumulated data (62 users, 18 CV files, 4 match runs) and was deliberately left untouched.
> - **Migration round-trip**: `alembic upgrade head` (001→006) applied cleanly on a pristine schema; `alembic downgrade -1` then `alembic upgrade head` again both succeeded — the untested downgrade path (which relies on no trial-owned rows existing at that point) works as designed.
> - **Schema spot-check**: all 5 `ck_*_exactly_one_owner` CHECK constraints and every `trial_session_id` FK confirmed present via direct inspection of `pg_constraint`/`\d`, matching the design exactly.
> - **Two pre-existing ownership gaps found and fixed during verification, not deferred**: `POST /matches` (`matches.py::create_match`) and `POST /cover-letters/start` (`cover_letters.py::start_workflow`) both resolved a `jobPostId`/`cvId` from the request body with no ownership check at all — either gap could let one identity create a row referencing another identity's (including a trial session's) data, which would permanently wedge `cleanup_expired_trial_sessions` the next time that trial session expired (the dangling reference triggers a foreign-key violation that rolls back the *entire* cleanup batch, not just the affected session). Both fixed using the same `identity_owner_filter`/ownership-join pattern already used everywhere else.
> - **Claim-trial extracted for testability**: the reassignment transaction moved out of the `POST /auth/claim-trial` route handler into `app/services/trial_session.py::claim_trial_session()` — same precedent as Task 2.3's `enforce_concurrent_job_limit` extraction, and for the same reason (testable directly, without going through FastAPI's DI/HTTP layer).
> - **New test files, all passing against the live database**: `test_trial_session_constraints.py` (10 tests — CHECK constraints genuinely fire, including on `processing_jobs`, the highest-risk table since its `user_id` was already nullable pre-Sprint-2), `test_trial_session_concurrency.py` (5 scenarios including a real `asyncio.gather` race, keyed by `trial_session_id`), `test_trial_session_identity.py` (9 tests — trial header resolution, expiry/claim/precedence including the fail-closed "invalid bearer token doesn't fall back to anonymous" edge case, plus IDOR checks), `test_claim_trial.py` (5 tests — full 5-table reassignment including `cv_profile_versions`, and atomicity proven by rolling back instead of committing and confirming nothing persisted), `test_trial_session_cleanup.py` (4 tests — full row-tree deletion across every child table the task is responsible for, confirming the FK-dependency delete order reasoned out ahead of time is actually correct).
> - **Full suite**: 120 passed, 1 pre-existing unrelated skip, 7 pre-existing failures all in `test_ssrf_fetch.py` — confirmed via empty `git diff` that this file was never touched this session; 6 are a case-sensitivity bug in the test's own regex (`match="scheme"` vs. the code's actual `"Scheme '...'"` message) and 1 needs real DNS resolution unavailable in this sandbox. No regressions. (`test_confidence_and_merge.py`, `test_pipeline_stage_transitions.py`, and `test_regression_full_chain.py` need `docling` or the full Docker stack and weren't run in this pass — pre-existing scope, not part of Sprint 1/2.)
> - ⚠️ **New, unrelated finding — not investigated, flagged only:** the project's actual dev database (`cv_tailoring`, reached via `docker exec backend-postgres-1`) already held real accumulated data (62 users, 18 CV files, 4 match runs) and was deliberately left untouched for this verification — a fresh `cv_tailoring_verify` database was used instead, later dropped. While confirming that, `cv_tailoring`'s `alembic_version` table was found stuck at `003` even though migration `004`'s column (`match_runs.contradictory_count`) already exists in that database — running `alembic upgrade head` against it as-is fails with `psycopg2.errors.DuplicateColumn`. This means someone applied migration `004`'s schema change to this database without Alembic recording it (a manual `ALTER TABLE`, a hand-edited migration, or a `stamp` that didn't take). Migrations `004`–`006` cannot be applied to this database until this is resolved — most likely an `alembic stamp 004` (or later) after manually confirming which of `004`/`005`'s changes are actually present, but this needs a deliberate look, not a guess baked into this doc.

**What got built, file by file:**
- **Schema** (`app/db/models.py`, migration `006_trial_sessions.py`): new `TrialSession` table (`id`, `created_at`, `expires_at`, `claimed_by_user_id`, `claimed_at`, `ip_address`). `user_id` relaxed to nullable + a new nullable `trial_session_id` FK, each with an "exactly one owner" `CHECK` constraint, on `cv_files`, `job_posts`, `match_runs`, and `processing_jobs`.
- **New dependency** (`app/core/security.py`): `RequestIdentity` (a real user XOR a trial session) and `get_current_user_or_trial_session()`, which wraps `get_current_user()` rather than modifying it — a valid Bearer token always wins over an `X-Trial-Session-Id` header. A shared `identity_owner_filter()` helper builds the right ownership `WHERE` clause for whichever identity resolved, reused across every route below instead of re-derived per call site.
- **New endpoint**: `POST /trial-sessions` (new router, `app/api/v1/trial_sessions.py`) — creates the session, rate-limited on its own tier (see below).
- **Route wiring**: `POST /cvs`, `POST /job-posts/url`, `POST /job-posts/text`, `POST /matches` switched to the new dependency, exactly as speced.
- **`POST /auth/claim-trial`** (`app/api/v1/auth.py`): single-transaction reassignment — nothing commits until every table's rows are reassigned and the trial session is marked claimed, so a mid-transaction failure rolls back everything rather than leaving a partial reassignment (relies on `AsyncSession`'s context-manager rollback-on-exception, the same mechanism every other multi-row write in this codebase already depends on).
- **Abuse controls**: a dedicated `trial_session` rate-limit tier (tighter than the others — 5/hour by default, since this is the one unauthenticated way to mint a new identity); `enforce_concurrent_job_limit()` extended to lock/count by either `user_id` or `trial_session_id`.
- **Expiry cleanup**: `cleanup_expired_trial_sessions` Celery task (`app/workers/worker_jobs.py`) — deletes an expired, unclaimed session and every row still attached to it, in FK-dependency order.
- **Tests**: `test_request_identity.py` (new — `RequestIdentity`/`identity_owner_filter`, DB-independent) and trial-tier additions to `test_tiered_rate_limits.py`. 53 passed, 1 pre-existing unrelated skip.

**Corrections and gaps found while implementing — none of these were visible from the design doc alone; all surfaced by tracing the actual data flow:**

1. **`cv_profile_versions` needed the same treatment as `cv_files`, and this was missing from the original scope.** `worker_jobs.py`'s `cv_parse` step copies `user_id=cv_file.user_id` onto the new `CvProfileVersion` row. Since `cv_files.user_id` is now nullable for trial uploads, leaving `cv_profile_versions.user_id` as `NOT NULL` would have crashed the parse pipeline on the very first trial CV — a `NOT NULL` constraint violation on an otherwise-working code path, only two steps downstream of the upload. `cv_profile_versions` now gets the identical nullable-`user_id` + `trial_session_id` + `CHECK` treatment, and `cv_parse` copies both fields, not just one. This also means `claim-trial`'s reassignment had to include `cv_profile_versions`, not just `cv_files`.
2. **`processing_jobs` needed a `trial_session_id` column after all**, despite the Sprint 2 design's own correction (above, in the Sprint plan section) noting `user_id` didn't need to become nullable there. Those are two different questions: `user_id` nullable was already true; a `trial_session_id` column to key `enforce_concurrent_job_limit()` and the cleanup task's queries off of is new and was still required.
3. **Four read endpoints needed to switch to the trial-or-user dependency that weren't in the original "which routes actually change" list**: `GET /cvs/{cvId}`, `GET /cvs/{cvId}/parsed-profile`, `GET /jobs/{jobId}`, and `GET /job-posts/{jobPostId}`. Without these, a trial session has no way to poll upload/match status or retrieve its own `profileVersionId` — the sprint's own demo criterion ("upload a CV and run a match with no account") is unachievable without them. `GET /matches/{matchId}` was already planned. No other read/list/delete endpoints were extended — the account-paywall boundary elsewhere is unchanged.
4. **No Celery beat (or any cron) infrastructure exists in this codebase for any task, not just this one.** The cleanup task is written and callable, but nothing periodically invokes it yet. That's a separate infra decision (a new service in `docker-compose.yml`, a beat schedule) that wasn't picked here rather than being silently assumed away.
5. **Pre-existing, unrelated to this sprint:** `POST /matches` looks up the target `JobPostProfile` by `jobPostId` with no ownership check at all (any authenticated user or trial session can match against any job post's structured profile, not just their own). This predates Sprint 2 and wasn't introduced by it — flagged here rather than silently fixed, since changing it wasn't asked for and deserves its own confirmation first.

---

## Recurring patterns worth naming

Two patterns are confirmed across enough instances to call them patterns, not incidents:

1. **Docstrings describing intended behavior ahead of the code that implements it.** This happened at least three times in the same function (`_build_consistency_map`) across review cycles, plus earlier SSRF and confidence-score instances. Not a quality problem with the code itself — a process problem: documentation gets written as a statement of design intent and isn't re-checked against the function it sits above once the implementation lands or changes. The `_build_consistency_map` instance is now fixed (Sprint 1); worth watching for recurrence rather than assuming it's solved as a category.
2. **Foundational, security-adjacent work has consistently been prioritized over the product's core generation feature.** Not a criticism — rate limiting, SSRF, concurrency limits, and soft-delete are all real and important — but several sprints of hardening work happened around a product that doesn't yet do the one thing it's for. This is the reason the sprint plan below reorders Sprint 2/3 ahead of further hardening polish.

---

## Open decisions — status check

| Decision | Needed by | Status | Note |
|---|---|---|---|
| LLM provider and model | Phase 3 (Sprint 3) | ✅ Pinned and confirmed (2026-08-11) | **Provider: OpenAI API**, using the existing platform API key. This is the standard OpenAI API (developer platform), not the ChatGPT consumer product. **Model: cost-efficient tier (`gpt-4o-mini` class)**, replacing the `gpt-4o` placeholder — matches this doc's own `~$0.04–$0.05`/call cost target (§6/cost table) for these short, structured-field rewrite calls rather than long free-form generation. **Data Controls confirmed (2026-08-11):** the OpenAI platform account's Data Controls setting is saved as disabled — no data shared with OpenAI for model training/improvement. Compliance concern closed; no outstanding action here. |
| Export file formats/templates | Phase 5 (Sprint 5) | Unresolved | No change. |
| Cost alert thresholds | Phase 5 (Sprint 5/6) | Unresolved | No change. |
| Endpoint-tier rate limit values | Phase 1/3 | ✅ Done (structure + enforcement) | Config fields exist with the tiered structure correctly separated from the general limit, **and**, as of Sprint 1 (2026-08-10), actually enforced — all three non-auth tiers are wired into every job-creating endpoint. Placeholder *values* still need tuning against real traffic post-launch, but that's a tuning task, not an implementation gap. |
| Malware scanner selection | Phase 1 | ✅ Done | Code-verified. |

---

## Security plan gaps (`10-security-plan.md` §13) — status check

| # | Gap | Status | Note |
|---|---|---|---|
| 1 | Malware scanning on upload | ✅ Done | Code-verified. |
| 2 | SSRF protection on job post URL fetch | ✅ Done | Was tracked pending; code-verified done — see Phase 2 above. |
| 3 | Evidence-reference content verification | ⬜ Pending | Phase 3, not started (blocked on generation not existing yet). The requirement is that a validation step confirms the referenced source (e.g. a specific `cv_experience_items.id`) *actually contains text supporting the specific claim it's attached to* — not merely that a syntactically valid reference ID was supplied. A check that only confirms "a UUID was provided" satisfies the schema but not the security requirement. This becomes directly relevant once Sprint 3 builds tailored CV generation. |
| 4 | Security tests cross-referenced into test plan | ✅ Done | `09-test-plan.md` §9 points into `10-security-plan.md` §1, §2, §3, §4, §5, §10, and §14 by section number. Documentation-only, resolved. |
| 5 | Endpoint-tier rate limit granularity | ✅ Done | Was "structure done, enforcement pending" — as of Sprint 1 (2026-08-10) enforcement is done too, see Open Decisions above. Tuning placeholder values against real traffic remains a post-launch task. |

---

## Product extensions — unchanged

Extensions #1 (ATS check) and #3 (fix-it checklist) build in/around Phase 3, #2 (multi-job-post coverage) lands in Phase 5, #4 and #5 are schema-only reservations already specified but not yet built, #6 remains explicitly flagged as needing a separate go/no-go conversation before any design work starts.

---

## Sprint plan to project completion

Sprints are scoped to be independently shippable and independently verifiable — each one should end with something a developer could demo. Sizing assumes roughly the same pace as Task 2.3 (a security-adjacent, moderately complex piece of work spanning three correction cycles took about a week of focused effort with this level of review rigor) — treat these as planning estimates, least reliable for Sprints 2 and 3 specifically, since nothing at that depth (new identity model, first LLM integration) has been built in this codebase yet and it may move at a different pace than the extraction/matching work did. Replan after Sprint 2's actual velocity is observed.

### Sprint 1 — Close the security/hardening backlog — ✅ COMPLETE (2026-08-10)

All four items done and tested (47 passed, 1 pre-existing unrelated skip); see Phase 3 and Phase 5 sections above for what changed. **Committed as `53f3452`** on local `main`.

### Sprint 2 — Anonymous trial support — ✅ COMPLETE and verified (2026-08-11)

Goal: make the "try for free, no account required" flow actually possible to build against. New backend work, not a frontend concern.

**Status:** written, wired, and verified against a live Postgres instance — see the "Anonymous trial support" section above for the full verification write-up, including the corrections found while implementing (`cv_profile_versions` needed the same nullable-owner treatment as `cv_files`; `processing_jobs` needed a `trial_session_id` column after all; four read endpoints needed to join the trial-accessible set for the demo criterion to be achievable) and the two ownership gaps found and fixed during verification (`POST /matches`, `POST /cover-letters/start`). Migration round-trips cleanly; all new tests pass against real Postgres. **Committed as `25ad817`** on local `main`, not yet pushed to `origin` — see Immediate next actions. **Still genuinely outstanding**: no Celery beat (or other cron) scheduler exists anywhere in this codebase yet, so `cleanup_expired_trial_sessions` is written and tested but nothing invokes it periodically — that's a separate infra decision. A full HTTP-level end-to-end walkthrough (the actual demo below, through the real API with Celery workers running) also wasn't done — this verification pass proved schema/transaction/concurrency correctness at the DB layer, not the full stack end-to-end, which needs the full `docker compose up` (workers, MinIO, ClamAV) this pass deliberately didn't bring up.

**Design (as originally specced):**

- **New concept: `trial_session`.** A row created when an anonymous visitor starts a trial — `id` (opaque token, not a guessable sequential ID), `created_at`, `expires_at` (recommend 24-48 hours — a trial left unclaimed for a week is functionally abandoned and shouldn't linger as unowned data), `claimed_by_user_id` (nullable, set once attached to a real account), `ip_address` (for the abuse controls below — see `10-security-plan.md` §4/§9 on what's storable here). No `email`, no PII beyond what the CV upload itself already collects.
- **Schema change:** `user_id` becomes nullable on `cv_files`, `job_posts`, `match_runs`, and `tailored_cv_drafts` (once it exists in Sprint 3), each gaining a new nullable `trial_session_id` FK. **Correction to the original scope of this item:** `processing_jobs.user_id` does *not* need to become nullable — it's already `nullable=True` in `models.py` and in the original `001_initial_phase1.py` migration, most likely because system-initiated jobs never had a user. **But as implementation revealed (see the "Anonymous trial support" section above), `processing_jobs` still needs its own new `trial_session_id` column** — that's a separate question from whether `user_id` needed relaxing, needed to key `enforce_concurrent_job_limit()` and the cleanup task by trial identity. And `cv_profile_versions` — not listed in the original four tables at all — turned out to need the identical treatment `cv_files` gets, since it copies `cv_files.user_id` at parse time. Exactly one of `user_id`/`trial_session_id` populated at creation — enforce with a `CHECK` constraint, not just application logic, so a bug can't silently create an orphaned row with neither. (Note on precedent: `03-data-model.md` §4 rule 3 establishes the same non-empty/non-null discipline for `evidence_references`, but enforces it at the validation layer, not via an actual SQL `CHECK` — so this would be a *new* instance of DB-level enforcement in this codebase, a stronger version of the existing pattern, not a literal repeat of one that already exists at the DB layer.)
- **New dependency: `get_current_user_or_trial_session`.** Separate from `get_current_user`, which stays untouched. Accepts either a valid Bearer token (existing behavior) or a valid `X-Trial-Session-Id` header matching a non-expired `trial_session` row (returns a lightweight trial identity). Only routes that should support anonymous use switch to it: `POST /cvs`, `POST /job-posts/url`, `POST /job-posts/text`, `POST /matches`, and the Sprint 3 generation endpoint. Everything else (auth, dashboard lists, cover letters, exports) stays on `get_current_user` exactly as today — matching the product vision's consistent paywall boundary ("cover letter and beyond require an account").
- **Claim-on-registration:** new endpoint, e.g. `POST /auth/claim-trial`, called right after register/login when the frontend is carrying a trial session. Verifies unexpired and unclaimed, then in one transaction: sets `claimed_by_user_id`, reassigns every row currently pointing at that session to the new `user_id` (clear `trial_session_id`, set `user_id`).
- **Abuse controls (new attack surface, needs its own `10-security-plan.md` entry, not an assumption existing controls cover it):**
  - Rate-limit trial-session *creation* by IP, same `rate_limit.py` pattern from Sprint 1.
  - Apply `enforce_concurrent_job_limit` to trial sessions too, keyed by `trial_session_id` instead of `user_id`.
  - Malware scanning, file-type/size validation, and SSRF protections already apply at the file/URL level, not the auth level — confirm directly rather than assume.
  - Document a per-IP/per-session trial-creation cap as an accepted limitation (true "one free trial per person" enforcement requires device fingerprinting, which is unreliable and privacy-sensitive) rather than trying to solve it this sprint — gate what actually matters (repeated generation/cover-letter use) behind the account boundary instead, per the existing product plan.
- **Trial session expiry cleanup:** scheduled task deleting expired, unclaimed `trial_session` rows and associated data, per `06-non-functional-requirements.md`'s retention discipline.

**Test coverage:** anonymous upload + match with no token; claim-on-registration reassignment in one transaction with no orphaned rows even on partial failure (test the failure case, not just happy path); expired trial rejected; a trial session can't access another trial's or another user's data (same IDOR discipline extended to the new identity type); concurrent-job limit and rate limits apply to trial sessions exactly as to real users.

**Demo:** upload a CV and run a match with no account, then register and see that same CV/match already present in the new account's dashboard.

**Schedule note:** Sprint 3 explicitly requires trial-session-accessible generation, so a slip here is a slip in Sprint 2 + Sprint 3 combined, not just Sprint 2 — this is the single biggest schedule risk in the whole plan.

### Sprint 3 — Tailored CV generation, the actual feature (large, ~1-2 weeks)

Goal: the sprint where the product starts doing what it's named for.

- Pin the LLM provider/model decision — **start this now, in parallel with Sprint 2** (see Open Decisions above), not at the top of this sprint.
- Build the generation module: takes a `match_run`'s evidence (supported/partial items only — never unsupported/contradictory/unclear, per the non-fabrication rule already established elsewhere), produces a tailored CV draft.
- Must go through schema-constrained/structured output, consistent with every other AI-adjacent design decision in this pack (`02-architecture-overview.md` §6). This must not be the first place free-form generation gets used unconstrained.
- Every generated claim needs a traceable evidence reference back to the source `match_evidence_item`, reusing the `evidence_references` pattern already established in `cover_letter.py`, not reinventing it.
- The generation endpoint must accept the trial-session identity from Sprint 2, not just authenticated users — the tailored CV is the free-tier value delivered *before* the account wall. Easy to build authenticated-only by default and miss this; confirm explicitly.
- Full test coverage: strong evidence → full draft; thin evidence → correctly less content, not filled gaps; a deliberate test that `unsupported`/`contradictory`/`unclear` evidence never appears in generated output.

**Demo:** submit a real CV + job post as an anonymous trial session and get back an AI-generated tailored draft, every claim traceable to its evidence.

### Sprint 4 — Real cover letter generation (medium, ~4-6 days)

Goal: replace template assembly with genuine generation, reusing the pattern Sprint 3 proves.

- Reuse Sprint 3's generation infrastructure (same provider, same structured-output discipline, same evidence-binding pattern) rather than a second pipeline.
- `assemble_draft()` becomes the fallback/template layer only if generation fails or is explicitly disabled — not the primary path.
- `generate_questions()`'s existing evidence-driven logic stays as-is; only final draft assembly changes.
- Test coverage: generated letter incorporates actual answers (not generic filler), never states anything the evidence doesn't support.
- Cover letters sit behind the account paywall per the product vision — this endpoint stays on `get_current_user` only, the opposite rule from the sprint immediately before it. Confirm explicitly.

**Demo:** the full guided cover-letter flow, ending in a genuinely AI-written letter grounded in real answers and evidence.

### Sprint 5 — Exports and remaining Phase 5 product surface (medium, ~1 week)

- `POST /exports/cv/{draftId}`, `POST /exports/cover-letter/{workflowId}`, `POST /exports/application-pack` — none exist yet. Pin the export format decision (`08-deployment-guide.md` §1) before building beyond a stub.
- ATS structural-readability check (`11-product-extensions.md` §1) — rules-based, no generation dependency, genuinely independent of Sprints 3-4 and could be pulled forward if there's spare capacity earlier.
- Multi-job-post coverage reporting (`11-product-extensions.md` §2) — same independence.

**Demo:** upload through to a downloaded, tailored application pack.

### Sprint 6 — Full hardening pass and pre-launch review (medium-large, ~1 week)

- Run every test in `09-test-plan.md` §1-13 end to end, not just the subset with test files so far.
- Run the full adversarial test list in `10-security-plan.md` §1-9 against current code, including everything added since the security plan was first written.
- Confirm the `10-security-plan.md` §14 "what hardened means" bar — gaps resolved or explicitly risk-accepted with an owner, at least one incident-response tabletop run.
- Load/soak test the queue and worker layer now that generation calls (the slowest, most expensive step) are actually in the pipeline.
- Get an external security review before this goes anywhere near real user data.

**Demo:** a documented, evidenced sign-off that the system meets its own stated security and quality bar.

---

## What to prioritize if the timeline gets compressed

Cut Sprint 5 first if needed — genuinely valuable but the product is demonstrable without it.

Sprint 2 (anonymous trial support) is tempting to cut because it's new, large scope rather than a known fix — but it isn't optional if "try before you register" stays part of the product. If timeline pressure is severe enough to consider dropping it, the honest alternative is a deliberate product decision to require registration upfront for the first release, made explicitly with whoever owns the product vision — not a silent schedule slip that leaves the frontend team building against a flow the backend was never going to support in time.

Sprint 3 (tailored CV generation) is the actual product; Sprint 6 (hardening/pre-launch review) is the actual safety gate. Neither should be the one that gets compressed under deadline pressure.

---

## Immediate next actions, in order

1. ~~Commit Sprint 1 and Sprint 2~~ — ✅ **done** (2026-08-11): `53f3452` (Sprint 1), `25ad817` (Sprint 2) on local `main`. See the "Anonymous trial support" section above for the full verification write-up.
2. **Push local `main` to `origin`** — local history was squashed (co-author trailer removed, duplicate merge lines from parallel sessions collapsed) and is now `ahead 2, behind 8` of `origin/main`; syncing requires an explicit force-push, not a plain push. Deliberately not done yet pending go-ahead.
3. ~~Start the LLM provider/model decision~~ — ✅ **pinned and confirmed** (2026-08-11): OpenAI API, cost-efficient tier (`gpt-4o-mini` class), Data Controls confirmed saved as disabled (no data shared with OpenAI) — see Open Decisions above. No outstanding action.
4. **Wire up a Celery beat (or equivalent) scheduler** for `cleanup_expired_trial_sessions` — written and tested, but nothing invokes it periodically yet. Small, but genuinely open.
5. **Investigate the `cv_tailoring` dev database's stuck `alembic_version`** (see the new flagged finding in the "Anonymous trial support" verification block above) — blocks ever running real migrations against that database again until resolved.
6. **Sprint 3 immediately follows** — track Sprint 2 + Sprint 3 combined duration as the number that determines whether this plan hits its dates, not either sprint's estimate alone. Sprint 2's actual velocity (implemented, IDOR-audited, and DB-verified in one session) is worth using to sanity-check the Sprint 3 estimate rather than the original Task-2.3-based planning number.
