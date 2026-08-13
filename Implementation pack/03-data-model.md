# Data Model

PostgreSQL is the system of record. Relational tables for queryable, joinable entities; JSON columns for full model-output payloads and versioned snapshots. This mix matters here specifically because the non-fabrication rule needs both: structured fields for querying and matching, and the original structured response preserved for evidence/audit review.

Column types below are a concrete starting point, not gospel — adjust precision/length to real data once Phase 1 is running, but keep the *shapes* (immutability, array-based evidence references, polymorphic job tracking) as designed, since those encode decisions the product depends on.

## 1. Entity list

| Table | Purpose |
|---|---|
| `users` | Account, identity, status |
| `user_sessions` | Session/refresh token records |
| `cv_files` | Original upload metadata, storage key, processing state |
| `cv_extraction_passes` | Docling output, Textract output, confidence/completeness metadata — one row per pass per file |
| `cv_raw_text` | Canonical *merged* extracted text, OCR-used flag, merge strategy metadata, structural validation result |
| `cv_profiles` | Fast-read pointer to the current structured candidate profile |
| `cv_profile_versions` | Immutable versioned profile snapshots |
| `cv_experience_items` | Normalised work experience rows |
| `cv_education_items` | Normalised education rows |
| `cv_skill_items` | Skills, optional categorisation |
| `job_posts` | Raw job post content + source type (URL/pasted) |
| `job_post_profiles` | Structured job requirements, required vs. preferred, keywords |
| `match_runs` | Match analysis run between a CV profile version and a job post |
| `match_evidence_items` | Requirement-by-requirement evidence mapping |
| `tailored_cv_drafts` | Generated CV drafts, versions, approval status |
| `tailored_cv_sections` | Draft sections/bullets with evidence links |
| `cover_letter_workflows` | Guided workflow state |
| `cover_letter_questions` | Generated question sets per step |
| `cover_letter_answers` | User-submitted answers |
| `cover_letter_drafts` | Generated letter versions |
| `prompt_context_cache` | Cached compact CV/job-post context blocks, keyed by profile hash, for rewrite cost reduction |
| `processing_jobs` | Async job tracking across all pipelines |
| `audit_events` | Security, processing, and generation audit trail |
| `exports` | Export requests, status, file references |
| `ats_readiness_checks` | ATS structural-readability score and check detail, separate from Docling/Textract agreement — product extension #1, see `11-product-extensions.md` |
| `job_post_collections` | User-defined groups of job posts for aggregate comparison — product extension #2 |
| `coverage_reports` | Aggregated match-gap report across a job post collection — product extension #2 |

## 2. Key relationships

- `users` 1→many `cv_files`, `job_posts`, `user_sessions`
- `cv_files` 1→many `cv_extraction_passes`, `cv_profile_versions`
- `cv_profile_versions` 1→many `cv_experience_items`, `cv_education_items`, `cv_skill_items` (**not** `cv_files` directly — see the versioning note in §4)
- `job_posts` 1→1 `job_post_profiles`
- `cv_profile_versions` + `job_post_profiles` feed `match_runs`
- `match_runs` 1→many `match_evidence_items`, `tailored_cv_drafts`
- `tailored_cv_drafts` 1→many `tailored_cv_sections`
- `cover_letter_workflows` link `users`, `cv_files`, `job_posts`, and optionally `match_runs`
- `cover_letter_workflows` 1→many `cover_letter_questions`, `cover_letter_answers`, `cover_letter_drafts`
- `processing_jobs` reference a polymorphic source entity (`source_entity_type`, `source_entity_id`)
- `prompt_context_cache` keyed by `source_hash` (profile hash or job-post hash) + `context_type`

## 3. Table definitions

### `users`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID (PK) | |
| `email` | VARCHAR(255) NOT NULL UNIQUE | |
| `password_hash` | VARCHAR(255) NOT NULL | bcrypt or equivalent |
| `status` | VARCHAR(50) DEFAULT 'active' | `active`, `suspended`, `deleted` |
| `created_at` | TIMESTAMPTZ NOT NULL | |
| `updated_at` | TIMESTAMPTZ NOT NULL | |
| `last_active` | TIMESTAMPTZ | |

Indexes: `idx_users_email` on `email`.

### `user_sessions`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID (PK) | |
| `user_id` | UUID NOT NULL (FK → `users`) | |
| `refresh_token` | VARCHAR(255) NOT NULL UNIQUE | |
| `access_token` | VARCHAR(255) NOT NULL | |
| `expires_at` | TIMESTAMPTZ NOT NULL | |
| `ip_address` | VARCHAR(45) | for audit, not display |
| `user_agent` | TEXT | |
| `created_at` | TIMESTAMPTZ NOT NULL | |
| `revoked_at` | TIMESTAMPTZ | |

Indexes: `idx_sessions_user` on `user_id`; `idx_sessions_refresh_token` on `refresh_token`; `idx_sessions_expires` on `expires_at`.

### `cv_files`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID (PK) | |
| `user_id` | UUID NOT NULL (FK → `users`) | |
| `filename` | VARCHAR(255) NOT NULL | original filename |
| `mime_type` | VARCHAR(100) NOT NULL | |
| `file_size` | INTEGER NOT NULL | bytes |
| `storage_key` | VARCHAR(500) NOT NULL | object storage path |
| `status` | VARCHAR(50) DEFAULT 'pending' | `pending`, `extracting`, `merging`, `parsing`, `completed`, `failed` |
| `error_message` | TEXT | populated on `failed` |
| `created_at` | TIMESTAMPTZ NOT NULL | |
| `updated_at` | TIMESTAMPTZ NOT NULL | |
| `deleted_at` | TIMESTAMPTZ | soft-delete marker — see §4 rule 4 |

Indexes: `idx_cvs_user` on `user_id`; `idx_cvs_status` on `status`.

