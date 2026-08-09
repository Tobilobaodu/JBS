# Implementation Plan

AI CV Tailoring and Cover Letter Platform — Backend

## 1. Objective

Build the backend services that let a user upload a CV, submit a job post, receive a tailored CV draft, and complete a guided cover letter workflow — all using only verified user evidence, with every generated claim traceable back to its source. Frontend, visual design, and user journey are handled separately; this plan covers backend services, processing pipelines, data, and APIs only.

## 2. Recommended stack

| Layer | Choice | Why |
|---|---|---|
| API/backend language | Python + FastAPI | Single language across API and workers — see the rationale below, since this decision affects every downstream document in this pack |
| Validation / schemas | Pydantic | Native fit for FastAPI, and for the schema-first design this whole pack depends on (every AI output is schema-validated before it's trusted — see `02-architecture-overview.md` §6) |
| Database | PostgreSQL | Transactional integrity, clear relational structure, native JSON columns for model payloads |
| Database access | SQLAlchemy | Mature ORM with solid parameterized-query defaults — see `10-security-plan.md` §7 on why this matters for injection resistance |
| Migrations | Alembic | Standard SQLAlchemy-ecosystem migration tool |
| Object storage | S3-compatible | Original uploads, extracted artefacts, exports |
| Queue | Managed queue (e.g. SQS) or Celery, depending on how much workflow control the team needs beyond basic job dispatch | Backpressure, retries, decoupled worker scaling |
| Cache | Redis | Prompt context cache, rate limiting, short-lived workflow state |
| Document parsing (first pass) | Docling (self-hosted) | Strong structured extraction, no per-page vendor cost, data stays in our infrastructure for the first pass. Docling is itself a Python library — see the rationale below for why this is one of the stronger arguments for the language choice, not just a convenience |
| Document parsing (second pass) | Amazon Textract (managed), via boto3 | Mature, benchmarked completeness/OCR review — not a fallback, a standard second stage. boto3 is the most mature Textract SDK across languages |
| LLM provider | Any provider with native JSON-schema-constrained structured output | Non-negotiable requirement — see architecture doc Section 6 |

### Why Python, and why this isn't a close call dressed up as one

This pack originally recommended Node.js/TypeScript with an explicit "this is a preference, not a mandate" caveat. That caveat still holds in spirit, but the specific recommendation has changed to Python, for reasons that stand on their own rather than because of any single reference implementation:

- **Docling is a Python library with no first-class equivalent in other ecosystems.** Given the two-pass extraction design already committed to in `02-architecture-overview.md` §4, Docling runs somewhere in this stack regardless of what language the API is written in. If it's Python either way, the real choice is "Python everywhere" versus "Python for the Docling worker, something else for the API" — and the second option is a deliberate hybrid architecture (see the note at the end of this section), not a lighter-weight default.
- **The hard part of this system is document and AI processing, not high-throughput lightweight API serving.** Textract calls and LLM calls dominate end-to-end latency regardless of the API language — the traditional case for Node (fast, cheap concurrency for many simple requests) doesn't carry much weight when the actual bottleneck is a multi-second external call either way.
- **Pydantic fits the schema-first design this pack is built around.** The non-fabrication rule (`02-architecture-overview.md` §1, §6) depends on every AI response being schema-validated before it's trusted. Pydantic plus FastAPI's native OpenAPI generation is a tight loop for exactly that pattern — comparable to what Zod gives a TypeScript stack, but with less glue code given Python's role in the extraction layer either way.
- **One language across API and workers** avoids the operational overhead of two deployment pipelines, two dependency systems, and a queue payload contract that has to stay in sync across languages — a real cost, not a stylistic preference, once Phase 2 onward has several worker types running concurrently with the API (see `07-first-sprint-tasks.md` and the worker list in `08-deployment-guide.md` §6).

What's deliberately **not** part of this reasoning: matching the language of any specific reference codebase someone happened to study while designing this system. That's a fine reason to make *reading* a reference implementation faster, but it says nothing about what's right for a multi-phase production backend, and shouldn't be confused with the points above.

**This still isn't an unconditional mandate.** Node.js/TypeScript remains a defensible choice if the team is strongly TypeScript-based already, tight type-sharing with a TypeScript frontend is a real priority, or the team plans to keep Docling entirely inside an isolated Python worker behind a queue (the hybrid architecture) while the API and every other worker stay in TypeScript. That hybrid is technically sound — it just adds two deployment environments, two dependency systems, two logging/testing setups, and a cross-language queue contract to maintain, which is a real and recurring cost, not a one-time setup cost. Make this call based on team composition, which this pack has no visibility into — the constraints that actually matter regardless of language choice are: schema-validated AI outputs, async job orchestration via a queue, PostgreSQL-or-equivalent relational storage with immutable versioning, and the two-pass extraction design.

## 3. Delivery phases

Each phase should end with something demonstrable, not just code merged. Suggested duration is indicative — adjust based on team size and actual velocity once Phase 1 is underway.

### Phase 1 — Foundations (~3–4 weeks)

**Goal:** a user can upload a CV and see it move through the extraction pipeline with observable status.

- Backend infrastructure setup: API service skeleton, authentication (register/login/session), database, object storage, queue.
- Document ingestion service: file validation (type, size), storage, processing job creation.
- Docling worker: first-pass extraction.
- Textract worker: second-pass completeness review.
- Merge layer: canonical extraction result with structural validation checks.
- Baseline observability: logs, basic metrics, job status visibility.

**Demonstrable outcome:** upload a CV via API, poll job status, retrieve canonical extracted text.

### Phase 2 — Structured parsing and job post ingestion (~3–4 weeks)

**Goal:** both CV and job post exist as structured, queryable, versioned data.

- CV parser/normaliser: build the structured candidate profile from canonical extraction (with confidence flags, immutable versioning).
- Job post ingestion: URL fetch path + pasted text path, both feeding the same structuring logic.
- Job post structuring: required vs. preferred criteria, keywords.
- Persist structured outputs per the data model.

**Demonstrable outcome:** retrieve a structured candidate profile for an uploaded CV, and a structured job requirement profile for a submitted job post (URL or pasted).

### Phase 3 — Matching and tailored CV drafting (~4–5 weeks)

**Goal:** the system can tell you what's supported, what's not, and produce an evidence-bound tailored CV.

- Matching engine: evidence-based comparison, `match_evidence_items` generation, unsupported-requirement flagging.
- Tailored CV generation: schema-constrained rewrite using only matched, verified evidence.
- Draft versioning: multiple draft versions, regeneration support.
- Evidence reference enforcement: validation layer that rejects any generated section without evidence references.
- ATS structural-readability check (product extension #1, see `11-product-extensions.md` §1): a rules-based composite score, deliberately not an LLM generation call, run against the canonical extraction result. Has no dependency on job post data, so it can be built in parallel with the matching engine rather than after it.
- Fix-it checklist (product extension #3, see `11-product-extensions.md` §3): synthesised from `match_evidence_items` at the same time as tailored CV generation, using template-based suggestion text — not a new generation call, and not exempt from the evidence-binding discipline just because it isn't part of the CV itself.

**Demonstrable outcome:** submit a CV + job post pair, get back a match analysis, generate a tailored CV draft with its improvement checklist, run an ATS readiness check, confirm every generated section traces to source evidence.

### Phase 4 — Guided cover letter workflow (~4 weeks)

**Goal:** the interactive question-and-answer engine produces a letter grounded in real user input.

- Question generation engine: derives questions from CV/job-post gaps.
- Answer capture and multi-round support.
- Cover letter drafting from CV evidence + user answers, same non-fabrication controls as CV generation.
- Regeneration on new answers.

**Demonstrable outcome:** start a workflow, answer a question set, get a draft letter, submit a follow-up answer, see the draft regenerate incorporating it.

### Phase 5 — Hardening and release readiness (~3–4 weeks)

**Goal:** production-ready, not just feature-complete.

- Export preparation services (CV export, cover letter export, combined application pack) — confirm the export format decision (see §7) before building beyond the identifier-return stub.
- Multi-job-post coverage reporting (product extension #2, see `11-product-extensions.md` §2) — an aggregation over existing `match_runs`, no new generation surface. Placed here as a default slot since it depends only on Phase 3's matching engine and has no dependency on Phase 4; a team with spare capacity earlier could pull it forward without disrupting sequencing, since nothing else depends on it being done at any specific time.
- Security hardening pass against `06-non-functional-requirements.md`.
- Audit logging completeness check.
- Performance tuning, particularly around the token-efficient rewrite architecture and prompt caching.
- Error handling review across all async paths — confirm nothing fails silently.
- Load/soak testing on the queue and worker layer.
- Full pass through `09-test-plan.md` — treat its exit criteria as the actual Phase 5 sign-off gate, not just this list.

**Demonstrable outcome:** end-to-end run from upload to exported application pack, under realistic load, with a clean audit trail.

Total indicative timeline: **~17–21 weeks** for a single backend developer working through phases sequentially. This compresses meaningfully with a second developer picking up parallel-izable work (e.g. one on extraction/parsing, one on matching/generation) from Phase 2 onward — Phases 1 and 2 have a natural split along the ingestion vs. structuring boundary.

## 4. Suggested team shape

- **Minimum viable:** one backend developer comfortable with async/queue-based systems, comfortable integrating LLM APIs with structured outputs. This is achievable solo but Phase 3 (matching + generation) is the highest-complexity phase and benefits from a second pair of eyes on the evidence-binding logic specifically, given how central it is to the product's core promise.
- **Recommended:** two backend developers from Phase 2 onward, split along ingestion/parsing vs. matching/generation/cover-letter, converging for Phase 5 hardening.
- Security/compliance review (even informal, even one person for a day) before Phase 5 sign-off — the compliance section in `06-non-functional-requirements.md` is written to be checkable, not just aspirational.

## 5. Sequencing dependencies a developer should know upfront

- **Docling + Textract merge logic is a Phase 1 blocker for everything downstream.** Don't start CV parsing (Phase 2) against unmerged or unvalidated extraction output — the structural validation step exists specifically to stop garbage propagating into the structured profile.
- **Canonical profile versioning must be right before Phase 3.** Match runs and generation both key off a specific `cv_profile_versions.id`. Retrofitting immutable versioning after matching logic already assumes mutable profiles is expensive — build it correctly the first time. Specifically: child rows (`cv_experience_items`, `cv_education_items`, `cv_skill_items`) must key off `cv_profile_version_id`, not `cv_file_id` — see `03-data-model.md` §4 rule 2 for why this matters once a CV gets reprocessed after a match already exists.
- **Evidence reference enforcement should be built as a validation gate, not a UI convention.** If it's optional at the schema level, it will get skipped under time pressure during Phase 3 or 4. Make the database/schema layer reject ungrounded content — and reject an *empty* evidence array specifically, since `evidence_references: []` is a valid JSON array that will otherwise pass a naive "field is present" check.
- **`processing_jobs` is the single source of truth for async status, from Phase 1 onward.** It's tempting, once a domain table like `cv_files.status` or `cv_profiles.current_version_id` exists, to let the frontend infer job progress by polling that table instead — don't. `03-data-model.md` §4 rule 6 already establishes this; the sequencing risk is that it's easy to violate quietly during Phase 2–4 as more domain tables with their own status-like fields appear (`job_posts.status`, `match_runs.status`, `tailored_cv_drafts.status`). Every one of those is a *result* status, not a *processing* status — the frontend polls `processing_jobs` to know if work is still happening, and the domain table to know the outcome once it's done. Conflating the two is the kind of shortcut that works fine until two jobs touch the same entity concurrently and the domain-table status becomes ambiguous about which job it reflects.
- **Export services (Phase 5) depend on approval state, not draft existence.** Don't build export against "latest draft" — build it against "latest draft where `status = approved`", enforced server-side.
- **`cv_extraction_passes` has a unique constraint on `(cv_file_id, pass_type)`.** Decide how `reprocess` behaves against it (archive-and-replace vs. an `attempt_number` column) during Phase 1, before the reprocess endpoint ships — see `03-data-model.md` §3.
- **Malware scanning and worker sandboxing are Phase 1 requirements, not Phase 5 hardening.** It's tempting to treat security as a pre-launch pass, but `POST /cvs` accepts arbitrary files from day one — see `10-security-plan.md` §2 for why this specific control can't wait, and `07-first-sprint-tasks.md` Sprint 2 for the concrete task.
- **SSRF protections on job post URL fetch must be designed before Phase 2 fetch logic is written**, not added afterward. Once a "just fetch the URL" implementation exists and works for the happy path, retrofitting IP/redirect validation and network isolation is a bigger, riskier change than building it in from the first line of that worker. See `10-security-plan.md` §4.
- **The non-fabrication rule is a correctness requirement throughout every phase, not a Phase 3 feature or a quality nice-to-have.** It's stated as the system's defining constraint in `02-architecture-overview.md` §1, but the sequencing risk is specific: under time pressure in any phase — a demo deadline, a "just ship it and fix evidence-binding later" moment, a convenient shortcut in the matching or generation logic — this is the requirement most likely to get quietly traded off, precisely because a plausible-looking draft with weak evidence binding still *looks* like it's working. If a design decision anywhere in the implementation trades this off for convenience or speed, raise it explicitly rather than working around it — don't let it be discovered later as a gap between what the product promises and what it actually verifies.

## 6. Open decisions

A few things the source material left unresolved. None block starting Phase 1, but confirm them before the phase noted:

| Decision | Needed by | Notes |
|---|---|---|
| LLM provider and model | Phase 3 (generation work) | Any provider with native JSON-schema-constrained structured output satisfies the architecture requirement. Pin the specific choice early — it affects the cost estimate in `02-architecture-overview.md` §10 and the schema-validation library that fits best. |
| Export file formats and templates | Phase 5 | Not specified in the original scope. `08-deployment-guide.md` and the OpenAPI spec use `pdf`/`docx` as placeholders. |
| Cost alert thresholds | Phase 5 (monitoring setup) | `08-deployment-guide.md` §9 uses round placeholder numbers. Recalculate from real Phase 1–2 usage against the per-run cost estimate in `02-architecture-overview.md` §10. |
| Endpoint-tier rate limit values | Phase 1 (upload/auth), Phase 3 (generation) | `08-deployment-guide.md` §5 introduces tiered rate limits per `10-security-plan.md` §6 with illustrative numbers. The tiering structure is the requirement; the specific thresholds need tuning against real traffic. |
| Malware scanner selection | Phase 1, Sprint 2 | `10-security-plan.md` §2 requires this control but doesn't mandate a specific product (ClamAV is used as an example). Pick one that fits the deployment environment before Sprint 2 closes. |

## 7. What's in this pack

| File | Contents |
|---|---|
| `01-implementation-plan.md` | This document |
| `02-architecture-overview.md` | System architecture, extraction strategy, non-fabrication controls, cost estimate |
| `03-data-model.md` | Full entity list, column-level schema, relationships, JSON schemas, modelling rules |
| `04-api-reference.md` | Human-readable endpoint index, shared request/error format, design rules |
| `05-openapi.yaml` | Machine-readable OpenAPI 3.0 spec (validated) — request/response schemas and examples for every endpoint |
| `06-non-functional-requirements.md` | Security, compliance, reliability, performance requirements (baseline) |
| `07-first-sprint-tasks.md` | Ticket-sized tasks to start Phase 1 immediately |
| `08-deployment-guide.md` | Environments, config, worker settings, monitoring, rollback, deployment checklist |
| `09-test-plan.md` | Test areas and exit criteria, including the non-fabrication-specific test cases |
| `10-security-plan.md` | Attack-surface-by-attack-surface controls, adversarial test cases, exploitation scenarios, incident response |
| `11-product-extensions.md` | Six ideas for differentiating the product beyond the core spec — three designed for building now, two schema-only extensions for later features, one flagged for a separate scoping decision |
| `12-project-status-and-roadmap.md` | Canonical, code-verified status of what's actually built — check this before trusting any progress report, including this plan's own phase-completion claims once implementation starts |
| `13-frontend-plan.md` | Developer-built test harness, phase by phase, and the plan for handing off to a designer |

Start with this file and `02-architecture-overview.md` for context, then check `12-project-status-and-roadmap.md` for where things actually stand before assuming this document's phase descriptions reflect current progress, then go straight to `07-first-sprint-tasks.md` to begin work. Reference `03-data-model.md` and `05-openapi.yaml` while implementing, `08-deployment-guide.md` when setting up environments, `09-test-plan.md` when writing tests for each phase rather than waiting until Phase 5, `10-security-plan.md` alongside every phase that touches an attacker-reachable surface (which, in this system, is most of them) — it's written to extend, not duplicate, `06-non-functional-requirements.md` §4 — `11-product-extensions.md` when Phase 3 reaches the ATS-check and checklist tasks, or when deciding whether to prioritise the coverage-reporting work in Phase 5, and `13-frontend-plan.md` alongside each phase's backend work so there's always a working, clickable way to demo progress.
