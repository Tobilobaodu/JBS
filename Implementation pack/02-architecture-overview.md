# Architecture Overview

AI CV Tailoring and Cover Letter Platform — Backend

## 1. What this system does

Users upload a CV, submit a job post (URL or pasted text), and receive:

1. A tailored CV draft aligned to the job post.
2. A cover letter, produced through a guided question and answer workflow.

The single hard rule that shapes every design decision below: **the system must never invent experience, employers, figures, dates or skills.** Every sentence in a generated draft must be traceable to either the parsed CV or an answer the user gave. Where evidence is missing, the system omits, flags, or asks — it never guesses. This is a non-negotiable constraint, not a nice-to-have, and it should be treated as a correctness requirement with the same weight as "the API returns 200."

## 2. Architecture style

Modular, service-based backend. Synchronous APIs for user-initiated actions (upload, submit, fetch status); asynchronous workers for anything CPU- or inference-bound (OCR, parsing, matching, generation). Document handling mixes I/O-bound and inference-bound work, so orchestration and inference are decoupled via a queue — this gives backpressure, retries, and clean status propagation without blocking the API.

Every AI-generation step takes structured input and returns structured, schema-validated output. No step calls a model with a raw prompt and free text back — everything is JSON-schema constrained (see Section 6).

## 3. Logical components

| Component | Responsibility |
|---|---|
| API gateway / application API | Authenticated REST endpoints, request validation, rate limiting, orchestration kickoff |
| Authentication service | Identity, sessions/tokens, role checks, access control |
| File ingestion service | CV upload validation, metadata capture, storage handoff |
| Self-hosted parser worker (Docling) | First-pass text and structure extraction for digital PDFs and DOCX |
| Amazon Textract enrichment worker | Second-pass completeness review, OCR recovery, layout/structure validation |
| Extraction merge layer | Reconciles parser + Textract output into one canonical extraction result |
| CV parser and normaliser | Section detection, field extraction, structured profile building, confidence flags |
| Job post ingestion service | Fetch by URL or accept pasted text, structure into a role profile |
| Matching engine | Evidence-based comparison of CV profile against job requirements |
| Tailored CV generation service | Structured, evidence-bound CV draft generation |
| Cover letter workflow engine | Question generation, answer capture, controlled letter drafting |
| Queue / job orchestration layer | Async handoff, retries, state transitions, worker coordination |
| Relational database (PostgreSQL) | Users, structured entities, drafts, answers, audit metadata |
| Object storage | Original uploads, extracted artefacts, exports |
| Observability layer | Logs, metrics, tracing, job status monitoring |

## 4. Document extraction strategy — the two-pass design

This is a deliberate two-stage pipeline, **not** a fallback pattern. Both stages run on every document.

**Stage 1 — Docling (self-hosted).** Fast first-pass extraction of text, reading order, and structure for digital PDFs and DOCX. Runs in our own infrastructure — no per-page vendor cost, no data leaving our environment at this stage.

**Stage 2 — Amazon Textract (managed).** Runs against the *same* uploaded file as a completeness and verification pass: recovers text the first pass may have missed, validates layout/structure, and handles OCR for scanned or image-based documents.

**Why both, always:** real-world CVs are messy — tables, columns, unusual headings, mixed fonts. Docling is strong on structured extraction but self-hosted parsers can silently drop content on odd layouts. Textract is a mature, benchmarked, production-grade document understanding service that catches what Docling misses. Running both and merging is more reliable than treating OCR as an emergency fallback for "bad" files only.

**Merge layer responsibilities:**
- Compare both outputs, preserve the highest-confidence text blocks.
- Run structural validation: section count comparison, heading alignment, reading order comparison, date range consistency, bullet preservation, line coverage.
- If confidence is low or a structural anomaly is detected, don't silently continue — flag the document, favour whichever source has higher confidence for that section, retain both passes for diagnostics, and optionally trigger a repair/reprocessing path.
- Produce one canonical extraction result. Downstream services never see two competing document views.

**What counts as a valid confidence score.** "Highest confidence wins" only works as a merge strategy if every parser's `confidence_score` measures the same underlying thing: how likely this specific extraction is to be correct. It does not mean "did this pass produce a non-trivial amount of output," "did parsing complete without an exception," or any other proxy that happens to move in the same rough direction as real confidence most of the time. Textract genuinely reports this (per-block OCR confidence, averaged) — Docling, run through the `DocumentParser` interface in §4a, needs a confidence figure that carries the same meaning, or the comparison in the bullet above is meaningless even though it looks like it's working.