### `cv_extraction_passes`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID (PK) | |
| `cv_file_id` | UUID NOT NULL (FK → `cv_files`) | |
| `pass_type` | VARCHAR(50) NOT NULL | `docling`, `textract` |
| `extracted_text` | TEXT NOT NULL | raw pass output |
| `raw_output` | JSONB | full structured extraction payload beyond plain text (layout, blocks) |
| `engine` | VARCHAR(100) | e.g. `docling-2.0`, `amazon-textract` |
| `engine_version` | VARCHAR(50) | |
| `confidence_score` | DECIMAL(3,2) | nullable — must represent genuine per-parser extraction confidence (Textract: averaged OCR block confidence; Docling: a real parse-quality signal), never a proxy like output length or "did parsing complete without an exception." See `02-architecture-overview.md` §4 for why this matters — a proxy value here silently breaks the merge layer's "highest confidence wins" comparison without any visible failure. |
| `characters` | INTEGER | |
| `pages` | INTEGER | |
| `processing_duration_ms` | INTEGER | |
| `created_at` | TIMESTAMPTZ NOT NULL | |

Indexes: `idx_passes_cv` on `cv_file_id`; `idx_passes_cv_type` UNIQUE on `(cv_file_id, pass_type)` — **one Docling pass and one Textract pass per CV file per processing cycle.** A `reprocess` call creates a new `cv_files` processing cycle logically, but if passes are re-run against the same `cv_files.id`, either version the pass rows (add `attempt_number`) or archive prior passes before inserting new ones — pick one explicitly rather than letting the unique constraint silently reject reprocessing.

### `cv_raw_text`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID (PK) | |
| `cv_file_id` | UUID NOT NULL (FK → `cv_files`) | |
| `canonical_text` | TEXT NOT NULL | merged, highest-confidence text |
| `characters` | INTEGER | |
| `merge_strategy` | VARCHAR(50) | `highest_confidence`, `union`, `manual` |
| `merge_strategy_metadata` | JSONB | which pass won for which section, disagreement log |
| `ocr_used` | BOOLEAN DEFAULT FALSE | |
| `structural_validation_result` | JSONB | section count match, heading alignment score, reading order consistency, date range consistency, bullet preservation score, `anomaly_detected`, `anomaly_detail` |
| `created_at` | TIMESTAMPTZ NOT NULL | |

Indexes: `idx_raw_cv` UNIQUE on `cv_file_id`.

### `cv_profiles` (pointer) / `cv_profile_versions` (immutable snapshots)

**`cv_profile_versions`** — the source of truth. Never updated after insert.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID (PK) | |
| `cv_file_id` | UUID NOT NULL (FK → `cv_files`) | |
| `user_id` | UUID NOT NULL (FK → `users`) | denormalised for query convenience |
| `version_number` | INTEGER NOT NULL | sequence per `cv_file_id` |
| `profile_hash` | VARCHAR(64) NOT NULL | SHA-256, used for prompt cache invalidation |
| `schema_version` | VARCHAR(20) NOT NULL | |
| `source_pass_ids` | UUID[] | references into `cv_extraction_passes` |
| `structured_payload` | JSONB NOT NULL | full profile: basics, summary, etc. |
| `confidence_summary` | JSONB | per-section confidence scores |
| `validation_status` | VARCHAR(50) | `passed`, `partial`, `failed` |
| `created_at` | TIMESTAMPTZ NOT NULL | |

Indexes: `idx_profile_versions_cv` on `cv_file_id`; `idx_profile_versions_hash` on `profile_hash`.

**`cv_profiles`** — fast-read pointer only. This table is *not* a source of truth and holds no content of its own.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID (PK) | |
| `cv_file_id` | UUID NOT NULL (FK → `cv_files`) | |
| `current_version_id` | UUID (FK → `cv_profile_versions.id`) | moves on each successful re-parse |
| `updated_at` | TIMESTAMPTZ NOT NULL | |

Indexes: `idx_profiles_cv` UNIQUE on `cv_file_id`.

### `cv_experience_items`, `cv_education_items`, `cv_skill_items`

**These key off `cv_profile_version_id`, not `cv_file_id` or `cv_profiles.id`.** This is the fix to a real modelling trap: if a CV gets reprocessed and a new profile version is created, child rows must stay attached to the exact version they were extracted from, or a regeneration against an older `match_run` (which references a specific `cv_profile_version_id`) has no reliable way to pull the experience/skill rows that were actually used as evidence at match time.

**Section-heading canonicalization.** The parser that populates these tables needs to map varied real-world heading text to a fixed, small set of canonical `section_type` values, since CVs use inconsistent terminology for the same section. At minimum, map the following heading variants to a single canonical form before populating the tables below — this list isn't exhaustive, but it's the common cluster worth hardcoding rather than rediscovering per-CV:

| Canonical section | Common heading variants to map from |
|---|---|
| `work_experience` | Employment History, Professional Experience, Work Experience, Career History, Employment Record |
| `education` | Education, Academic Background, Qualifications, Academic History |
| `skills` | Skills, Technical Skills, Core Competencies, Areas of Expertise |
| `certifications` | Certifications, Licenses, Professional Certifications, Credentials |
| `projects` | Projects, Key Projects, Selected Projects, Portfolio |
| `summary` | Summary, Professional Summary, Profile, About, Objective |

