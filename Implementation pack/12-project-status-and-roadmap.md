# Project Status and Roadmap

This is the single canonical status tracker for the project — status history, current state, and the forward sprint plan, all in one place. It previously existed as two documents (this file, plus a separately-circulated "Project Update and Sprint Plan" review); the second has been folded in here as of **2026-08-10** so there is one source instead of two that can drift out of sync with each other. Nothing from either source was dropped silently: where the two disagreed, or where a claim in either one didn't hold up against a fresh code check, it's corrected below with the correction visible, not quietly merged away.

Base commit for everything in this document: `64cfbbd`, **plus** Sprint 1 (2026-08-10) and Sprint 2 (2026-08-11), both now committed on local `main` as `53f3452` (Sprint 1) and `25ad817` (Sprint 2). Local history was subsequently squashed to drop a Claude co-author trailer and collapse a 3x-duplicated merge history that came from parallel sessions redoing the same work — the two commits above replaced the original `9b612f7`/`0d8a864` (and their duplicates) with identical trees, same authorship/timestamps, cleaner history. **Pushed** — confirmed via `git fetch` that local `main` and `origin/main` are fully in sync.

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
| 3 — Matching and tailored CV drafting | ✅ Complete, verified live | Matching engine (5 support levels) and tailored CV generation (Sprint 3, 2026-08-11) both done. Real OpenAI generation, schema-constrained, independently evidence-verified — see below. |
| 4 — Guided cover letter workflow | ⚠️ Half built | All 6 endpoints exist and are ownership-checked. The draft itself is template-assembled text, not AI-generated. Sprint 3's generation infrastructure is now available to reuse here (Sprint 4). |
| 5 — Hardening and release readiness | ⚠️ In progress | Tasks 2.1–2.4 (rate-limit identity, SSRF streaming, concurrency limit, tiered rate limits) are all done as of Sprint 1 (2026-08-10). ATS check (Extension #1) done and verified. Exports, full security/test-plan pass, and incident-response tabletop are not started. |
| — Anonymous trial support | ✅ Complete, verified live, committed | Sprint 2 (2026-08-11): schema, dependency, route wiring, claim-on-registration, abuse controls, and expiry cleanup all written and verified against a real Postgres instance — migration round-trip, CHECK constraints, concurrency race, claim-transaction atomicity, IDOR, and the cleanup task's full delete order all confirmed. Two pre-existing ownership gaps found and fixed along the way. Committed as `25ad817`, pushed; scheduler wired up (not yet live-verified). |

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

## Phase 3 — Matching and Tailored CV Drafting — ✅ COMPLETE (2026-08-11)

### Matching engine — ✅ Code-verified, done
`app/extraction/match_engine.py` implements all five documented support levels (`supported`/`partially_supported`/`unsupported`/`contradictory`/`unclear`) with a weighted scoring model. Contradictory-evidence detection compares same-company role titles for conflicting families (`_roles_conflict`).

> ✅ **Previously flagged docstring/code mismatch — fixed 2026-08-10 (Sprint 1).** `_build_consistency_map()`'s docstring claimed date-overlap detection ("overlapping date ranges with conflicting titles") that the code didn't actually implement — it only compared company and title, meaning any title change at the same company got flagged regardless of timing, including ordinary sequential job changes. This was flagged three times across review cycles without being fixed. As of Sprint 1: `_parse_cv_date()` and `_date_ranges_overlap()` were added, and a title conflict is now only flagged when the date ranges are confirmed to overlap; missing/unparseable dates stay conservative (no flag), consistent with the module's own stated "false positives are worse than missed contradictions" design. Covered by new tests in `test_match_contradictory_unclear.py` (`test_sequential_roles_with_no_overlap_are_not_a_conflict`, `test_missing_dates_are_conservative_no_flag`, plus direct tests of both new helper functions). All 22 tests in that file pass.

### Tailored CV generation — ✅ Built and verified live (2026-08-11)

**Sprint 3 shipped.** `POST /matches/{matchId}/tailored-cv`, `GET /tailored-cvs/{draftId}`, `POST /tailored-cvs/{draftId}/regenerate`, `POST /tailored-cvs/{draftId}/approve` — all four endpoints from `05-openapi.yaml`, trial-session-accessible, following `matches.py`'s create-entity-then-job pattern (not `create_processing_job()` — a `tailored_cv_drafts` row, like a `match_run`, has to exist before its worker runs, in the same transaction). OpenAI API, `gpt-4o-mini`, JSON-schema strict mode — no free-text generation anywhere.

**The evidence-verification gap this sprint had to solve first.** `match_evidence_items.source_references` — the field the security plan's evidence-reference-content-verification requirement (§13 gap 3) depends on — turned out to be populated in exactly one of five support-level branches in `match_engine.py` (a `"skill:<name>"` tag string, not a real row id), and empty everywhere else. Rather than retrofitting `match_engine.py` (would touch a shipped Phase 3 pipeline for a fix that still wouldn't verify a not-yet-generated claim), generation re-derives evidence bindings itself at generation time, directly from the CV's current `CvExperienceItem`/`CvEducationItem`/`CvSkillItem` rows (`app/extraction/evidence_binder.py`) — fresher than a match-time snapshot, and the only place a real, resolvable row id exists at all.