This was a real bug caught during implementation, worth stating precisely so it isn't repeated: an early Docling implementation computed `confidence_score` as a function of output length alone (roughly, "is this suspiciously short for a CV") rather than anything about extraction quality. That heuristic returns a value near the top of the scale for almost any normal-length document, whether or not Docling actually extracted it well — so in the merge comparison against Textract's real, calibrated confidence, Docling would win most of the time regardless of actual quality, silently defeating the entire point of running two passes and comparing them. The bug was invisible from the outside: the pipeline ran, produced text, and nothing failed loudly. It only surfaces if you specifically test a case where Docling extracts *badly* and check whether the merge result reflects that.

The general principle, not just the specific fix: **a placeholder or proxy value in a field with a real semantic meaning is a correctness bug, not a cosmetic gap** — the field's type checks out, the code runs, and the failure is silent until someone tests the specific case the shortcut doesn't cover. This is the same category of risk the non-fabrication design (§6) exists to guard against in generated text; it applies just as much to a numeric field feeding a decision the pipeline makes automatically. Any field described as a "confidence," "quality," or "validation" score anywhere in this pack should be treated as a claim that needs to be true, not a formality that needs to be present. See `07-first-sprint-tasks.md` Sprint 3 for the concrete acceptance check this implies for the Docling worker task, and `09-test-plan.md` §2 for the corresponding test.

Keep the parser worker behind a swappable interface. If a CV-specific parser later outperforms Docling on resume-shaped documents, it should be a drop-in replacement, not a rearchitecture. See §4a for the concrete shape of that interface and the deployment spec for the Docling worker itself.

### 4a. Docling deployment and the swappable-parser interface

