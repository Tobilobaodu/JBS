# Sprint 6 — Full Hardening Pass Sign-off

Sprint 6 closes the gap between "Sprints 1-5 shipped and live-verified" and
security-plan `10-security-plan.md` §14's definition of "hardened". This is the
durable record §14 requires: pass/fail per §1-9 "how to test" item, **with the
specific test that proves each** — not "looks fine".

Baseline / final suite numbers (host venv, `--ignore=tests/test_regression_full_chain.py`):
- **Baseline:** 449 passed, 1 failed (pre-existing), 1 skipped.
- **Final:** **552 passed, 0 failed, 1 skipped.**

Two corrections to this document's own earlier draft, found by cross-checking
the finished work against the actual code rather than taking the summary at
face value — both are now fixed, not just noted:

1. An earlier version of this doc reported `test_confidence_and_merge.py::test_garbled_low_density_scores_low`
   as "pre-existing, unrelated, left untouched." That was stale — the failure
   was real (not a bad test mock) and has since been fixed: `_compute_confidence`
   in `docling_parser.py` let `text_density_score` (`chars / item_count`) cancel
   out the density penalty for a document with very few items, because dividing
   the same character count by a smaller item count inflates the average — the
   exact "proxy heuristic passing type/range checks while measuring the wrong
   thing" failure mode `09-test-plan.md` §2 names as having shipped once before.
   Fixed by scaling `text_density_score` by `density_score` so a document can't
   launder "pathologically few items" into "each item looks dense." See "Real
   bugs found" below.
2. §10's monitoring row was marked done on the strength of one passing test
   (`test_authz_denied_counter_increments_on_cross_user_access`) that only
   exercised 1 of ~28 real IDOR-denial routes. A cross-check found
   `authz_denied_total` was only wired at 3 of those routes — see "Real bugs
   found" below for the fix, and the new breadth test that now proves all 28.

---

## §1-9 "how to test" — pass/fail and proof

| Plan § | Control | Result | Proof |
|---|---|---|---|
| §1 | Auth/session (bcrypt, min-12, JWT alg/expiry, session revocation, enumeration timing) | ✅ | `test_auth_endpoints.py`, `test_tiered_rate_limits.py`, `test_rate_limit_identity.py` |
| §2 | File upload (magic-byte spoofing, size, path-traversal, collision, EICAR malware, extraction timeout) | ✅ | `test_file_upload_security.py` (new — 13 cases; EICAR is a live ClamAV test) |
| §3 | IDOR (cross-user denial on every ID-scoped route) | ✅ | `test_idor_matrix.py` (new — 28 routes, all 404) |
| §4 | SSRF (scheme/IP/redirect/DNS-rebinding) | ✅ | `test_ssrf_fetch.py` (existing) |
| §5 | Prompt injection (CV-side + job-post-side; evidence verification rejects) | ✅ | `test_prompt_injection.py` (new), `test_evidence_binder.py`, `test_tailored_cv_generation.py` |
| §6 | Rate limits + circuit breaker (fail-fast on degraded Textract/LLM) | ✅ | `test_tiered_rate_limits.py`, `test_job_concurrency_limit.py`, `test_circuit_breaker.py` (new — state machine + LLM wiring) |
| §7 | SQLi (payloads in free-text + filter params) | ✅ | `test_sql_xss.py` (new) |
| §8 | XSS (payloads round-trip as inert JSON; nosniff/CSP headers) | ✅ | `test_sql_xss.py` (new), `test_auth_endpoints.py::test_security_headers_present_on_every_response` |
| §9 | Secrets (CI secret scanning) | ✅ | `.github/workflows/backend-ci.yml` gitleaks job |
| §10 | Monitoring/alerting (5 attack-pattern counters + rules fire) | ✅ (config + counter tests, full breadth verified) | `test_metrics_counters.py` (new), `test_idor_matrix.py::test_cross_user_denied_increments_authz_counter` (new — all 28 IDOR routes, not just 1), `prometheus/alert_rules.yml`, `prometheus/alertmanager.yml` |
| §11 | Supply chain (dependency scan in CI) | ✅ | `.github/workflows/backend-ci.yml` pip-audit job |

