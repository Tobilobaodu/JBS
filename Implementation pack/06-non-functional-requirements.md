# Non-Functional Requirements

## 1. Reliability and validation

- Every AI-generation step returns schema-constrained output (see `05-openapi.yaml` schemas). Responses that fail schema validation are retried once with a corrective prompt; a second failure marks the `processing_job` as `failed` — never persisted as a partial or guessed draft.
- Safe failure is the default. Where required evidence is absent, the system withholds the claim rather than inserting anything uncertain.
- Async processing (extraction, parsing, matching, generation) must support retries with backoff and a dead-letter queue for jobs that exhaust retries, so failures are visible for manual inspection rather than silently dropped.

## 2. Auditability and traceability

- Every generated draft section must carry `evidenceReferences` back to source CV content or a user-submitted answer. This is enforced at the schema/validation layer, not left to convention.
- `audit_events` is append-only. No update or delete path should exist for this table at the application layer.
- Audit metadata must be sufficient to answer, for any generated sentence: "where did this come from?" — this is a product requirement (user transparency) as much as a compliance one.

## 3. Performance and scalability

- All OCR, parsing, matching, and generation work runs through the queue — no synchronous path should block on any of these steps.
- Architecture should scale by adding worker instances per job type independently (extraction workers, parsing workers, matching workers, generation workers), not as a single monolithic worker pool.
- Design for phased scaling: the Phase 1–2 volume (early users, testing) does not need the same worker capacity as post-launch volume — provision accordingly rather than over-building infrastructure upfront.

## 4. Security and privacy

### Data classification

Treat as personal data, with corresponding handling: uploaded CVs, extracted text, structured candidate profiles, cover letter answers, generated drafts. Contact details, work history, and education records are sensitive from an application security perspective.

Keep raw uploaded documents, derived structured data, and generated outputs in separate storage/table boundaries so retention rules, access policies, and deletion workflows can be applied consistently and independently.

### Access control

- All endpoints handling documents, profiles, drafts, or audit trails require authenticated access.
- Authorisation ensures users only access their own files, records, drafts, and exports — enforce this at the query layer (scope every query by `user_id`), not only at the route/middleware layer.
- Admin/support access, where it exists, must be role-based, time-limited, and logged.
- Service accounts, workers, storage access, and database roles follow least privilege.

### Encryption

- Encryption at rest for user files and structured personal data (managed platform encryption or equivalent).
- TLS for all data in transit: client↔API, API↔storage, API↔workers, workers↔third-party model/OCR providers.
- Secrets (API keys, DB credentials, storage tokens, signing keys) live in a managed secrets vault — never in source code or committed environment files.

### Retention, deletion, lifecycle

- Explicit retention rules per data category: original uploads, extracted text, structured profiles, draft versions, audit records.
- User-facing deletion must actually remove documents and derived records (not just soft-delete flags), subject to any lawful/operational retention requirement that's been explicitly documented.
- Temporary files from OCR/parsing/generation are deleted automatically once processing completes — these should never persist beyond the job lifecycle.
- Where draft history is retained for user convenience, the retention period should be configurable and disclosed to the user.

### Third-party processing

- Route only the minimum necessary data to external OCR/LLM providers (this is also why the token-efficient rewrite architecture in `02-architecture-overview.md` matters for privacy, not just cost).
- Evaluate provider data handling terms, regional hosting, retention settings, and whether provider-side training on submitted content can be disabled — this should be a documented decision per provider, not assumed.
- Keep the extraction/generation provider interfaces swappable so a stricter deployment model can be adopted later without a rearchitecture.
- Log requests to third-party services in a way that supports diagnostics without storing unnecessary personal content in the log itself.

### Audit logging and incident readiness

- Log security-relevant events: authentication actions, uploads, processing job creation, privileged access, export generation, deletion requests.
- Audit logs must be protected against tampering and retained per policy.
- Have a documented incident response path for: document exposure, cross-user data access, failed deletion, prompt leakage, unauthorised administrative access. At minimum this means traceability, access review, and controlled revocation procedures exist and are tested — not just written down.

## 5. Compliance expectations

The platform processes personal data relating to identifiable users, so it should be designed to support UK/GDPR-style obligations where relevant: transparency, access control, deletion handling, retention discipline, processor due diligence. The implementation should not block a later privacy notice or a record of processing activities (what's collected, why, how long retained) — i.e. the data model and deletion mechanics need to actually support answering those questions, even if the legal documents themselves are out of scope here.

**Formal legal compliance advice is out of scope for engineering.** This section describes what the backend needs to support, not a substitute for legal review before launch.

## 6. Assumptions

- The frontend manages account-level UX, review interfaces, and document editing — the backend exposes APIs and processing states for the frontend to consume in real time or near-real time.
- Job post URLs submitted by users are assumed publicly accessible without complex anti-bot protection. Where a URL can't be fetched, the user is expected to paste the job description instead — this is a documented fallback, not a bug (see `04-api-reference.md` error handling).

## 7. Explicit exclusions (out of scope unless raised via change control)

- Frontend design, implementation, and user journey work.
- Rich text browser editing components.
- Third-party ATS submission / auto-apply features.
- CRM integrations and recruiter workflow tooling.
- Advanced multilingual support (future roadmap only).
- Employer-side analytics, recruiter dashboards, candidate ranking modules.

Any requirement introducing employer-side workflows, external platform submission, new supported document types, multilingual expansion, advanced analytics, or recruiter collaboration should go through change control. Same for anything affecting data retention, compliance obligations, or security posture — assess separately before implementation, don't fold it into an existing sprint.
