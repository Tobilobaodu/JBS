# Incident-Response Runbook

Sprint 6 / Workstream I. Operational playbook for the four incident scenarios
security-plan §12 requires at minimum, written against **this system's actual
tables, endpoints, and tools** — not generic security advice. Exercised in a
tabletop (§5).

The runbook's job is to make the data model answer "what data, which users,
since when" fast. It does **not** make the user-notification decision — that is
explicitly a legal/business call (§12), not an engineering one.

---

## 1. Roles (named, not people — team structure not final)

| Role | Authority |
|---|---|
| **Incident lead** | Coordinates; owns the timeline; calls whether to revoke broadly. |
| **On-call engineer** | First responder; runs §2 triage; executes revocations in §3. |
| **Comms owner** | Communicates with affected users. |
| **Notification decider** | Legal/business role; makes the notify-or-not decision. |

Nobody acts alone on notification — the decider owns that call; the rest of
the team owns containment and evidence preservation.

---

## 2. First steps for every scenario (do these first, in order)

1. **Record** start time and everything you run (a real incident needs a
   blameless timeline, not a reconstructed one).
2. **Check the alerting counters** (Prometheus `/metrics`, or the `*_total`
   series): `auth_failures_total`, `authz_denied_total`,
   `ssrf_rejected_total`, `generation_schema_validation_failed_total`. An
   anomaly here tells you *which* pattern fired before you read raw logs.
3. **Check Alertmanager** (`/api/v2/alerts` or the UI) for which rule fired
   and when — this is the automated tripwire; check it before log-grepping.
4. **Pull the audit trail** — two ways, in order:
   - `GET /api/v1/audit/{entityType}/{entityId}` (real endpoint, Sprint 6
     Workstream F) for a specific entity's trail.
   - Direct `audit_events` query for cross-entity correlation:
     ```sql
     SELECT created_at, user_id, entity_type, entity_id, event_type, actor_type, metadata, ip_address
     FROM audit_events
     WHERE user_id = :user_id OR entity_id = :entity_id
     ORDER BY created_at DESC;
     ```
   `audit_events` is append-only and DB-immutable (trigger
   `audit_events_no_update` rejects UPDATE/DELETE — migration `012`), so it is
   trustworthy forensic evidence; back it up before touching anything else.
5. **Do not delete, restart, or "clean up" anything** until evidence is
   captured. Contain first, preserve second.

---

## 3. How to revoke access (already built this session)

- **Revoke a single session**: `POST /auth/logout` revokes all refresh tokens
  for the current user; the session-backing check in `get_current_user`
  (`user_sessions.revoked_at` / `expires_at`) means a revoked session stops
  working immediately — the bearer token is rejected even before its own JWT
  `exp` (security-plan §1).
- **Revoke all sessions for a user** (credential-compromise case): set
  `revoked_at = now()` on every `user_sessions` row for that `user_id`, then
  force a password change.
- **Suspend the account**: set `users.status = 'suspended'` — `get_current_user`
  already rejects non-`active` accounts with 401.

Only the **incident lead** and **on-call engineer** execute revocations; the
**notification decider** owns whether users are told.

---

## 4. The four scenarios

### 4.1 Document/data exposure (e.g. S3 bucket, export, log leak)

1. Confirm scope: which `storage_key`/`export` rows are affected. The upload
   path (`app/core/storage.py`) never uses client filenames in keys
   (`generate_storage_key` is uuid-based), so trace from `audit_events`
   `event_type IN ('upload','export_generated')` → `entity_id`.
2. Identify *which users*: join `cv_files`/`exports` back to `user_id`.
3. Determine *since when*: `audit_events.created_at` and the object's
   creation time.
4. If the leak is via a credential (see §4.3), rotate it and scope it down; if
   via a mis-scoped IAM role, cut the role to the documented minimum
   (`06-non-functional-requirements.md` §4).

### 4.2 Cross-user data access realized (an actual IDOR exploit, not probing)

1. The IDOR-probing alert (`authz_denied_total` rate) tells you the *pattern*;
   a realized exploit is one specific account reading another's data.
2. Pull `audit_events` for the suspect `user_id`; cross-reference each
   `entity_id` against its owner table (`cv_files`, `job_posts`, `match_runs`,
   `tailored_cv_drafts`, `cover_letter_workflows`, `exports`).
3. Confirm scope: every `entity_id` the suspect accessed, and whether it was a
   read (GET) or a mutation (DELETE/POST). Ownership checks return consistent
   404s (`identity_owner_filter` / `ownership_denied`), so a realized exploit
   means either a route missing the check or a leaked token.
4. If a route bug: fix the route to use `identity_owner_filter` /
   `ownership_denied` (canonical pattern — `matches.py` / `security.py`)
   before anything else ships.
5. Revoke the suspect's sessions (§3). Notification → **decider**.