**Deployment.** Docling runs as its own containerised worker, separate from the API service and from the Textract-calling worker — this isolation matters for the resource and security reasons covered in `10-security-plan.md` §2 (sandboxing, no outbound network beyond what's needed), not just for scaling independence. With the stack now Python throughout (`01-implementation-plan.md` §2), this worker uses the same language, dependency tooling, and testing setup as the rest of the backend — there's no cross-language marshalling to design at this boundary, which removes a class of bugs (serialization mismatches, type drift between a Python worker and a non-Python caller) that a mixed-language stack would need to actively guard against.

| Aspect | Recommendation |
|---|---|
| Base image | Slim Python base (e.g. `python:3.11-slim`) with Docling and its dependencies installed — avoid a full OS image; smaller image surface is fewer things to patch and scan (`10-security-plan.md` §11). |
| CPU | Start at 2 vCPU per worker instance. Docling's extraction is CPU-bound (layout analysis, text positioning), not I/O-bound like the Textract call — size for compute, not for network wait. |
| Memory | Start at 2–4 GB per worker instance. PDF/DOCX parsing can spike on large or complex documents; this is also the resource ceiling that contains a resource-exhaustion attempt (`10-security-plan.md` §2) — enforce it as a hard container limit, not a soft guideline. |
| Concurrency | Matches `docling_extract: { concurrency: 5 }` already specified in `08-deployment-guide.md` §6 — each concurrent job needs its own memory headroom within the above, so total worker pool sizing is per-instance memory × concurrency, not per-instance memory alone. |
| Timeout | 60000ms (already specified) — enforced at the job level so a hung parse doesn't hold a worker slot indefinitely. |
| Network | No outbound access beyond what the container registry/package manager needs at build time. At runtime, no outbound network access at all — Docling doesn't need to call out anywhere, which makes deny-all-egress the correct runtime posture, not just a hardening nice-to-have. |
| Scaling | Horizontal — add worker instances behind the queue as `docling_extract` queue depth grows, rather than vertically scaling a single instance. Stateless by design (no data persisted in the container itself), so this is a clean horizontal-scale case. |

These are starting sizing numbers, not measured values — same caveat as the other placeholder figures in this pack (`01-implementation-plan.md` §6): load-test with representative CVs (per the test-file guidance in `07-first-sprint-tasks.md`) once Phase 1 extraction is running, and adjust CPU/memory to what's actually observed rather than the estimate above.

**The swappable interface.** "Keep it swappable" only means something if the interface boundary is defined before the first line of Docling-calling code is written. Concretely, in Python terms:

- Define an abstract base class — e.g. `DocumentParser(ABC)` — with one method: given a file (bytes/stream) and its MIME type, return a Pydantic model matching the `cv_extraction_passes` shape already in `03-data-model.md` §3 (`extracted_text`, `raw_output`, `engine`, `engine_version`, `confidence_score`, `characters`, `pages`, `processing_duration_ms`). Using a Pydantic model here, not a bare dict, gets validation on the interface boundary itself for free — consistent with the schema-everywhere design principle in `02-architecture-overview.md` §6.
- The Docling worker implements this interface as, e.g., `DoclingParser(DocumentParser)`. It does not leak Docling-specific types, options, or output shapes past the interface boundary — anything Docling-specific (its own internal document model, its own confidence representation) gets translated into the common Pydantic shape *inside* the implementation, not exposed to callers.
- The `pass_type` field (`docling`, `textract` today) is exactly the seam a future CV-specific parser would extend — adding a new `pass_type` value and a new `DocumentParser` implementation should not require changes to the merge layer's *logic*, only to which implementation it calls. If replacing Docling ever means touching the merge layer's comparison/validation logic, the interface boundary wasn't drawn in the right place.
- Keep provider-specific configuration (model paths, API keys, resource settings) in the deployment/environment layer, not hardcoded into the parser implementation — this is what actually makes "drop-in replacement" true operationally, not just at the code level.

This is a Phase 1 design task, not a Phase 5 refactor — defining the interface after the Docling implementation already exists means retrofitting an abstraction around code that wasn't written to it, which is a materially bigger job than designing the seam first. Add it explicitly to the Sprint 3 Docling worker task in `07-first-sprint-tasks.md`.

## 5. Processing pipeline (end to end)

1. Upload CV → store file → create processing job.
2. Docling first-pass extraction.
3. Textract second-pass completeness review.
4. Merge into canonical extraction result with completeness flags.
5. Parse and normalise into a structured, versioned candidate profile.
6. Ingest job post (URL fetch or pasted text).
7. Structure job post into required vs. preferred criteria and keywords.
8. Run match analysis (CV profile vs. job profile).
9. Generate tailored CV draft from verified evidence only.
10. Run guided cover letter question flow, capture answers.
11. Generate cover letter draft from verified evidence + user answers.
12. User reviews, edits, approves.
13. Export approved draft(s).

Steps 2–5 and 8–11 are asynchronous. The API returns job/draft identifiers immediately; the frontend polls or subscribes for status.

## 6. Non-fabrication controls (the core design constraint)

This is the system's defining requirement, so it's worth stating as concrete engineering controls rather than a principle:

- **Schema-constrained generation everywhere.** Every AI call that produces content used in a draft must return JSON conforming to a fixed schema (see `05-openapi.yaml` and the parsing/rewrite schemas). No free-text generation gets written to a draft without passing through a schema.
- **Evidence binding.** Every generated bullet, sentence, or section must carry a reference back to its source: a CV section, a specific extracted field, or a user-submitted answer ID. This is what `tailored_cv_sections` and `match_evidence_items` exist for (see `03-data-model.md`).
- **Nullable over invented.** Fields the system isn't confident about are `null` or `unknown`, never guessed.
- **Missing evidence ≠ negative evidence, and it's never filled in.** If a job post asks for "stakeholder management" and the CV doesn't mention it, the matching engine flags it as *unsupported* — it does not infer it, downplay it, or invent a bullet to cover the gap. The cover letter engine asks the user directly instead.
- **Validation and retry, not silent correction.** If a model response fails schema validation, retry with a corrective prompt or fail the job — never patch invalid output silently.
- **Token-efficient, evidence-scoped prompts.** Never send the full raw CV to a rewrite call. Parse once into a canonical profile, then build each rewrite prompt from only the structured fields relevant to that job post (summary, relevant experience bullets, matched skills, evidence links). This is both a cost control and a safety control — a smaller, scoped context is easier to keep evidence-bound than a full raw document dumped into a prompt. See `prompt_context_cache` in the data model for the three-level caching design (extraction / canonical profile / rewrite context) this depends on — each level has a different cost profile and a different invalidation trigger, so treat them as three caches with one shared table, not one undifferentiated cache.

## 7. Canonical profile versioning

CV profiles are **immutable snapshots**, not overwritten in place. Each parse creates a new `cv_profile_versions` row referencing its extraction passes, with a profile hash, schema version, and confidence summary. A separate "current profile pointer" gives fast reads without losing history. This enables rollback, regression comparison, and safe prompt cache invalidation (cache keys off the profile hash).

## 8. Infrastructure shape (recommended)

| Layer | Component |
|---|---|
| Edge | CDN + load balancer / API gateway |
| API | Containerised service (Python/FastAPI recommended — see `01-implementation-plan.md` §2 for stack rationale) |
| Background jobs | Queue + stateless worker services, split by responsibility (extraction, parsing, matching, generation) |
| Database | Managed PostgreSQL |
| File storage | Managed object storage (S3-compatible) |
| Cache | Managed Redis — prompt context cache, rate limiting, short-lived workflow state |
| Document processing | Self-hosted Docling worker (see §4a for container/sizing spec) + Amazon Textract |
| LLM integration | Structured-output-capable provider (schema-validated responses) |
| Monitoring | Centralised logs, metrics, tracing, alerting, dead-letter queue for failed jobs |
| Secrets | Managed secrets vault (never in code or env files in version control) |

## 9. Sequence diagram

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant FE as Frontend
    participant API as Backend API
    participant OBJ as Object Storage
    participant Q as Queue
    participant DOC as Docling Worker
    participant TX as Textract Worker
    participant PAR as Parser Worker
    participant JOB as Job Post Service
    participant MAT as Matching Service
    participant GEN as Generation Service
    participant DB as PostgreSQL

    User->>FE: Upload CV and submit job post
    FE->>API: POST CV file + job post input
    API->>OBJ: Store original CV file
    API->>DB: Create cv record and processing job
    API->>Q: Enqueue Docling extraction job
    API-->>FE: Return ids and initial status

    Q->>DOC: Process first-pass extraction
    DOC->>OBJ: Read stored CV file
    DOC->>DB: Save first-pass extraction result
    DOC->>Q: Enqueue Textract enrichment job

    Q->>TX: Process completeness review
    TX->>OBJ: Read stored CV file
    TX->>DB: Save Textract extraction result
    TX->>Q: Enqueue merge + parsing job

    Q->>PAR: Merge extraction passes, validate structure
    PAR->>DB: Save canonical extraction result
    PAR->>PAR: Build structured candidate profile
    PAR->>DB: Save versioned candidate profile

    FE->>API: Submit job post (URL or pasted text)
    API->>JOB: Fetch/clean job post content
    JOB->>DB: Save raw + structured job post

    FE->>API: Request match analysis
    API->>Q: Enqueue matching job
    Q->>MAT: Compare CV profile vs job profile
    MAT->>DB: Save match run + evidence items
    MAT-->>API: Match ready

    FE->>API: Request tailored CV generation
    API->>Q: Enqueue CV draft generation
    Q->>GEN: Generate evidence-bound CV draft
    GEN->>DB: Save draft + traceability metadata
    API-->>FE: Tailored CV ready

    FE->>API: Start cover letter workflow
    API->>GEN: Create guided question set
    GEN->>DB: Save workflow + questions
    API-->>FE: Return first questions

    User->>FE: Answer guided questions
    FE->>API: Submit answers
    API->>DB: Save answers
    API->>Q: Enqueue cover letter generation
    Q->>GEN: Generate evidence-bound letter draft
    GEN->>DB: Save draft + sources
    API-->>FE: Cover letter draft ready
```

## 10. Estimated per-run cost (for planning, not a quote)

Rough order of magnitude, based on a 2-page CV, one tailored CV generation, one cover letter generation:

| Component | Estimated cost |
|---|---|
| Docling (self-hosted compute) | negligible per-run, fixed infra cost instead |
| Amazon Textract (2 pages) | ~$0.003 |
| CV rewrite LLM call | ~$0.042 |
| Cover letter LLM call | ~$0.025 |
| Storage (S3, ~3MB/month) | ~$0.00007 |
| **Total per completed application pack** | **~$0.05–$0.10** |

LLM tokens dominate cost, not OCR or storage. This is the practical justification for the token-efficient rewrite architecture in Section 6 — sending compact structured fields instead of raw CV text on every rewrite call is the single biggest lever on unit cost at scale. Treat these numbers as planning inputs; validate with real usage once Phase 3 is live.
