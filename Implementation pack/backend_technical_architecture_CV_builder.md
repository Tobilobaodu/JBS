# Backend Technical Architecture for AI CV Tailoring and Cover Letter Platform

## Overview

This document defines the proposed backend technical architecture for a platform that ingests user CVs, structures job posts, generates a tailored CV and supports a guided cover letter workflow without fabricating experience, achievements or figures[web:76][web:78]. The architecture is designed around structured document processing, asynchronous job orchestration, validated AI outputs and traceable evidence mapping so generated content remains reviewable and grounded in user supplied information[web:68][web:76][web:81].

The recommended design uses an API layer, asynchronous workers, document extraction services, AI generation services, relational storage, object storage and an audit friendly data model. This approach aligns well with production document processing systems, where ingestion, extraction, validation and generation are separated so the platform can scale and fail safely[web:68][web:72][web:75]. For your preferred ingestion strategy, the architecture should use a two step document extraction path for CVs: a quick parser as the first pass for digital PDFs and DOCX files, followed by Amazon Textract as a second pass to review the file for completeness and recover text, layout or structural detail that the quick parser may miss[page:4].

## Technical architecture section

### Architecture style

A modular service based backend is recommended for this project. The core pattern should combine synchronous API endpoints for user initiated actions with asynchronous processing for OCR, CV parsing, job post structuring, role matching and generation workflows[web:68][web:72][web:81].

This split matters because document handling includes both I O bound and inference bound work. Research on OCR and LLM pipelines highlights the value of decoupling orchestration from inference, using queues for backpressure, retries and status propagation while exposing direct APIs for submission and retrieval[web:68].

### Logical components

The backend should be organised into the following logical components:

| Component | Responsibility |
|---------|---------|
| API gateway or application API | Authenticated REST endpoints, request validation, rate limiting and orchestration kickoff |
| Authentication service | User identity, sessions or tokens, role checks and access control |
| File ingestion service | CV upload validation, metadata capture and storage handoff |
| Quick parser worker | Fast first pass text extraction for digital PDFs and DOCX files before downstream enrichment |
| Amazon Textract enrichment worker | Second pass document review for completeness, OCR, layout recovery and structured document signals[page:4] |
| CV parser and normaliser | Section detection, field extraction, profile structuring and confidence flags[web:78][web:81] |
| Job post ingestion service | Fetching job post content by URL or accepting pasted text, then structuring the role profile |
| Matching engine | Evidence based comparison between user experience and job requirements |
| Tailored CV generation service | Structured generation of CV drafts using source grounded content[web:76] |
| Cover letter workflow engine | Interactive question generation, answer capture and controlled cover letter drafting |
| Queue and job orchestration layer | Asynchronous handoff, retries, state transitions and worker coordination[web:68][web:72] |
| Relational database | Users, jobs, parsed entities, drafts, answers, audit metadata |
| Object storage | Original CV uploads, extracted artefacts, rendered exports and optional logs[web:72][web:75] |
| Observability layer | Logs, metrics, tracing, alerts and job status monitoring |

### Processing model

The backend should follow a staged document processing pipeline. Intelligent document processing systems commonly move through ingestion, preprocessing, OCR, extraction, validation and structured output storage, which maps well to this use case[web:78][web:81]. In your preferred design, OCR is not only a rescue path for broken files. Instead, the quick parser and Amazon Textract should work as two deliberate stages, where the first stage extracts fast text and the second stage reviews the document for completeness, OCR quality and missing structure before normalisation[page:4].

For this product, the proposed stages are:
1. Upload or receive CV.
2. Store file and create processing job.
3. Run a quick parser against the uploaded digital PDF or DOCX to obtain a first pass text extraction.
4. Run Amazon Textract against the document as a second pass to validate completeness, recover missed text and improve structural coverage[page:4].
5. Merge the first pass and Textract outputs into a canonical extraction result with completeness flags.
6. Parse and normalise the merged CV content into structured candidate data.
7. Ingest job post from URL or pasted text.
8. Structure job post into required and optional criteria.
9. Run match analysis.
10. Generate tailored CV draft from verified evidence only.
11. Run guided cover letter questions and capture answers.
12. Generate cover letter draft from verified evidence plus user answers[web:68][web:78][web:81].

