# 16 — Tailored-CV content-loss fix and flow unification

**Status:** Phase 1 complete (failing regression test committed to the tree,
not yet fixed). Phases 2-5 planned, awaiting decisions at the bottom.
**Opened:** 2026-08-28
**Trigger:** "the current flow produces a cv thats not usable" — with
`Example/` supplied as the reference for both quality and speed.

---

## 1. Problem statement

The tailored CV the product delivers is not a usable CV. Reproduced and
measured, not inferred: with realistic extraction output fed through the
real generation orchestrator, the generated draft contains
**`['skills']`** — a bare skills list. No work history, no education, no
summary.

The reference app (`Example/`) produces a strong, complete tailored CV in
roughly 35 seconds using **one** `gpt-5-mini` call
(`Example/artifacts/api-server/src/routes/resume.ts`): raw resume text +
raw job description in, JSON out containing score, summary,
matched/missing skills, and 3-5 achievement bullets **per role for every
role**.

## 2. Root cause (verified against code, not commit messages)

The Docling → Textract → merge → `cv_parse` pipeline was decommissioned
and replaced by a single LLM call
(`app/services/cv_analysis.py::analyze_cv`, run by
`worker_jobs.py::process_cv_analyze`).

That replacement extracts **only `basics` + `skills`**. The old
`cv_parse` step was the *only* writer of the four structured row types:

| Row type | Only remaining writer |
|---|---|
| `CvExperienceItem` | `decommissioned/extraction_v1/step6_cv_parse_task.py` + test fixtures |
| `CvEducationItem` | same |
| `CvCertificationItem` | same |
| `CvProjectItem` | same |

`_write_cv_profile_shim` (`worker_jobs.py:551`) is explicit that it is a
minimal FK-satisfying shim; its signature accepts only
`(session, cv_file, basics, skills)`.

Consequence: `process_cv_generate` loads those four row types by
`cv_profile_version_id`, gets four empty lists in production, and
`generate_draft_sections` has nothing to build experience/education/
project sections from. The same empty pool starves
`cover_letter_generation.py`.

### Why no test caught it

No test exercised extraction → generation as one chain.
`test_cv_analysis.py` stops at the analysis dataclass;
`test_tailored_cv_generation.py` hand-builds the very rows production
never creates; `test_e2e_match_v2.py` seeds profile rows directly via SQL
and stops at the match; `test_cv_analyze_and_match_live.py` asserts the
shim writes `basics`/`skills` and stops there.

## 3. The three delivery paths (all enumerated)

| # | Path | Frontend entry | Engine | LLM calls | Uses `tailored_cv_prompts.py`? | State |
|---|---|---|---|---|---|---|
| A | Fast rewrite | `/try/upload` | `resume_rewrite.py` (single streamed call) | 2 | No | Works, Example-like |
| B | Legacy draft | `/dashboard/matches/[matchId]` | `tailored_cv_generation.py` (per-section) | 2 + per-section, each with up to 2 verify retries | **Yes** | Broken |
| C | Trial results | `/try/results` | same as B | same as B | **Yes** | Broken |
| — | Cover letter | `[matchId]` page | `cover_letter_generation.py` | 1 | No (own prompts) | Starved evidence |

**Key irony:** anonymous trial users on `/try/upload` get the good, fast
path; registered users on the dashboard get the broken, slow one. That is
identity-arbitrary behaviour, not a product decision.

## 4. Orphaned v2 prompt file

`tailored_cv_prompts.py` exists at the **repository root** as an
unmerged v2 draft (adds `WRITING_STANDARDS` and `ANTI_AI_TELL_RULES`,
documents a 17x rise in AI-flagged term density in v1 output, banned
vocabulary, banned constructions, locale preservation).

The live module `backend/app/prompts/tailored_cv_prompts.py` is still
v1. Repo-wide grep: **nothing imports the root file**; no reference to
`WRITING_STANDARDS`/`ANTI_AI_TELL_RULES` anywhere in the codebase. Its
content is valuable and should be folded into the path that actually
ships CVs (`resume_rewrite_prompts.py`), not only into the legacy
generator.

---

## 5. Agreed plan

### Phase 1 — Failing regression test (DONE)

`backend/tests/test_cv_content_pipeline_regression.py`. Pure: fake LLM
client, no DB writes, no network. Asserts the contract the fix must
satisfy:

1. `analyze_cv` returns structured `experience` (roles, companies, bullets).
2. Quantified achievements (`43`, `20`, `50%`, `25%`) survive extraction.
3. `analyze_cv` returns `education` and `certifications`.
4. `basics`/`skills` keep working (regression guard on what already works).
5. End to end: extraction output, mapped to rows, must produce a draft
   containing experience **and** education sections.
6. Labelled static guard: `_write_cv_profile_shim` must accept the four
   structured row groups it has to persist.