**Verification is a real, independent check, not a UUID-presence check.** Every generated claim is checked against the *actual text* of the rows it cites: a token-overlap floor (catches wholesale invention) plus a hard-fact check (every number and multi-word capitalized span in the claim must appear in the cited evidence — catches one invented statistic dropped into an otherwise-grounded sentence). The model cites small integer indexes into a pool the code controls, never raw row ids, so citing something it was never shown is structurally impossible, not just discouraged. Failed verification gets one corrective retry, then the section is omitted entirely — never persisted unverified.

> ✅ **Live verification (2026-08-11).** Migration `008` round-trips cleanly (`001`→`008` upgrade, `-1` downgrade, upgrade again) against an isolated Postgres instance. 52 new tests, all passing: `test_evidence_binder.py` (22, pure-function — includes a caught-and-fixed real bug: the number-extraction regex silently failed to match magnitude-suffixed numbers like "50M" due to a `\b` word-boundary gap between digit and letter, which would have let a fabricated statistic slip past verification undetected; also caught and fixed a false-positive bug where sentence-initial capitalization ("Experienced Python...") was mistaken for a 2-word named entity, which would have incorrectly rejected well-grounded content), `test_tailored_cv_generation.py` (17, orchestrator against a fake LLM client — fabrication rejection, empty-evidence omission, corrective retry, contradictory/unclear exclusion), `test_tailored_cv_endpoints.py` (13, live DB, including a genuine end-to-end Celery→Redis publish, not stubbed). Full suite: 190 passed, 1 pre-existing unrelated failure (`test_confidence_and_merge.py`, confirmed via empty `git diff` that it was never touched), no regressions.
>
> Two environment issues found and resolved during this pass, not code bugs: (1) the dev venv had drifted to `fastapi==0.141.1` against the `0.115.6` pin — some earlier ad-hoc `pip install` had pulled a newer version transitively, silently changing FastAPI's route-registration internals enough that routes appeared not to register at all; re-pinned to match `requirements.txt`. (2) `enqueue_cv_generate`'s Celery publish appeared to hang for 5+ minutes — actually a slow failure, not a hang: `REDIS_URL` resolves to the Docker-internal hostname `redis` from `.env.local`, unreachable from the host, exactly the same class of issue as `DATABASE_URL` needing a `localhost` override for host-side testing, just not previously hit because no earlier live-DB test in this codebase had exercised a real Celery publish to completion. Confirmed this affects every job type, not just `cv_generate` (`enqueue_ats_check` hangs identically) — a pre-existing gap in this codebase's testing docs, not something Sprint 3 introduced.

**What got built, file by file:** `app/extraction/evidence_binder.py` (evidence binding + verification, no LLM), `app/services/llm_client.py` (OpenAI wrapper — first LLM integration in this codebase, schema-validation retry, typed exceptions, injectable for tests), `app/prompts/tailored_cv_prompts.py` (versioned system prompts, instruction/data separation per `10-security-plan.md` §5), `app/services/tailored_cv_generation.py` (orchestrator — summary + per-experience-item + deterministic skills sections, improvement-checklist synthesis), `app/api/v1/tailored_cvs.py` (the 4 endpoints), `app/schemas/tailored_cv.py`, migration `008` (`tailored_cv_drafts`/`tailored_cv_sections`, nullable-owner + CHECK constraint pattern, plus a new non-empty-evidence-references DB CHECK beyond what the data-model doc specified), `worker_jobs.py::process_cv_generate`, `tasks.py::enqueue_cv_generate`, a new `worker_cv_generate` Celery service in `docker-compose.yml` (learned from the ATS-check review: a queue with no consuming worker is a silent dead end), two new Prometheus metrics (`LLM_TOKENS_COUNTER`, `LLM_GENERATION_COUNTER`).