### Design constraints

The architecture should enforce schema validated outputs for AI generated steps. Structured outputs are recommended because they ensure responses conform to predefined formats such as JSON schemas, improving consistency and downstream reliability[web:73][web:76].

The architecture should also isolate raw document content from derived structured entities, because document pipelines benefit from clear boundaries between ingestion, extraction, validation and load phases[web:78]. This separation improves auditability, retention control and future provider replacement flexibility.

### Document extraction strategy

For this product, the recommended CV ingestion design is a two step extraction strategy rather than a fallback model. Step one should use a quick parser for digital PDFs and DOCX files so the system can get immediate plain text and document metadata with low latency. Step two should run Amazon Textract against the same uploaded document as a completeness and verification pass, reviewing the file for missing text, layout segmentation, forms like structures and OCR recoverable content that the first pass may not preserve[page:4].

The merge layer should compare quick parser output and Textract output, preserve the highest confidence text blocks, capture disagreements for internal diagnostics and produce a canonical extraction result for downstream CV normalisation. This keeps Textract in the primary ingestion path without forcing the rest of the system to consume two competing document views.

## API endpoints

The API should be versioned, for example under `/api/v1`, and designed around authenticated user workflows. The endpoints below represent a practical minimum set for the described product.

### Authentication and user session

| Method | Endpoint | Purpose |
|---------|---------|---------|
| POST | `/api/v1/auth/register` | Create user account |
| POST | `/api/v1/auth/login` | Authenticate user and issue session or token |
| POST | `/api/v1/auth/logout` | End session |
| GET | `/api/v1/auth/me` | Return current user profile and permissions |

### CV upload and parsing

| Method | Endpoint | Purpose |
|---------|---------|---------|
| POST | `/api/v1/cvs` | Upload CV file, validate, store and create processing job |
| GET | `/api/v1/cvs` | List uploaded CVs for the current user |
| GET | `/api/v1/cvs/{cvId}` | Get CV metadata and latest processing state |
| GET | `/api/v1/cvs/{cvId}/raw-text` | Get canonical extracted text for review, with merged parser and Textract result |
| GET | `/api/v1/cvs/{cvId}/extraction-detail` | Get first pass parser output, Textract enrichment result and completeness metadata |
| GET | `/api/v1/cvs/{cvId}/parsed-profile` | Get structured candidate profile |
| POST | `/api/v1/cvs/{cvId}/reprocess` | Re trigger quick parsing, Textract enrichment or full parsing workflow |
| DELETE | `/api/v1/cvs/{cvId}` | Delete uploaded CV and derived records subject to policy |

### Job post ingestion

| Method | Endpoint | Purpose |
|---------|---------|---------|
| POST | `/api/v1/job-posts/url` | Submit job post URL for fetch and structuring |
| POST | `/api/v1/job-posts/text` | Submit pasted job post text for structuring |
| GET | `/api/v1/job-posts` | List job posts linked to the current user |
| GET | `/api/v1/job-posts/{jobPostId}` | Get raw and structured job post data |
| POST | `/api/v1/job-posts/{jobPostId}/reprocess` | Re run cleaning or structuring logic |

### Matching and tailoring

| Method | Endpoint | Purpose |
|---------|---------|---------|
| POST | `/api/v1/matches` | Create a match analysis between a CV and a job post |
| GET | `/api/v1/matches/{matchId}` | Retrieve match analysis and evidence flags |
| POST | `/api/v1/matches/{matchId}/tailored-cv` | Generate a tailored CV draft from the match result |
| GET | `/api/v1/tailored-cvs/{draftId}` | Retrieve a tailored CV draft |
| POST | `/api/v1/tailored-cvs/{draftId}/regenerate` | Regenerate using revised instructions or approved changes |
| POST | `/api/v1/tailored-cvs/{draftId}/approve` | Mark draft as approved for export |