### 4.3 Credential compromise

1. Triggers: `auth_failures_total{reason=...}` spike (stuffing), or a user
   reporting unexpected activity.
2. Revoke **all** sessions for the affected `user_id` (§3) — containment before
   forensics.
3. Force a password change; check `audit_events` `event_type IN
   ('login','login_failed','register')` for the account to bound the window.
4. Check `users.last_active` and session `ip_address` for anomalous origins.
5. If the credential was a *service* secret (not a user password): treat it as
   a leaked-credential event per §9 — **rotate, don't just delete the commit**
   — and scope the replacement to least privilege.

### 4.4 Unauthorized admin access

1. This system has **no admin role** in the JWT (`create_access_token` embeds
   only `user_id` + expiry, §1). "Admin access" therefore means a credential
   with broader-than-intended scope (DB/S3/IAM), not an app role.
2. Identify the credential from `audit_events` `actor_type` / `metadata`; if an
   app credential, revoke/rotate (§4.3); if DB/S3/IAM, rotate and re-scope to
   the documented minimum.
3. Confirm scope: which `entity_id`s / buckets the credential reached, via
   `audit_events` and object-storage access logs.

---

## 5. Tabletop exercise (run and documented)

**Ran:** 2026-08-13 — two scenarios walked live against the real running
Docker stack (not a mock/staging copy): IDOR-realized (§4.2) and credential
compromise (§4.3). Two throwaway accounts were created
(`tabletop-owner-*`/`tabletop-attacker-*@test.example`), the owner created a
real job post, and every step below is a real HTTP call against the live API,
not a walkthrough on paper.

**IDOR-realized (§4.2), step by step:**
1. Attacker requested the owner's job post directly:
   `GET /job-posts/{jobPostId}` with the attacker's own valid token →
   correctly denied, `404 {"detail":"Job post not found"}` — no 403/500, no
   information leak about the resource existing.
2. Checked the alerting counter (§2 step 2): `authz_denied_total` on
   `/metrics` incremented to `1` immediately — the signal that "an IDOR
   probe/denial just happened somewhere" reached Prometheus correctly.
3. Pulled the audit trail for the attacker's `user_id` (§2 step 4) —
   **came back empty of the denied attempt itself.** Only `login`/`register`
   events existed; the actual `GET /job-posts/{jobPostId}` denial left no
   `audit_events` row at all.
4. Tested `GET /api/v1/audit/job_post/{jobPostId}` (the real endpoint,
   Workstream F) as the owner: correctly returned the post's `upload` event.
   As the attacker: correctly returned `[]` (200, not 404 — doesn't leak
   existence), matching `test_audit_cross_user_returns_empty`.

**What worked:** the ownership-denial mechanism itself (consistent 404s,
§10's `authz_denied_total` firing on every real denial — this is also what
the Sprint 6 wiring-gap fix and its 28-route breadth test exist to guarantee),
session revocation (below), and the audit endpoint's own IDOR protection.

**What was unclear / changed as a result — the real gap this tabletop found:**
`audit_events` only records mutations (creation/register/login/etc.), never
read attempts — successful or denied. §2 step 4 and §4.2 step 2 both imply
`audit_events` is where you go to answer "which specific entity_ids did the
suspect account access" for an IDOR investigation, but for a pure-probing
(read-only) attempt — which is what IDOR probing usually *is* — that query
comes back **empty**. The only signal that a probe happened at all is the
aggregate `authz_denied_total` counter, which has no per-entity detail: it
tells you *an* attempt happened, not *which* resource, *when* (beyond the
metric's own timestamp), or by *which* account beyond whichever token made
the request. Correlating "which entity_id" currently requires falling back to
raw uvicorn access logs / SQL echo output (confirmed both contain the
`jobPostId` and the requester's `user_id` in this test) — which is incidental,
not designed for this, and SQL echo logging in particular is commonly
disabled in production. **Runbook §2/§4.2 have been left as-is for now**
(the correct fix — auditing denied-access attempts, not just mutations — is
a real product change, not a runbook wording fix, and is flagged here rather
than done silently mid-tabletop-writeup); treat this as the concrete
follow-up item the next engineering pass on this runbook should close.

**Credential compromise (§4.3) / session revocation (§3), step by step:**
1. Owner's valid token: `GET /job-posts/{jobPostId}` → `200`.
2. `POST /auth/logout` with that token → `204`.
3. Same token, same request, immediately after → `401
   {"detail":"Session has been revoked or is invalid"}` — confirmed the
   session-backing check rejects it even though the JWT's own `exp` hadn't
   passed, exactly as §1/§3 document. This worked with zero surprises.

Per §12: an untested runbook reliably has gaps exactly where it's needed most
— this one found a real gap on the first real run. Re-run this tabletop again
at least annually, and after any real incident however small, and after the
`audit_events`-for-reads gap above is addressed.