**Decisions made explicitly, not defaulted into** (see plan file for full reasoning): `tailored_cv_drafts.status` extended to 6 values (`pending`/`failed` added beyond the documented 4, `05-openapi.yaml` updated to match) — forced by creating the draft row before its worker runs, same shape as `MatchRun.status`. Education/certifications/projects sections ship empty this sprint — correct non-fabrication behavior, since `CvEducationItem` is never populated anywhere in this codebase today and no certification/project tables exist at all (confirmed via repo-wide grep, not assumed). Full prompt/response logged to `AuditEvent` for injection investigation; the resulting data-retention policy question is a flagged follow-up, not a blocker. Repeat `POST .../tailored-cv` on an already-drafted match returns 409, not a silent new version — `/regenerate` is the only versioning path.

Also found and corrected while reviewing this section: `schemas/cover_letter.py` uses the inverted field-name/alias convention (camelCase field name, snake_case alias) — verified directly against FastAPI's actual serialization behavior that this silently produces **snake_case** JSON output instead of the camelCase the OpenAPI spec documents, for every field where the two differ (`currentStep`, `questionSetVersion`, `createdAt`, etc. in `CoverLetterWorkflowResponse`). Pre-existing Phase 4 bug, not introduced or fixed this session — flagged here since it directly cost real debugging time when `schemas/tailored_cv.py` was being written and the wrong convention was nearly copied from it.

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
> - ✅ **`alembic_version` anomaly — investigated and resolved (2026-08-11).** The project's actual dev database (`cv_tailoring`, reached via `docker exec backend-postgres-1`) holds real accumulated data (62 users, 18 CV files, 4 match runs) and was deliberately left untouched during the original Sprint 2 verification — a fresh `cv_tailoring_verify` database was used instead, later dropped. `alembic_version` was found stuck at `003` even though migration `004`'s columns already existed. Direct schema inspection (`\d` on every affected table, compared column-by-column against the actual migration files) confirmed **migrations 004 and 005 are fully and correctly applied** — `match_runs.contradictory_count`/`unclear_count` and all four `cover_letter_*` tables match their migration definitions exactly; only the bookkeeping was wrong, not the schema. Migration `006` (trial sessions) is confirmed **not** applied (no `trial_sessions` table, no `trial_session_id` columns anywhere) — expected, since that's this session's own Sprint 2 work, never previously run against this database. **Fix applied:** `alembic stamp 005` — metadata-only, executes no DDL, doesn't touch data. Verified before/after: `alembic_version` now correctly reads `005`; row counts unchanged (62/18/4). Migration `006` was deliberately **not** applied to this database as part of this fix — a separate decision, held for later.

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
5. ~~Pre-existing, unrelated to this sprint: `POST /matches` looks up the target `JobPostProfile` by `jobPostId` with no ownership check at all~~ — ✅ **fixed** (was fixed during the Sprint 2 live-DB verification pass, see the IDOR-fixes note above; this line was left stale afterward and is corrected now, 2026-08-11). Re-verified directly against current code: `identity_owner_filter(JobPost, identity)` is present in the `JobPostProfile` join in `matches.py::create_match`.
6. **Code-quality pass (2026-08-11), 3 real findings fixed in `orchestration.py`/`trial_session.py`:** `create_processing_job`'s XOR guard was falsy-based (`if not user_id and not trial_session_id:`) instead of identity-based like `enforce_concurrent_job_limit`'s — direct comparison of the two across all input combinations showed this wasn't just a style mismatch: the falsy guard never caught the case where **both** `user_id` and `trial_session_id` were set, silently violating the "exactly one owner" invariant until the DB's `CHECK` constraint caught it later as an opaque failure. Now identity-based (`is None`), matching line 38 exactly. Also fixed: two PEP 8 blank-line spacing defects around `mark_job_publish_failed`, and `claim_trial_session()` (`trial_session.py`) had zero logging despite being a 5-table data-reassignment — every comparable write path elsewhere logs (`orchestration.py`'s `job_created`), this one didn't; added a `trial_claimed` info log with the reassignment counts. Separately noted but not acted on: no linter (`ruff`/`flake8`) or CI is configured under `backend/` at all, so nothing catches a spacing recurrence — an accepted gap, not addressed here.

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
| 3 | Evidence-reference content verification | ✅ Done | Sprint 3 (2026-08-11): `app/extraction/evidence_binder.py::verify_claim_against_evidence()` checks a generated claim's actual text against the real content of the rows it cites (token-overlap floor + hard-fact check on numbers/named entities) — not merely that a syntactically valid reference was supplied. The model cites pool indexes, never raw row ids, so an unverifiable reference is structurally impossible, not just checked-for. |
| 4 | Security tests cross-referenced into test plan | ✅ Done | `09-test-plan.md` §9 points into `10-security-plan.md` §1, §2, §3, §4, §5, §10, and §14 by section number. Documentation-only, resolved. |
| 5 | Endpoint-tier rate limit granularity | ✅ Done | Was "structure done, enforcement pending" — as of Sprint 1 (2026-08-10) enforcement is done too, see Open Decisions above. Tuning placeholder values against real traffic remains a post-launch task. |

---

## Product extensions

Extensions #3 (fix-it checklist) builds in/around Phase 3, #2 (multi-job-post coverage) lands in Phase 5, #4 and #5 are schema-only reservations already specified but not yet built, #6 remains explicitly flagged as needing a separate go/no-go conversation before any design work starts.

### Extension #1 — ATS structural validation — 🛠️ implemented, not yet live-verified (2026-08-11)

Built by a junior developer as a parallel-safe task (no dependency on Sprint 3/4 or trial-session code — confirmed zero file overlap at handoff time). `app/extraction/ats_check.py` (6 pure-function checks + composite scorer, mirrors `heading_canonicalizer.py`'s style), migration `007` (`ats_readiness_checks` table), `POST /cvs/{cvId}/ats-check` + `GET /cvs/{cvId}/ats-check`, `process_ats_check` Celery task. 28 new tests, all pure-function/no-DB, all passing.

**Reviewed 2026-08-11 — 4 findings, all fixed before this could be verified against a live DB:**
1. **Critical, reproduced directly:** `AtsReadinessCheckResponse.cv_id` (per `05-openapi.yaml`'s documented `cvId` field) had no matching attribute on the `AtsReadinessCheck` model (`cv_file_id`, not `cv_id`) — `GET /cvs/{cvId}/ats-check` raised a Pydantic `ValidationError` on every successful lookup. Confirmed via direct reproduction, not just inspection. Fixed: the route now constructs `AtsReadinessCheckResponse` explicitly instead of relying on `from_attributes` auto-mapping.
2. **Critical, confirmed via grep:** no worker in `docker-compose.yml` consumed the `ats_check` queue — every job would sit `"queued"` forever. Same class of gap as the `maintenance` queue caught during the Celery-beat task. Fixed: added `worker_ats_check` service.
3. **Real edge case:** `ats_readiness_checks.cv_profile_version_id` was `NOT NULL`, but the worker sets it `None` whenever the CV hasn't finished parsing yet — a case the check logic was explicitly designed to tolerate (`structured_payload=None` handled gracefully in 2 of 6 checks), just not the schema. Fixed: column now nullable (model, migration `007`, and `05-openapi.yaml` all updated together).
4. **Gap:** the new `POST /cvs/{cvId}/ats-check` had no rate-limit tier, unlike every other job-creating endpoint since Task 2.4. Fixed: added `generation` tier (same bucket `POST /matches` uses — the other rules-based, non-LLM analysis endpoint).

**Still outstanding, same shape as the Sprint 2 gap:** migration `007`'s upgrade/downgrade round-trip and the full `POST → worker → GET` path haven't been run against a live Postgres yet — this review verified module-level correctness (compile, reproduction scripts, existing test suite) but not the full stack end-to-end.

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

### Sprint 3 — Tailored CV generation, the actual feature — ✅ COMPLETE and verified live (2026-08-11)

Goal: the sprint where the product starts doing what it's named for.

**Status:** built, wired, and verified against a live Postgres + Redis instance — see the "Tailored CV generation" section under Phase 3 above for the full write-up, including the evidence-reference infrastructure gap found and solved along the way (`match_evidence_items.source_references` was populated for only 1 of 5 support levels — generation re-derives bindings fresh from the CV's current rows instead of relying on it) and the two real bugs caught during test-writing (a number-regex boundary bug that would have missed a fabricated statistic; a false-positive bug that would have rejected well-grounded content). Migration `008` round-trips cleanly; 52 new tests pass against real Postgres, including a genuine end-to-end Celery→Redis publish.

- ~~Pin the LLM provider/model decision~~ — done, OpenAI API / `gpt-4o-mini`, see Open Decisions above.
- ~~Build the generation module~~ — done: `app/services/tailored_cv_generation.py`, evidence pool restricted to `supported`/`partially_supported` only, per the non-fabrication rule.
- ~~Schema-constrained/structured output~~ — done: OpenAI JSON Schema strict mode, no free-form generation anywhere.
- ~~Traceable evidence reference~~ — done, but via a different, more robust mechanism than originally planned: not a reuse of `match_evidence_items.source_references` (found to be unreliable — see above), but a fresh re-derivation directly from `CvExperienceItem`/`CvEducationItem`/`CvSkillItem` at generation time, independently content-verified after the fact.
- ~~Trial-session-accessible~~ — done: all 4 endpoints use `RequestIdentity`/`get_current_user_or_trial_session`, mirroring `matches.py`.
- ~~Full test coverage~~ — done: 52 new tests across 3 files, mapped directly to `09-test-plan.md` §6's checklist.

**Demo:** submit a real CV + job post as an anonymous trial session and get back an AI-generated tailored draft, every claim traceable to its evidence. **Not yet done**: this specific end-to-end walkthrough through the real running API with Celery workers and a real OpenAI key — this verification pass proved the DB/orchestration/evidence-verification layers against live infrastructure with a fake LLM client, not a real generated draft through the full deployed stack.

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
2. ~~Push local `main` to `origin`~~ — ✅ **done**: confirmed via `git fetch` that local `main` and `origin/main` are fully in sync (0 ahead, 0 behind).
3. ~~Start the LLM provider/model decision~~ — ✅ **pinned and confirmed** (2026-08-11): OpenAI API, cost-efficient tier (`gpt-4o-mini` class), Data Controls confirmed saved as disabled (no data shared with OpenAI) — see Open Decisions above. No outstanding action.
4. ~~Wire up a Celery beat scheduler~~ — ✅ **done, not yet live-verified** (2026-08-11): `beat_schedule` added to `app/workers/tasks.py`'s Celery config (hourly, via new `settings.trial_session_cleanup_interval_seconds`), a `beat` service added to `docker-compose.yml` to run the scheduler process, and a new `worker_maintenance` service added to actually consume the `maintenance` queue the task publishes to — previously no worker listened on that queue at all, so a beat schedule alone would have queued the task forever without anything executing it. Verified: `celery_app.conf.beat_schedule` loads correctly (checked directly via Python import) and `docker-compose.yml` parses as valid YAML with both new services present. **Not yet verified**: an actual `docker compose up` run confirming beat fires the task and `worker_maintenance` executes it end-to-end — that needs the full stack up, which this pass didn't bring up.
5. ~~Investigate the `cv_tailoring` dev database's stuck `alembic_version`~~ — ✅ **resolved** (2026-08-11): was a bookkeeping-only mismatch, not a partial migration — fixed via `alembic stamp 005`. See the "Anonymous trial support" verification block above for the full investigation.
6. ~~Sprint 3~~ — ✅ **done, verified live** (2026-08-11): tailored CV generation — see the Phase 3 section above for the full write-up. Not committed, not pushed (same as everything else this session — commits are the user's own call).
7. **Full end-to-end walkthrough through the real deployed stack** — `docker compose up` (api, all Celery workers including the new `worker_cv_generate`, Postgres, Redis) with a real `OPENAI_API_KEY`, actually generating a draft through the running API rather than a fake LLM client. This pass verified every layer up to the OpenAI call itself; the real call has never been made.
8. **Sprint 4 — real cover letter generation** — now unblocked, reuses Sprint 3's `llm_client.py`/evidence-verification infrastructure directly rather than a second pipeline, per the sprint plan below.
9. **Genuinely still open, not forgotten:** the Celery beat scheduler (item 4 above) has never been live-verified end-to-end; `schemas/cover_letter.py`'s field-alias bug (found while building Sprint 3, documented in the Phase 3 section above) is real and unfixed; education/certifications/projects sections in tailored CV drafts will stay empty until Phase 2 extraction is extended to populate `CvEducationItem` and add certification/project tables (a deliberate, accepted Sprint 3 scope decision, not an oversight).