### Cover letter workflow

| Method | Endpoint | Purpose |
|---------|---------|---------|
| POST | `/api/v1/cover-letters/start` | Start a guided cover letter workflow from CV and job post |
| GET | `/api/v1/cover-letters/{workflowId}/questions` | Retrieve the next question set |
| POST | `/api/v1/cover-letters/{workflowId}/answers` | Submit user answers for the active step |
| GET | `/api/v1/cover-letters/{workflowId}/draft` | Retrieve the current cover letter draft |
| POST | `/api/v1/cover-letters/{workflowId}/regenerate` | Regenerate letter after user edits or new answers |
| POST | `/api/v1/cover-letters/{workflowId}/approve` | Mark letter as approved for export |

### Jobs, audit and exports

| Method | Endpoint | Purpose |
|---------|---------|---------|
| GET | `/api/v1/jobs/{jobId}` | Get async processing job status |
| GET | `/api/v1/audit/{entityType}/{entityId}` | Retrieve evidence links and generation history |
| POST | `/api/v1/exports/cv/{draftId}` | Request export package for approved CV draft |
| POST | `/api/v1/exports/cover-letter/{workflowId}` | Request export package for approved cover letter |
| POST | `/api/v1/exports/application-pack` | Export approved CV plus approved cover letter together |

### API design notes

The upload and submission endpoints should be synchronous only for acceptance and validation, with heavy work delegated to background jobs. Production OCR and LLM pipeline designs commonly use synchronous submission paths paired with asynchronous job coordination through queues and status updates[web:68].

Each endpoint that triggers AI output should return identifiers for draft objects and job objects rather than blocking until full completion. This allows the frontend to poll, subscribe or refresh status while workers complete long running tasks[web:68][web:72].

## Database schema requirements

A relational database such as PostgreSQL is recommended because the product requires transactional integrity, clear entity relationships, version history and auditability. The schema should support both operational data and traceability of generated outputs back to user supplied evidence.

### Core entities

| Table | Purpose |
|---------|---------|
| `users` | User account, identity and account metadata |
| `user_sessions` | Session or refresh token records |
| `cv_files` | Original upload metadata, object storage key, processing state |
| `cv_raw_text` | Canonical extracted text, OCR markers and extraction metadata |
| `cv_extraction_passes` | First pass parser output, Textract output, confidence and completeness metadata |
| `cv_profiles` | Latest structured candidate profile summary |
| `cv_profile_versions` | Versioned structured profile snapshots |
| `cv_experience_items` | Normalised work experience rows |
| `cv_education_items` | Normalised education rows |
| `cv_skill_items` | Skills and optional categorisation |
| `job_posts` | Submitted job post raw content and source type |
| `job_post_profiles` | Structured job requirements and keywords |
| `match_runs` | Match analysis results between CV and role |
| `match_evidence_items` | Requirement by requirement evidence mapping |
| `tailored_cv_drafts` | Generated CV drafts and approval status |
| `tailored_cv_sections` | Draft sections and evidence linked content blocks |
| `cover_letter_workflows` | Workflow state for cover letter generation |
| `cover_letter_questions` | Generated question sets per workflow step |
| `cover_letter_answers` | User submitted answers |
| `cover_letter_drafts` | Generated cover letter versions |
| `processing_jobs` | Async job tracking across all pipelines |
| `audit_events` | Security, processing and generation audit trail |
| `exports` | Export requests, statuses and file references |

### Important schema requirements

#### users
- Primary key.
- Email or external identity reference.
- Account status.
- Created at and updated at timestamps.

#### cv_files
- Primary key.
- Foreign key to `users`.
- Original filename.
- Mime type.
- File size.
- Object storage path.
- Upload status and processing status.
- Timestamps.

#### cv_raw_text
- Primary key.
- Foreign key to `cv_files`.
- Canonical merged extracted text.
- OCR used flag.
- Merge strategy metadata.
- Extraction confidence if available.
- Timestamp.