### Real bugs found (and fixed) this sprint
- `docling_parser.py` swallowed the Docling-convert `TimeoutError` into a
  generic `ValueError`, destroying the §2 "fail fast on hung parse" signal.
  Fixed to propagate `TimeoutError`; verified by
  `test_docling_conversion_timeout_kills_hung_parse`.
- `docling_parser.py::_compute_confidence` had a genuine scoring bug (not a
  stale test, as an earlier draft of this doc incorrectly concluded): a
  document with very few structural items could inflate `text_density_score`
  (`chars / item_count`) high enough to cancel out the item-density penalty
  that's supposed to flag it as low-confidence. Fixed by scaling
  `text_density_score` by `density_score`, so per-item averages only count
  as a quality signal when there are enough items to trust the average.
  Verified: all `TestComputeConfidence` cases pass with real margin, full
  suite green.
- **`authz_denied_total` was only wired at 3 of ~28 real IDOR-denial routes**
  (`get_cv`, `get_match`, `get_questions` — via the shared `ownership_denied()`
  helper), despite the §10 IDOR-probing alert rule implying full coverage.
  Every other route (`delete_cv`, `reprocess_cv`, every export endpoint, every
  job-post endpoint, most of cover-letters, coverage reports, etc.) raised
  `HTTPException(404, ...)` directly, bypassing the counter entirely — an
  actual IDOR-probing attacker hitting those ~25 routes would have generated
  zero signal on the alert this sprint was supposed to have built. Fixed by
  routing every genuine ownership-denial 404 across `cvs.py`, `job_posts.py`,
  `jobs.py`, `matches.py`, `tailored_cvs.py`, `cover_letters.py`, `coverage.py`,
  and `exports.py` through `ownership_denied()` (29 call sites; business-state
  404s like "no draft yet" or "raw text not available yet" were deliberately
  left alone — they're not ownership denials). A new parametrized test,
  `test_idor_matrix.py::test_cross_user_denied_increments_authz_counter`,
  reuses the same 28-route matrix as the 404 test to prove the counter now
  fires from every one of them, not just a sample — the original
  `test_metrics_counters.py` test only covered 1 route, which is exactly how
  this gap went unnoticed.

## §13 — the 5 gaps, resolved

1. Malware scanning on upload — was already implemented; now **tested** (EICAR).
2. SSRF protection — was already implemented; was already tested (`test_ssrf_fetch.py`).
3. Evidence-reference content verification — was already implemented
   (`verify_claim_against_evidence`); now additionally proven against the
   injection framing (`test_prompt_injection.py`).
4. Security tests not in `09-test-plan.md` — closed by this sprint's test files,
   which are the security-plan test cases run as normal CI tests.
5. Rate-limit granularity — tiered limits already existed (`test_tiered_rate_limits.py`).

## §14 — the bar, item-by-item

- **§§1-9 how-to-test run + recorded durably** — ✅ this document (table above).
- **§13 gaps resolved or explicitly accepted** — ✅ (all five resolved, above).
- **At least one incident-response tabletop run** — ⚠️ **PARTIALLY DONE, corrected.**
  An earlier draft of this doc marked this ✅ on the strength of the runbook
  document existing. Re-checked directly against the runbook file itself:
  `14-incident-response-runbook.md` is written well and references this
  codebase's real tables/endpoints/functions (not generic advice) — that part
  holds up. But its §5 "Tabletop exercise" section is an **unfilled template**
  (`**Ran:** (date)`, `[fill in from the actual exercise...]`), not a record of
  an exercise that happened. §14's actual bar is "at least one tabletop *run*,"
  not "a runbook with a tabletop section" — so this is still open. The runbook
  is ready to be exercised; scheduling and running it (at minimum the
  IDOR-realized and credential-compromise scenarios) is the remaining step.
- **Dependency and secret scanning are active CI gates** — ✅ Workstream A:
  `.github/workflows/backend-ci.yml` (pip-audit + gitleaks) and
  `.github/workflows/frontend-ci.yml` (`npm audit --audit-level=high`).
  Note: these run in GitHub Actions and could not be *executed* from this local
  environment — the throwaway-branch "deliberately commit a vulnerable pin /
  fake secret and watch CI fail" acceptance test must be run once the workflows
  are pushed to a remote with Actions enabled.
- **Third-party security review / pen test** — ❌ **OPEN, not done.** This needs
  an external vendor, not an engineer. Flag to whoever owns the
  budget/vendor relationship. This sprint's output (a small, documented,
  already-self-tested attack surface + this sign-off doc) makes that review
  efficient — it is not a substitute for it.