**Result on the unfixed tree: 5 failed, 1 passed** — the pass is #4, the
guard for existing behaviour. Verbatim failure evidence:

```
AssertionError: The tailored CV has no experience section.
  Sections present: ['skills'].
AssertionError: lost the '43' figure in extraction
AssertionError: _write_cv_profile_shim cannot persist
  ['certifications', 'education', 'experience', 'projects']
  - it only accepts ['basics', 'cv_file', 'session', 'skills'].
```

### Phase 2 — Restore the CV's real content

Extend the existing single `cv_analyze` LLM call's JSON schema to also
extract `experience`, `education`, `certifications`, `projects` (the shape
the old parser produced), add the matching fields to `CvAnalysisResult`,
and extend `_write_cv_profile_shim` to persist the four row types.

Cost: no extra round-trip — the call already happens once per upload in
the background. Only output tokens grow (raise `max_tokens` from 1200);
expect +5-15s on that one background call, nothing on the user-facing
deliverable.

Fixes the legacy generator **and** the cover-letter evidence pool.

### Phase 3 — One flow, fast engine

Route the dashboard "Download tailored CV" and the trial "Download trial
CV" through the already-built fast path (`stream_rewrite_resume`, single
streamed call) instead of `createTailoredCv → approve → export`. Inputs
are already in the DB (`cv_raw_text.canonical_text`, `job_post.raw_text`,
plus the fast match-analysis stats). Retire `/try/results`; the per-section
draft engine is either demoted to an opt-in "detailed verified" mode or
retired once the fast path is proven.

### Phase 4 — Prompt and accuracy upgrades (zero added latency)

- Structural preservation in `resume_rewrite_prompts.py` (bump to v5):
  contact header verbatim, **every** role kept with
  `Title — Company — Dates`, 3-4 achievement bullets per role, numbers
  preserved and led with, education/certs never dropped, one-page guidance.
- Fold the orphaned v2 `WRITING_STANDARDS` + `ANTI_AI_TELL_RULES` (banned
  vocabulary, banned constructions, locale preservation, verb-first,
  impact-ordered) into that same prompt.
- Cover letter: add raw CV + JD text to `build_cover_letter_user_payload`,
  keeping the existing verification gate. Same single call, no added time.

### Phase 5 — Flow unification by account type (not a separate trial flow)

**Decision: keep the trial *identity*, delete the trial *flow*.**

What already exists and should stay: `trial_sessions` +
`X-Trial-Session-Id` + `RequestIdentity` /
`get_current_user_or_trial_session`, `POST /auth/claim-trial` reassigning
all trial rows into a new account in one transaction, 48h TTL, per-IP
abuse limits, cleanup worker, and `buildIdentityHeaders()` on the
frontend already auto-selecting Bearer vs trial header.

What is missing: an account-type seam. `accountStatus` is only
`active | suspended | deleted`; `rate_limit.py` states plainly that "No
paid/subscription tier exists in the schema yet (User has no plan/tier
column)".

Target model, which matches `Frontend/frontend-roadmap.md` §4.2 and
`Frontend/job-board-conversation-2.md` already:

| Identity / type | Entitled to |
|---|---|
| anonymous (trial session) | upload, analyse, rewrite, one download, then upsell |
| registered — free | same core + persistent history (dashboard) |
| registered — paid | + cover letters, exports, application tracker, company tracking |

Implementation: add a `tier`/`plan` column to `users`, expose
`account_type` on `RequestIdentity`, add a
`require_entitlement("cover_letter" | "export" | ...)` FastAPI dependency
used alongside the existing auth dependencies (**server-enforced**, never
frontend-hidden only). One route tree; gated buttons show the auth or
upgrade paywall per the roadmap. Keep `claim-trial` →
`/dashboard/continue` as the conversion path.

Why better than a separate flow: one engine to maintain and test, one
place for quality fixes to land, no "trial vs account produces different
quality" inconsistency, and paywall placement becomes declarative rather
than three bespoke pages.

---

## 6. Open decisions

1. Phase 2 **and** 3 (recommended), or Phase 3 only?
2. Fast-path download as **PDF** (current trial UX, Gotenberg) or **DOCX**
   (current dashboard export)?
3. Retire the legacy per-section draft engine, or keep it as a paid
   "detailed verified" mode?

## 7. Verified vs unverified

**Verified by reading code or running it:** the four row types have no
live writer; the shim's signature; `Sections present: ['skills']` from a
real orchestrator run; the three delivery paths and their entry points;
the root v2 prompt file being unimported; the absence of any tier column.

**Not verified:** end-to-end wall-clock time of the proposed Phase 3 path
against a real CV and job post (no live comparison run yet); whether
extending the `cv_analyze` schema degrades its scoring quality (needs a
live A/B on real CVs); the Example's 35s figure is taken from the earlier
`CV matching fix/` measurement, not re-measured in this session.