#### cv_extraction_passes
- Primary key.
- Foreign key to `cv_files`.
- Pass type, for example quick parser or Textract.
- Raw extracted text or structured extraction payload.
- Engine metadata.
- Confidence or completeness score where available.
- Processing duration.
- Timestamp.

#### cv_profiles and profile detail tables
- Foreign key to `cv_files` and `users`.
- Summary fields for current profile.
- Version number.
- Confidence summary.
- Structured JSON payload for full profile.
- Separate normalised child tables for experience, education and skills to support querying, matching and reporting.

#### job_posts and job_post_profiles
- Foreign key to `users`.
- Source type, URL or pasted text.
- Raw text copy.
- Structured requirement JSON.
- Required criteria array.
- Preferred criteria array.
- Keywords and phrases array.
- Parsing status and timestamps.

#### match_runs
- Foreign key to `users`, `cv_files`, `job_posts`.
- Match score fields if used.
- Summary analysis.
- Unsupported requirement count.
- Status.
- Created at.

#### match_evidence_items
- Foreign key to `match_runs`.
- Requirement text.
- Requirement type, for example required or preferred.
- Support level, for example supported, partially supported, unsupported.
- Source references to CV sections or user answers.
- Reviewer flags.

#### tailored_cv_drafts
- Foreign key to `users`, `match_runs`.
- Draft version.
- Status, for example generated, user edited, approved, archived.
- Structured content JSON.
- Render ready text blocks.
- Hallucination guard result or validation result.
- Created at and approved at.

#### cover_letter_workflows and related tables
- Workflow foreign keys to `users`, `cv_files`, `job_posts` and optionally `match_runs`.
- Current step.
- Workflow status.
- Question set version.
- User answer records with timestamps.
- Draft records with version numbers and approval state.

#### processing_jobs
- Job id.
- Job type, for example OCR, CV parse, job post parse, match, CV draft, cover letter draft.
- Source entity type and id.
- Status, retry count and last error.
- Worker metadata.
- Timestamps.

#### audit_events
- Event id.
- User id if applicable.
- Entity type and id.
- Event type.
- Actor type, for example user, admin, system worker.
- Metadata JSON.
- Timestamp.

### Data modelling recommendations

The schema should mix relational tables for queryable entities with JSON columns for model output payloads and versioned snapshots. This works well for AI powered document systems because validation and review often require both structured queryable fields and the original model response context[web:76][web:78].

Soft deletion flags may be useful for operational recovery, but hard deletion workflows should still be supported for privacy requirements and user initiated removal requests. The schema should also support evidence references at section or sentence level so the frontend can explain why a draft bullet or paragraph exists.

## Recommended infrastructure components

A cloud native stack with managed services is recommended for the first production version because the workload mixes web APIs, object storage, background processing, AI integration and personal data handling.

### Application and API layer
- Containerised API service, for example Node.js or similar, deployed on managed containers or Kubernetes.
- API gateway or load balancer for HTTPS termination, routing and rate limiting.
- Authentication provider or identity layer for user accounts and session control.

### Storage layer
- Object storage for CV files, intermediate artefacts and exports[web:72][web:75].
- PostgreSQL for operational data, versioning, audit and workflow state.
- Optional Redis for caching, rate limit counters and short lived workflow state.

### Asynchronous processing
- Message queue for document and generation jobs. Production document pipelines use queues to provide backpressure, retries and decoupled scaling[web:68][web:72].
- Worker services separated by responsibility, such as extraction worker, parser worker, matching worker and generation worker[web:68].

### AI and document processing
- Quick parser for digital PDFs and DOCX files as the first extraction stage.
- Amazon Textract as the second stage for document review, OCR enrichment and completeness validation[page:4].
- Structured output capable LLM provider for parsing, matching and controlled generation[web:73][web:76].
- Optional provider abstraction layer so OCR or LLM vendors can be swapped later.

### Observability and operations
- Centralised logs.
- Metrics and alerting.
- Distributed tracing for long running multi service jobs.
- Dead letter queue for failed tasks requiring manual inspection.