## One loose end, flagged (not silently dropped)

Alertmanager delivery routing is a log-only stub (`prometheus/alertmanager.yml`).
There is no real Slack/email/PagerDuty channel configured — that's a separate
on-call-tooling decision that shouldn't block this sprint. The alerts fire and
are queryable at `/api/v2/alerts`; routing to a real channel is the one
follow-up.

## Files touched (all unstaged; no commit/push performed)

- New code: `app/core/circuit_breaker.py`, `app/api/v1/audit.py`, `app/schemas/audit.py`.
- Modified: `auth.py`, `cvs.py`, `cover_letters.py`, `matches.py`, `main.py`,
  `core/metrics.py`, `core/security.py`, `extraction/docling_parser.py`
  (TimeoutError propagation + the `_compute_confidence` text-density fix),
  `services/generation_core.py`, `services/llm_client.py`,
  `services/ssrf_safe_fetch.py`, `workers/worker_jobs.py`, `docker-compose.yml`,
  `prometheus/prometheus.yml`. Plus, for the `authz_denied_total` wiring fix:
  `api/v1/job_posts.py`, `api/v1/jobs.py`, `api/v1/tailored_cvs.py`,
  `api/v1/coverage.py`, `api/v1/exports.py` (newly routing their ownership-denial
  404s through `ownership_denied()`; `cvs.py`/`cover_letters.py`/`matches.py`
  above got the same treatment for their remaining unwired call sites).
- New tests: `test_file_upload_security.py`, `test_idor_matrix.py`,
  `test_audit_endpoint.py`, `test_circuit_breaker.py`, `test_prompt_injection.py`,
  `test_sql_xss.py`, `test_metrics_counters.py`.
- New config: `prometheus/alert_rules.yml`, `prometheus/alertmanager.yml`,
  `.github/workflows/backend-ci.yml`, `.github/workflows/frontend-ci.yml`.
- New docs/scripts: `14-incident-response-runbook.md`, `15-sprint6-signoff.md`
  (this file), `backend/scripts/load_test.py`.

## Definition of done — status

- [x] Every workstream's new tests pass against the real Docker stack
      (Workstreams B, C, D, E, G, H tests all green in the full suite).
- [x] Full regression suite fully green, no exceptions
      (552 passed / 0 failed / 1 skipped — the confidence-score bug this doc
      previously carried as "pre-existing, unrelated" is fixed, not excused).
- [ ] CI blocks on deliberately-introduced vuln + fake secret — **not yet run**
      (requires pushing the workflows to a remote with Actions; flagged above).
- [ ] All 5 alerting patterns fire **live** in Alertmanager — **config + counter
      tests done; live-fire requires the full Prometheus/Alertmanager stack**
      (the counters are proven to increment; firing the rules is the remaining
      live-fire step).
- [ ] Load test produces a recorded, reviewed result — `scripts/load_test.py`
      written but **not yet executed** (a full soak against the real stack takes
      many minutes and needs the alerting stack up to verify the queue-depth rule).
- [ ] Tabletop produces documented notes — **corrected from a previous ✅**:
      runbook §5 is an unfilled template, not documented notes from a run
      exercise. Runbook content itself is solid and ready; the exercise still
      needs to actually happen.
- [x] Sign-off doc written, external-review gap explicitly open.