If a heading doesn't confidently match any canonical section, don't force it into the closest-looking one — this is the same non-fabrication principle applied to structure rather than content. Store it with `section_type: unknown` and a `needs_review` flag (surfaced via the relevant row's `confidence` field being low, or via a dedicated flag if the parser distinguishes "low confidence" from "no match at all") rather than guessing. Misclassifying "Voluntary Experience" as `work_experience`, for instance, could let volunteer work silently masquerade as paid employment in a generated draft — a structural misclassification is still a fabrication risk, not just a cosmetic one.

`cv_experience_items`:

| Column | Type | Notes |
|---|---|---|
| `id` | UUID (PK) | |
| `cv_profile_version_id` | UUID NOT NULL (FK → `cv_profile_versions`) | |
| `company` | VARCHAR(255) | nullable — unknown over guessed |
| `title` | VARCHAR(255) | nullable |
| `start_date` | DATE | nullable |
| `end_date` | DATE | nullable if current |
| `current` | BOOLEAN DEFAULT FALSE | |
| `bullets` | TEXT[] | |
| `technologies` | TEXT[] | |
| `confidence` | DECIMAL(3,2) | nullable |
| `source_reference` | TEXT | pointer into `cv_raw_text.canonical_text` (offset or section label) |

`cv_education_items`: same pattern — `cv_profile_version_id` FK, `institution`, `degree`, `field`, `year`, `confidence`, `source_reference`.

`cv_skill_items`: same pattern — `cv_profile_version_id` FK, `skill_name`, `category` (`technical`/`soft`/`other`), `confidence`, `source_reference`.

Indexes on each: index on `cv_profile_version_id`; `cv_skill_items` additionally indexes `skill_name` for matching-engine lookups.

### `job_posts` / `job_post_profiles`

`job_posts`:

| Column | Type | Notes |
|---|---|---|
| `id` | UUID (PK) | |
| `user_id` | UUID NOT NULL (FK → `users`) | |
| `source_type` | VARCHAR(20) NOT NULL | `url`, `text` |
| `source_url` | VARCHAR(500) | nullable |
| `raw_text` | TEXT NOT NULL | |
| `status` | VARCHAR(50) DEFAULT 'pending' | `pending`, `fetching`, `structuring`, `completed`, `failed` |
| `error_message` | TEXT | |
| `created_at` | TIMESTAMPTZ NOT NULL | |
| `updated_at` | TIMESTAMPTZ NOT NULL | |

`job_post_profiles`:

| Column | Type | Notes |
|---|---|---|
| `id` | UUID (PK) | |
| `job_post_id` | UUID NOT NULL (FK → `job_posts`) | |
| `job_title` | VARCHAR(255) | nullable |
| `employer` | VARCHAR(255) | nullable |
| `location` | VARCHAR(255) | nullable |
| `required_skills` | TEXT[] | |
| `preferred_skills` | TEXT[] | |
| `responsibilities` | TEXT[] | |
| `qualifications` | TEXT[] | |
| `keywords` | TEXT[] | |
| `seniority` | VARCHAR(50) | nullable — don't force a guess if not stated |
| `structured_json` | JSONB | full structured representation |
| `confidence` | DECIMAL(3,2) | |
| `created_at` | TIMESTAMPTZ NOT NULL | |

Indexes: `idx_job_profiles_job` UNIQUE on `job_post_id`.

### `match_runs`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID (PK) | |
| `user_id` | UUID NOT NULL (FK → `users`) | |
| `cv_profile_version_id` | UUID NOT NULL (FK → `cv_profile_versions`) | pins the exact profile snapshot used |
| `job_post_profile_id` | UUID NOT NULL (FK → `job_post_profiles`) | |
| `status` | VARCHAR(50) DEFAULT 'pending' | `pending`, `analyzing`, `completed`, `failed` |
| `score` | DECIMAL(5,2) | optional overall score, 0–100 |
| `supported_count` | INTEGER | |
| `partial_count` | INTEGER | |
| `unsupported_count` | INTEGER | |
| `total_requirements` | INTEGER | |
| `summary_analysis` | TEXT | |
| `match_json` | JSONB | full analysis payload |
| `error_message` | TEXT | |
| `created_at` | TIMESTAMPTZ NOT NULL | |
| `completed_at` | TIMESTAMPTZ | |

Indexes: `idx_matches_user` on `user_id`; `idx_matches_cv_profile` on `cv_profile_version_id`; `idx_matches_job` on `job_post_profile_id`; `idx_matches_status` on `status`.

### `match_evidence_items`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID (PK) | |
| `match_run_id` | UUID NOT NULL (FK → `match_runs`) | |
| `requirement_text` | TEXT NOT NULL | |
| `requirement_type` | VARCHAR(20) NOT NULL | `required`, `preferred` |
| `support_level` | VARCHAR(20) NOT NULL | `supported`, `partially_supported`, `unsupported`, `contradictory`, `unclear` — see the table below for what each means and what the generation layer is allowed to do with it |
| `confidence` | DECIMAL(3,2) | |
| `source_references` | JSONB (array) | pointers to `cv_experience_items.id`, `cv_skill_items.id`, `cv_education_items.id`, or `cover_letter_answers.id` — **array, not a single string**, since one requirement can be supported by more than one piece of evidence. For `contradictory`, this array holds the conflicting sources themselves (e.g. two `cv_experience_items` rows with overlapping but inconsistent date ranges), not a resolution — resolution is a user or reviewer action, not something the matching engine decides on its own |
| `suggestion` | TEXT | nullable — improvement suggestion for partial support |
| `warning` | TEXT | nullable — populated on `unsupported` and `contradictory` |
| `created_at` | TIMESTAMPTZ NOT NULL | |

Indexes: `idx_evidence_match` on `match_run_id`.

**Support level definitions and permitted downstream action:**

| Level | Meaning | Permitted in generated output |
|---|---|---|
| `supported` | Direct evidence exists and is internally consistent | May be used as-is |
| `partially_supported` | Related evidence exists but wording or scope differs from the requirement | May be used with careful wording — the generation layer should narrow the claim to what the evidence actually shows, not round up to the requirement's phrasing |
| `unsupported` | No reliable evidence found anywhere in the CV or confirmed answers | Must not be included without explicit user confirmation (e.g. via a cover-letter clarifying question) |
| `contradictory` | Two or more sources disagree (e.g. conflicting employment dates, inconsistent job titles for what looks like the same role) | Must not be used until resolved — surface to the user as a flag needing their input, never silently pick one source over the other |
| `unclear` | Extraction confidence for the relevant CV section is too low to trust either way | Must not be used; route to a review/clarification step rather than either including or discarding the claim |

`contradictory` and `unclear` are meaningfully different failure modes and shouldn't be collapsed into `unsupported`: `unsupported` means "no evidence," `contradictory` means "evidence exists but conflicts with itself," and `unclear` means "evidence might exist but extraction wasn't confident enough to say." Each implies a different fix — asking the user directly (`unsupported`), asking the user to resolve a conflict (`contradictory`), or reprocessing/reviewing the source document (`unclear`) — and collapsing them loses the information needed to route to the right one. This is a direct implication of the non-fabrication design already established in `02-architecture-overview.md` §6: a system that only tracks "supported vs. not" can't distinguish "confidently absent" from "confusingly present," and the latter needs a different, more careful response.

### `tailored_cv_drafts` / `tailored_cv_sections`

`tailored_cv_drafts`:

| Column | Type | Notes |
|---|---|---|
| `id` | UUID (PK) | |
| `user_id` | UUID NOT NULL (FK → `users`) | |
| `match_run_id` | UUID NOT NULL (FK → `match_runs`) | |
| `version_number` | INTEGER NOT NULL | |
| `status` | VARCHAR(50) DEFAULT 'generated' | `generated`, `user_edited`, `approved`, `archived` |
| `content_json` | JSONB NOT NULL | structured draft content |
| `render_text` | TEXT | render-ready plain text, if precomputed |
| `instructions` | TEXT | user-supplied generation instructions, nullable |
| `validation_result` | JSONB | `{ passed: bool, issues: [...] }` — schema/evidence-gate result, see §4 rule 3 |
| `created_at` | TIMESTAMPTZ NOT NULL | |
| `updated_at` | TIMESTAMPTZ NOT NULL | |
| `approved_at` | TIMESTAMPTZ | |

Indexes: `idx_drafts_user` on `user_id`; `idx_drafts_match` on `match_run_id`; `idx_drafts_status` on `status`.

`tailored_cv_sections`:

| Column | Type | Notes |
|---|---|---|
| `id` | UUID (PK) | |
| `draft_id` | UUID NOT NULL (FK → `tailored_cv_drafts`) | |
| `section_type` | VARCHAR(50) NOT NULL | `summary`, `work_experience`, `education`, `skills`, `certifications`, `projects` |
| `content_text` | TEXT NOT NULL | |
| `evidence_references` | JSONB (array) NOT NULL | **must be non-empty** — see §4 rule 3 |
| `generation_task` | VARCHAR(100) | nullable — which specific generation step produced this (e.g. `tailored_cv_experience_bullet`, `tailored_cv_summary`), for debugging and auditing a specific section's provenance without reconstructing it from the draft as a whole |
| `prompt_version` | VARCHAR(50) | nullable — the versioned prompt template used, so a prompt regression can be traced to exactly which generated sections it affected. Prompts should be versioned files per `02-architecture-overview.md`, not inline strings, precisely so this field means something stable |
| `model_id` | VARCHAR(100) | nullable — which model/provider generated this section. Matters once more than one model is ever in use (e.g. a cheaper model for a low-risk step, a stronger one for rewriting) and something needs debugging |
| `validation_status` | VARCHAR(20) | nullable — `passed`, `warning`, `failed`, mirroring the draft-level `validation_result` in `tailored_cv_drafts` but at per-section granularity, so a partial validation failure doesn't have to fail an entire draft to be visible |
| `order_index` | INTEGER | |

Indexes: `idx_sections_draft` on `draft_id`.

The four provenance columns (`generation_task`, `prompt_version`, `model_id`, `validation_status`) exist for the same reason `evidence_references` does: when a generated claim is questioned — by the user, by a support investigation, or by a future regression — "which evidence supports this" is only half the answer. "Which prompt and model produced this specific wording, and did it pass validation at the time" is the other half, and without these columns that second question can only be reconstructed from logs, if the logs still exist and can be correlated back to this exact row. Nullable because Phase 3's first working version can populate them incrementally rather than blocking on having every field wired up on day one — but they should exist on the table from the start; adding them later means backfilling or losing provenance for everything generated before the column existed.

### `cover_letter_workflows` and related

`cover_letter_workflows`:

| Column | Type | Notes |
|---|---|---|
| `id` | UUID (PK) | |
| `user_id` | UUID NOT NULL (FK → `users`) | |
| `cv_file_id` | UUID NOT NULL (FK → `cv_files`) | |
| `job_post_id` | UUID NOT NULL (FK → `job_posts`) | |
| `match_run_id` | UUID (FK → `match_runs`) | nullable — optional |
| `status` | VARCHAR(50) DEFAULT 'in_progress' | `in_progress`, `completed`, `approved`, `archived` |
| `current_step` | INTEGER DEFAULT 0 | |
| `total_steps` | INTEGER | |
| `question_set_version` | INTEGER | |
| `created_at` | TIMESTAMPTZ NOT NULL | |
| `updated_at` | TIMESTAMPTZ NOT NULL | |
| `completed_at` | TIMESTAMPTZ | |
| `approved_at` | TIMESTAMPTZ | |

`cover_letter_questions`: `id` (PK), `workflow_id` (FK), `step_number`, `question_text`, `question_category` (`employer_interest`/`motivation`/`relevant_example`/`tone_preference`/`availability`/`clarification`), `required` (boolean), `help_text` (nullable), `created_at`.

`cover_letter_answers`: `id` (PK), `workflow_id` (FK), `question_id` (FK), `answer_text`, `submitted_at`.

`cover_letter_drafts`:

| Column | Type | Notes |
|---|---|---|
| `id` | UUID (PK) | |
| `workflow_id` | UUID NOT NULL (FK → `cover_letter_workflows`) | |
| `version_number` | INTEGER NOT NULL | |
| `status` | VARCHAR(50) DEFAULT 'generated' | `generated`, `user_edited`, `approved`, `archived` |
| `content_json` | JSONB NOT NULL | includes per-paragraph text + evidence, see note below and API doc for shape |
| `render_text` | TEXT | |
| `tone` | VARCHAR(50) | nullable |
| `word_count` | INTEGER | |
| `evidence_references` | JSONB (array) NOT NULL | same non-empty rule as CV sections |
| `prompt_version` | VARCHAR(50) | nullable — versioned prompt template used for this draft version, same rationale as `tailored_cv_sections.prompt_version` |
| `model_id` | VARCHAR(100) | nullable — model/provider that generated this draft version |
| `validation_result` | JSONB | |
| `created_at` | TIMESTAMPTZ NOT NULL | |
| `approved_at` | TIMESTAMPTZ | |

Indexes: `idx_letter_drafts_workflow` on `workflow_id`.

Unlike `tailored_cv_sections`, a cover letter draft is one row per version rather than one row per section — a letter's paragraphs don't map to a fixed enum of section types the way a CV's do. Per-paragraph evidence provenance (which sentence traces to the CV versus which traces to a specific `cover_letter_answers` row) still needs to exist, but it lives *inside* `content_json` as a structured array (paragraph text plus its own `evidence_references`), not as separate table rows. This is a deliberate structural difference, not an inconsistency with the CV drafts table — a letter genuinely doesn't have a fixed section taxonomy, so forcing it into the same row-per-section shape as a CV would mean inventing arbitrary section boundaries that don't reflect how a cover letter is actually structured.

### `prompt_context_cache`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID (PK) | |
| `cache_key` | VARCHAR(255) NOT NULL UNIQUE | see the three-level key structure below — this isn't one flat namespace |
| `user_id` | UUID NOT NULL (FK → `users`) | |
| `context_type` | VARCHAR(20) NOT NULL | `extraction`, `cv_summary`, `rewrite_context` — exactly the three levels defined below, no other values |
| `source_hash` | VARCHAR(64) NOT NULL | see per-level key composition below |
| `compact_payload` | JSONB NOT NULL | scoped, minimal context actually sent to the model, or the extraction result at level one |
| `expires_at` | TIMESTAMPTZ | |
| `created_at` | TIMESTAMPTZ NOT NULL | |
| `updated_at` | TIMESTAMPTZ NOT NULL | |

Indexes: `idx_cache_key` UNIQUE on `cache_key`; `idx_cache_hash` on `source_hash`; `idx_cache_expires` on `expires_at`.

This table is not a source of truth and can be safely wiped/rebuilt at any level — PostgreSQL (the tables above) remains authoritative. Use three distinct cache levels, each with its own key composition and invalidation trigger, rather than one flat cache — a single undifferentiated cache either over-invalidates (wiping cheap extraction results whenever an unrelated rewrite input changes) or under-invalidates (serving stale rewrite context after a CV edit), and neither failure is obvious until it's already caused a wrong or wasteful result:

| Level | `context_type` | Key composition | What it stores | Invalidates when |
|---|---|---|---|---|
| 1 — Document extraction | `extraction` | `sha256(original_file_bytes + parser_version)` | Docling result, Textract result, structural comparison, canonical extraction | The file content or parser version changes — never on anything downstream, since raw extraction is independent of any specific job post or rewrite |
| 2 — Canonical profile | `cv_summary` | `cv_profile_hash + schema_version` | Compact candidate profile, searchable experience items, normalised skills, evidence references | The profile is reprocessed into a new version, or the profile schema version changes |
| 3 — Rewrite context | `rewrite_context` | `sha256(cv_profile_hash + job_post_profile_hash + prompt_version + schema_version + model_id)` | Selected summary, relevant experience bullets, relevant skills, job requirements, evidence references, validation metadata — i.e. the compact payload actually sent to the rewrite model | Any one of: the CV changes, the user edits a confirmed experience item, the job post changes, the prompt version changes, the schema version changes, or the model changes in a way that affects output compatibility |

Level 3 is the one this pack's cost estimate (`02-architecture-overview.md` §10) depends on most directly — it's the cache that prevents re-sending a full scoped context to the LLM on every regeneration when nothing relevant has actually changed. Level 1 is the one most worth getting right early, since Docling/Textract extraction is the most expensive *fixed* cost per CV and the least likely to need re-running once a CV is stable.

### `processing_jobs`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID (PK) | |
| `job_type` | VARCHAR(50) NOT NULL | `docling_extract`, `textract_extract`, `merge_parse`, `job_post_parse`, `match`, `cv_generate`, `cover_letter_generate`, `export` |
| `source_entity_type` | VARCHAR(50) NOT NULL | `cv_file`, `job_post`, `match_run`, `tailored_cv_draft`, `cover_letter_workflow` |
| `source_entity_id` | UUID NOT NULL | |
| `user_id` | UUID (FK → `users`) | |
| `status` | VARCHAR(20) DEFAULT 'pending' | `pending`, `queued`, `processing`, `completed`, `failed`, `retrying` |
| `progress` | DECIMAL(3,2) DEFAULT 0 | optional 0–1 progress indicator |
| `retry_count` | INTEGER DEFAULT 0 | |
| `max_retries` | INTEGER DEFAULT 3 | |
| `last_error` | TEXT | |
| `worker_metadata` | JSONB | |
| `created_at` | TIMESTAMPTZ NOT NULL | |
| `started_at` | TIMESTAMPTZ | |
| `completed_at` | TIMESTAMPTZ | |
| `failed_at` | TIMESTAMPTZ | |

Indexes: `idx_jobs_user` on `user_id`; `idx_jobs_status` on `status`; `idx_jobs_source` on `(source_entity_type, source_entity_id)`; `idx_jobs_type` on `job_type`.

**One processing_jobs row represents one pipeline; job_type represents the current stage.** Multi-stage pipelines (CV: docling → textract → merge → cv_parse; job post: fetch → parse) reuse the same row. Each worker updates `job.job_type` to the next stage before enqueueing the downstream task.

**Not every `job_type` value is a stage in a multi-stage pipeline.** `match`, `cv_generate`, `cover_letter_generate`, and `export` are each a single-stage, one-shot job: the row is created with that `job_type` and never transitions to another value before completing or failing. Only the CV-extraction family (`docling_extract` → `textract_extract` → `merge_parse`) and the job-post family (`job_post_fetch`/`job_post_parse`) reuse a row across stages. Don't assume every `processing_jobs` row's `job_type` changes over its lifetime — check whether the specific value is part of a documented multi-stage family before writing code that waits for a transition.

`job_type` is `VARCHAR(50)`, not a Postgres `ENUM` or a `CHECK`-constrained column — deliberately, so a new stage or job type can ship without a migration. The value set is enforced at the application layer (the worker/orchestration code that sets it), not the database. This is the same trade-off as `status` and the other lifecycle-string columns in this table.

### `audit_events`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID (PK) | |
| `user_id` | UUID (FK → `users`) | nullable — some events are system-initiated |
| `entity_type` | VARCHAR(50) | |
| `entity_id` | UUID | |
| `event_type` | VARCHAR(50) NOT NULL | `upload`, `login`, `parse`, `match`, `generate`, `approve`, `export_generated`, `deletion_requested`, `admin_access` |
| `actor_type` | VARCHAR(50) NOT NULL | `user`, `admin`, `system_worker` |
| `metadata` | JSONB | |
| `ip_address` | VARCHAR(45) | nullable |
| `user_agent` | TEXT | nullable |
| `created_at` | TIMESTAMPTZ NOT NULL | |

Indexes: `idx_audit_user` on `user_id`; `idx_audit_entity` on `(entity_type, entity_id)`; `idx_audit_event` on `event_type`; `idx_audit_created` on `created_at`.

**Append-only.** No application-level update or delete path — protect against tampering per the compliance requirements in `06-non-functional-requirements.md`.

### `exports`

**Format decision resolved (Sprint 5, 2026-08-12).** DOCX is the primary export format, with multiple ATS-ready template layouts to choose from (`app/services/export_templates.py`). PDF is secondary — available only after the DOCX for that export has actually been *downloaded*, and is always a conversion of that exact file (via Gotenberg, a self-hosted LibreOffice-backed HTTP service — not an independently-rendered PDF) rather than a parallel format. An application-pack export is a ZIP of two independent, already-ATS-safe DOCX files, not a merged document — merging risks breaking each file's own ATS structure.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID (PK) | |
| `user_id` | UUID NULLABLE (FK → `users`) | **Deviation from this table's originally documented `NOT NULL`** — see below |
| `trial_session_id` | UUID NULLABLE (FK → `trial_sessions`) | **New.** Exactly one of `user_id`/`trial_session_id` set, enforced by a `CHECK` (`ck_exports_exactly_one_owner`), same pattern as `tailored_cv_drafts`/`cv_files`/`job_posts`/`match_runs`. Required because `export_type='cv'` must be trial-accessible — tailored CV generation itself already is, end to end, so a trial user finishing that flow shouldn't hit an account wall exporting it. A second `CHECK` (`ck_exports_trial_only_for_cv`) enforces `trial_session_id IS NULL OR export_type = 'cv'` at the DB layer, since `cover_letter`/`application_pack` exports always require a `CoverLetterWorkflow`, which is account-only. |
| `export_type` | VARCHAR(20) NOT NULL | `cv`, `cover_letter`, `application_pack` |
| `source_id` | UUID NOT NULL | the approved draft ID being exported (for `cover_letter`, the specific `CoverLetterDraft.id`, not the workflow id) |
| `secondary_source_id` | UUID NULLABLE | **New.** Holds the `CoverLetterDraft.id` for `application_pack` rows — `source_id` alone can't represent an export with two source rows. |
| `format` | VARCHAR(20) NOT NULL DEFAULT 'docx' | **Resolved** — `docx`, `pdf`, `zip`, `CHECK`-constrained (`ck_exports_format`) |
| `template_id` | VARCHAR(50) NULLABLE | **New.** Which CV layout was used; `NULL` for cover-letter/pdf/zip rows |
| `status` | VARCHAR(20) DEFAULT 'pending' | `pending`, `processing`, `completed`, `failed` |
| `storage_key` | VARCHAR(500) | nullable until complete |
| `file_size` | INTEGER | nullable |
| `downloaded_at` | TIMESTAMPTZ NULLABLE | **New.** Set the first time `GET /exports/{exportId}/download` succeeds — this is the field that gates PDF conversion. |
| `derived_from_export_id` | UUID NULLABLE (FK → `exports.id`, self) | **New.** Set on `format='pdf'` rows, pointing at the source `docx` row; `CHECK`-enforced (`ck_exports_pdf_requires_source`) that every `pdf` row has one. |
| `error_message` | TEXT | |
| `created_at` | TIMESTAMPTZ NOT NULL | |
| `completed_at` | TIMESTAMPTZ | |

Indexes: `idx_exports_user`, `idx_exports_trial_session`, `idx_exports_status`, `idx_exports_source_id`, `idx_exports_derived_from`.

**Same migration (010) also adds `tailored_cv_sections.source_item_id`** (nullable UUID, no FK — polymorphic, same convention as `processing_jobs.source_entity_id`): points at the `cv_experience_items.id`/`cv_project_items.id` a generated section came from. Needed so the DOCX export renderer can attach a real company/title/date header to each experience/project block — `content_json` has one section per role/project but nothing previously recorded which row it came from. `NULL` for `summary`/`education`/`skills` sections, which have no single source row.

## 3a. Product extension tables

The tables below support the product extensions detailed in `11-product-extensions.md` — read that document for the full design rationale; this section is the schema reference. They're additive to everything above: no existing table's shape changes except where explicitly noted (`match_evidence_items` and `cv_profile_versions` each get one new nullable column, called out below).

### `ats_readiness_checks`

Supports product extension #1 (ATS structural validation). One row per check run against a specific extraction result — distinct from `cv_raw_text.structural_validation_result`, which compares Docling against Textract; this table evaluates the *merged* result against known ATS-parsing-hostile patterns, independent of which parser produced what.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID (PK) | |
| `cv_file_id` | UUID NOT NULL (FK → `cv_files`) | |
| `cv_profile_version_id` | UUID NOT NULL (FK → `cv_profile_versions`) | which profile version this check ran against |
| `overall_score` | DECIMAL(3,2) | 0–1, see `11-product-extensions.md` §1 for how this is composed from the individual checks below — not a single model call, a rules-based composite |
| `checks` | JSONB NOT NULL | array of individual check results, each `{ check_type, passed, severity, detail }` — see the check type list in `11-product-extensions.md` §1 |
| `contact_info_parseable` | BOOLEAN | specifically flagged separately from the general `checks` array since a missing/unparseable contact block is close to an automatic-reject condition on most real ATS systems, not just one flaw among several |
| `created_at` | TIMESTAMPTZ NOT NULL | |

Indexes: `idx_ats_checks_cv` on `cv_file_id`; `idx_ats_checks_profile` on `cv_profile_version_id`.

### `job_post_collections` / `coverage_reports`

Supports product extension #2 (multi-job-post comparison and coverage-gap reporting).

`job_post_collections` — a user-defined group of job posts to compare against, e.g. "roles I'm actively targeting":

| Column | Type | Notes |
|---|---|---|
| `id` | UUID (PK) | |
| `user_id` | UUID NOT NULL (FK → `users`) | |
| `name` | VARCHAR(255) | user-supplied label |
| `job_post_ids` | UUID[] | references into `job_posts`; capped at 50 entries at the validation layer (Sprint 5) — uncapped would let one report trigger an unbounded number of match_engine runs |
| `created_at` | TIMESTAMPTZ NOT NULL | |
| `updated_at` | TIMESTAMPTZ NOT NULL | |

`coverage_reports` — the aggregated result of running one CV profile version against every job post in a collection:

| Column | Type | Notes |
|---|---|---|
| `id` | UUID (PK) | |
| `user_id` | UUID NOT NULL (FK → `users`) | |
| `cv_profile_version_id` | UUID NOT NULL (FK → `cv_profile_versions`) | |
| `collection_id` | UUID NOT NULL (FK → `job_post_collections`) | |
| `match_run_ids` | UUID[] | the individual `match_runs` this report aggregates — the report never recomputes matching itself, it summarises existing runs |
| `aggregate_gaps` | JSONB NOT NULL | requirements that recur across multiple job posts in the collection with `unsupported`/`contradictory`/`unclear` support, ranked by recurrence — see `11-product-extensions.md` §2 for the exact shape |
| `skipped_job_post_ids` | UUID[] NULLABLE | **New (Sprint 5), beyond the originally documented schema.** Job posts in the collection skipped because their `JobPostProfile` wasn't ready yet — the report still completes for the rest, never blocks on one unstructured posting. `recurrence_ratio`'s denominator is the full collection size regardless, so a skip genuinely lowers the ratio rather than being silently excluded from it — this field is what makes that shortfall visible instead of unexplained. |
| `status` | VARCHAR(20) DEFAULT 'pending' | `pending`, `processing`, `completed`, `failed` |
| `created_at` | TIMESTAMPTZ NOT NULL | |
| `completed_at` | TIMESTAMPTZ | |

Indexes: `idx_coverage_user` on `user_id`; `idx_coverage_collection` on `collection_id`; `idx_coverage_status` on `status`.

A `coverage_report` is a read/aggregation model over existing `match_runs` — it doesn't introduce a new matching algorithm, just a new query and ranking step over data the matching engine (already built in Phase 3) already produces. This is why it's a comparatively low-risk addition despite being new tables: no new AI generation surface, no new evidence-binding logic to get right.

**Built Sprint 5 (2026-08-12).** `_get_or_run_match()`/`_run_and_persist_match()` in `worker_jobs.py` reuse an existing completed `MatchRun` for a given `(cv_profile_version_id, job_post_profile_id)` pair when one exists (no such lookup existed before — `POST /matches` always created a fresh row unconditionally), and run+persist a fresh one via the exact same matching code `process_match` itself uses otherwise — coverage reporting deliberately shares this code path rather than risking a second, differently-tuned matching engine. Clustering for `aggregate_gaps` reuses the ESCO/O*NET taxonomy lookup built for M2 (`app/extraction/skills_index.py`) rather than a bespoke normalizer, per the spec's own "light normalization... full semantic clustering deferred" scoping.

### `tailored_cv_drafts` extension: fix-it checklist

Supports product extension #3 (confidence-calibrated "what to fix before you apply" checklist). No new table — one new column on the existing `tailored_cv_drafts` table:

| Column | Type | Notes |
|---|---|---|
| `improvement_checklist` | JSONB | nullable — array of `{ requirement_text, support_level, suggestion, priority }` items, synthesised directly from the `match_evidence_items` behind this draft's `match_run_id`. This is a read-time synthesis over already-computed evidence, not a new generation call requiring its own schema validation and evidence-binding pass — see `11-product-extensions.md` §3 for why keeping it a synthesis step, not a new AI generation surface, matters for both cost and fabrication risk. |

### `match_evidence_items` extension: user feedback signal

Supports product extension #5 (feedback signal for match-quality improvement). One new nullable column:

| Column | Type | Notes |
|---|---|---|
| `user_feedback` | JSONB | nullable — `{ feedback_type: 'incorrect_support_level' \| 'evidence_actually_present' \| 'other', corrected_support_level, user_note, submitted_at }`. Populated only when a user explicitly flags a match result as wrong — never inferred or defaulted. This is diagnostic data for improving matching-engine prompts/heuristics over time, not itself evidence used in any generation call — a user's disagreement with a match result doesn't retroactively become `supported` evidence without the underlying CV or job-post data actually changing. |

### `cv_profile_versions` extension: master CV lineage

Supports product extension #4 (master CV concept). One new nullable column:

| Column | Type | Notes |
|---|---|---|
| `master_profile_id` | UUID | nullable, self-referencing conceptually — see `11-product-extensions.md` §4 for the full design. Points to the `cv_profile_versions.id` that this version was derived from as a "base," distinct from `version_number`'s reprocess lineage (same file, re-parsed) — this tracks "same underlying CV, evolved by the user between applications," which is a different relationship. |

## 4. Modelling rules a developer should follow

1. **Canonical CV profiles are immutable.** Never `UPDATE` a `cv_profile_versions` row. A re-parse creates a new version row; the pointer in `cv_profiles` moves.
2. **Child rows (experience/education/skills) key off `cv_profile_version_id`, not `cv_file_id`.** This is deliberate, not incidental — see the note under `cv_experience_items` above. Getting this wrong means a `match_run` pinned to an old profile version can't reliably reconstruct the evidence it actually used once the CV is reprocessed.
3. **Evidence references are mandatory on generated content, and are arrays.** A `tailored_cv_sections` row or `cover_letter_drafts` row with empty `evidence_references` should fail validation before it's persisted as `generated` — this is the schema-level enforcement of the non-fabrication rule. Arrays because one bullet or claim can legitimately be supported by more than one source (e.g. a CV bullet plus a clarifying cover-letter answer).
4. **Raw text and structured JSON are stored separately**, always. Never derive structured fields from raw text at read time in a request path — that work happens once, at parse time, and is persisted.
5. **Soft-delete flags (`deleted_at`) are fine for operational recovery**, but every table holding personal data must also support a real hard-delete path for user-initiated deletion requests (see compliance requirements). Don't build soft-delete as the *only* deletion mechanism.
6. **`processing_jobs` is the single source of truth for async status.** The frontend should never infer job status by polling a domain table (e.g. checking if `cv_profiles.current_version_id` is null) — always read `processing_jobs`.
7. **`cv_extraction_passes` has a unique constraint on `(cv_file_id, pass_type)`.** Decide explicitly how `reprocess` behaves against this constraint (archive-and-replace vs. an `attempt_number` column) before building the reprocess endpoint — don't let it surface as a runtime uniqueness error nobody planned for.
8. **Any field named "confidence," "quality," or "validation" score must measure the thing its name claims, not a proxy that happens to correlate with it.** `confidence_score` specifically has caused a real bug (see the field note above and `02-architecture-overview.md` §4) where a length-based heuristic silently passed as a genuine confidence value — the pipeline ran and produced output with no visible error, and the failure only showed up when someone tested a case the shortcut didn't cover. Treat this as a general caution across the schema, not a one-off fix: a plausible-looking value in a semantically-loaded field is a correctness bug wearing the shape of a working feature.

## 5. JSON schema: canonical CV profile

The `structured_payload` stored in `cv_profile_versions`:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["basics", "workExperience", "education", "skills"],
  "properties": {
    "basics": {
      "type": "object",
      "properties": {
        "name": { "type": ["string", "null"] },
        "email": { "type": ["string", "null"] },
        "phone": { "type": ["string", "null"] },
        "location": { "type": ["string", "null"] },
        "summary": { "type": ["string", "null"] }
      }
    },
    "workExperience": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "id": { "type": "string" },
          "company": { "type": ["string", "null"] },
          "title": { "type": ["string", "null"] },
          "startDate": { "type": ["string", "null"], "format": "date" },
          "endDate": { "type": ["string", "null"], "format": "date" },
          "current": { "type": "boolean" },
          "bullets": { "type": "array", "items": { "type": "string" } },
          "technologies": { "type": "array", "items": { "type": "string" } }
        }
      }
    },
    "education": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "id": { "type": "string" },
          "institution": { "type": ["string", "null"] },
          "degree": { "type": ["string", "null"] },
          "field": { "type": ["string", "null"] },
          "year": { "type": ["integer", "null"] }
        }
      }
    },
    "skills": {
      "type": "object",
      "properties": {
        "technical": { "type": "array", "items": { "type": "string" } },
        "soft": { "type": "array", "items": { "type": "string" } }
      }
    },
    "certifications": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "id": { "type": "string" },
          "name": { "type": "string" },
          "issuer": { "type": ["string", "null"] },
          "year": { "type": ["integer", "null"] }
        }
      }
    },
    "projects": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "id": { "type": "string" },
          "name": { "type": "string" },
          "description": { "type": "string" },
          "technologies": { "type": "array", "items": { "type": "string" } }
        }
      }
    },
    "confidence": {
      "type": "object",
      "properties": {
        "overall": { "type": "number", "minimum": 0, "maximum": 1 },
        "workExperience": { "type": "number", "minimum": 0, "maximum": 1 },
        "education": { "type": "number", "minimum": 0, "maximum": 1 },
        "skills": { "type": "number", "minimum": 0, "maximum": 1 }
      }
    }
  }
}
```

Note: fields use `["string", "null"]` rather than omitting unknown fields — an explicit `null` is distinguishable from "the parser never looked at this," which matters when confidence scoring and evidence gating depend on knowing whether a field was genuinely absent from the CV versus not yet processed.

## 6. JSON schema: structured job post profile

The `structured_json` stored in `job_post_profiles`:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "jobTitle": { "type": ["string", "null"] },
    "employer": { "type": ["string", "null"] },
    "location": { "type": ["string", "null"] },
    "requiredSkills": { "type": "array", "items": { "type": "string" } },
    "preferredSkills": { "type": "array", "items": { "type": "string" } },
    "responsibilities": { "type": "array", "items": { "type": "string" } },
    "qualifications": { "type": "array", "items": { "type": "string" } },
    "keywords": { "type": "array", "items": { "type": "string" } },
    "seniority": {
      "type": ["string", "null"],
      "enum": ["Junior", "Mid", "Senior", "Lead", "Principal", null]
    }
  }
}
```

`seniority` is nullable and only populated when the source wording actually supports the distinction — inferring seniority from title conventions alone risks the same kind of unsupported-inference problem the matching engine is built to avoid on the CV side.