### Security and compliance support
- Secrets manager for API keys, database credentials and signing secrets.
- Managed key encryption or cloud KMS.
- Access logging and audit storage.
- Backup and recovery services for database and object storage.

### Suggested deployment shape

| Layer | Recommended component |
|---------|---------|
| Edge | CDN plus load balancer or API gateway |
| API | Container service hosting the application API |
| Background jobs | Queue plus stateless worker services |
| Database | Managed PostgreSQL |
| File storage | Managed object storage |
| Cache | Managed Redis, optional but useful |
| OCR | Managed OCR service or dedicated extraction worker |
| LLM integration | Structured output capable model provider |
| Monitoring | Logs, metrics, tracing, alerting |
| Secrets | Managed secrets vault |

## High level sequence diagram for backend flow

The sequence below shows the end to end backend flow from CV upload through tailored CV and guided cover letter generation.

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant FE as Frontend
    participant API as Backend API
    participant OBJ as Object Storage
    participant Q as Queue
    participant QP as Quick Parser Worker
    participant TX as Textract Worker
    participant PAR as Parser Worker
    participant JOB as Job Post Service
    participant MAT as Matching Service
    participant GEN as Generation Service
    participant DB as PostgreSQL

    User->>FE: Upload CV and submit job post
    FE->>API: POST CV file and job post input
    API->>OBJ: Store original CV file
    API->>DB: Create cv record and processing jobs
    API->>Q: Enqueue quick parsing job
    API-->>FE: Return ids and initial status

    Q->>QP: Process quick parsing job
    QP->>OBJ: Read stored CV file
    QP->>QP: Extract first pass text from digital PDF or DOCX
    QP->>DB: Save first pass extraction result
    QP->>Q: Enqueue Textract enrichment job

    Q->>TX: Process Textract enrichment job
    TX->>OBJ: Read stored CV file
    TX->>TX: Review document for completeness and OCR recovery
    TX->>DB: Save Textract extraction result
    TX->>Q: Enqueue CV parsing job

    Q->>PAR: Process CV parsing job
    PAR->>DB: Read merged extraction result
    PAR->>PAR: Build structured candidate profile
    PAR->>DB: Save structured CV profile

    FE->>API: Submit job post URL or pasted text
    API->>JOB: Fetch or clean job post content
    JOB->>DB: Save raw and structured job post

    FE->>API: Request match analysis
    API->>Q: Enqueue matching job
    Q->>MAT: Process matching job
    MAT->>DB: Read CV profile and job profile
    MAT->>MAT: Map evidence and unsupported gaps
    MAT->>DB: Save match run and evidence items
    MAT-->>API: Match ready

    FE->>API: Request tailored CV generation
    API->>Q: Enqueue CV draft generation job
    Q->>GEN: Process CV draft generation
    GEN->>DB: Read structured inputs and evidence map
    GEN->>GEN: Generate validated tailored CV draft
    GEN->>DB: Save draft and traceability metadata
    API-->>FE: Tailored CV ready

    FE->>API: Start cover letter workflow
    API->>GEN: Create guided question set
    GEN->>DB: Save workflow and questions
    API-->>FE: Return first questions

    User->>FE: Answer guided questions
    FE->>API: Submit answers
    API->>DB: Save answers
    API->>Q: Enqueue cover letter generation job
    Q->>GEN: Process cover letter generation
    GEN->>DB: Read CV, job post, evidence and answers
    GEN->>GEN: Generate validated cover letter draft
    GEN->>DB: Save letter draft and sources
    API-->>FE: Cover letter draft ready
```

## Implementation notes

The most important backend quality rule is that every AI generation step should be driven by structured inputs and return structured outputs wherever possible[web:73][web:76]. The architecture should also favour asynchronous processing and explicit state transitions because OCR and LLM pipelines are naturally multi step and benefit from queue based coordination[web:68][web:72].

Finally, the database and API contract should preserve evidence links between source content and generated outputs. That requirement is what allows the product to enforce the non fabrication rule in a practical, reviewable way.
