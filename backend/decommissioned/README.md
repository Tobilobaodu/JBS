# Decommissioned — extraction pipeline v1 (steps 3–6)

Nothing here is deleted and nothing here is imported by the running system.
This directory holds the previous extraction pipeline verbatim so it can be
read, diffed, or restored.

## What was decommissioned

| Step | What it did | Moved to |
|---|---|---|
| 3 | Docling first-pass extraction | `extraction_v1/step3_docling_task.py`, `extraction_v1/step3_docling_parser.py` |
| 4 | AWS Textract OCR second pass | `extraction_v1/step4_textract_task.py` |
| 5 | Merge + cross-parser structural validation | `extraction_v1/step5_merge_task.py`, `extraction_v1/step5_merge.py` |
| 6 | `cv_parse` → structured profile | `extraction_v1/step6_cv_parse_task.py` |

Also commented out rather than deleted, in place:

- `docker-compose.yml` — the `worker_docling`, `worker_textract`, `worker_merge`
  and `worker_cv_parse` service definitions.
- `Dockerfile` — the Docling model warm-up `RUN python -c "..."` block. It was
  also failing on the current base image (`ImportError: libxcb.so.1`), which
  blocked every backend image build.
- `app/workers/tasks.py` — `enqueue_textract_extract`, `enqueue_merge_parse`,
  `enqueue_cv_parse`.
- `app/core/config.py` — `textract_enabled` is kept as a field so existing
  `.env` files don't fail validation. Nothing reads it.

## What replaced them

A single step: `process_text_extract` (queue `text_extract`), which POSTs the
uploaded bytes to the `extraction` service and writes `cv_raw_text`.

The `extraction` service hosts **Example's step 2 unchanged**. These files are
byte-identical copies from `Example/artifacts/api-server/`:

```
extraction-service/src/routes/extract.ts      <- verbatim (the actual step 2)
extraction-service/src/app.ts                 <- verbatim
extraction-service/src/index.ts               <- verbatim
extraction-service/src/lib/logger.ts          <- verbatim
extraction-service/build.mjs                  <- verbatim
```

Four files had to be authored, because Example's originals depend on its pnpm
workspace and could not be copied as-is:

- `extraction-service/src/routes/index.ts` — Example's version also mounts
  `resume.ts` (the LLM rewrite route), which is not step 2. This mounts only
  the extract route.
- `extraction-service/package.json` — Example's has `workspace:*` dependencies
  (`@workspace/api-zod`, `@workspace/db`) that don't exist outside its monorepo.
  Dependency **versions are unchanged** from Example's.
- `extraction-service/tsconfig.json` — Example's `extends` a workspace base
  config and declares project references to `lib/db` and `lib/api-zod`. The
  compiler options here are copied from `Example/tsconfig.base.json` verbatim.
- `extraction-service/Dockerfile` — Example runs on Replit, so it had none.

`Example/artifacts/api-server/src/routes/health.ts` was deliberately **not**
copied: it imports `@workspace/api-zod`, which belongs to Example's OpenAPI
codegen chain rather than to step 2.

`npm install` runs with `--legacy-peer-deps` to reproduce Example's
`.npmrc` (`strict-peer-dependencies=false`). `esbuild-plugin-pino` declares a
peer range of esbuild `<=0.25.8` while Example pins `0.27.3`; pnpm tolerates
this, npm does not. Both versions are Example's own.

## Verified behaviour

Run against `Test Cvs/Tobiloba_Odu_CV.pdf` after the swap:

```
upload:          202
job:             text_extract completed in 2.0s
raw-text:        200, 6492 chars, ocrUsed=false
parsed-profile:  404  (expected — see below)
```

Extraction is **2 seconds**, against ~25 s for the Docling + Textract pair.
Output is token-identical to Example's own (892 words both). The 36 character
differences all favour the container: the Linux `pdftotext` preserves `–`,
`’` and `•`, where the Windows host build emitted `U+FFFD` for each. Bullet
glyphs surviving is a real gain — the decommissioned Textract path dropped
them entirely.

## What is now broken

Step 6 produced `cv_profile_versions.structured_payload` and `cv_skill_items`.
Nothing produces them any more, so `GET /cvs/{id}/parsed-profile` returns 404
and every consumer of a structured profile has no input:

| Consumer | Reads | Status |
|---|---|---|
| `app/extraction/match_engine.py` | `structured_payload`, `cv_skill_items` | no input |
| `app/api/v1/matches.py` | `CvProfileVersion` | cannot create a match |
| `app/services/cover_letter.py` | `cv_skill_items` | no input |
| `app/extraction/ats_check.py` | `structured_payload` | degraded |
| `app/api/v1/coverage.py` | `CvProfileVersion` | no input |
| `app/services/export_rendering.py` | `structured_payload` | no input |
| `app/services/trial_session.py` | `CvProfileVersion` | no input |

This is inherent to the swap, not an oversight. Example's step 2 returns a
flat string; it has no structured-profile equivalent, because Example's
matching is an LLM reading prose rather than a matcher reading fields.

Two ways forward, whenever you want to pick one:

1. **Restore step 6 only.** `process_cv_parse` reads
   `cv_raw_text.canonical_text` and nothing else, so it works unmodified on
   the new extractor's output. Move `step6_cv_parse_task.py` back into
   `app/workers/worker_jobs.py`, re-add `enqueue_cv_parse`, uncomment the
   `worker_cv_parse` service, and chain it from `process_text_extract`. This
   restores every consumer above while keeping steps 3–5 decommissioned — and
   the new extractor preserves the `•` markers that could fix the bullet
   over-collection documented in `CV matching fix/`.
2. **Replace matching Example-style.** Feed `canonical_text` and the job
   description to an LLM and drop the structured profile permanently. Faster
   and better at prose, but it gives up evidence provenance, determinism and
   the contradiction detection that `match_engine` provides.

## Restoring the old pipeline

1. Move the four `extraction_v1/step*_task.py` bodies back into
   `app/workers/worker_jobs.py`, and `step3_docling_parser.py` /
   `step5_merge.py` back to `app/extraction/`.
2. Uncomment the enqueue helpers in `app/workers/tasks.py`.
3. In `app/services/orchestration.py`, point `start_extraction_pipeline` at
   `docling_extract` and restore the chained dispatch branches.
4. Uncomment the four worker services in `docker-compose.yml` and the Docling
   warm-up in `Dockerfile` (which needs `libxcb1` added to its `apt-get`
   line to build on the current base image).
5. Re-add the four job types to `_KNOWN_JOB_TYPES` in `app/main.py`.

---

# Step 10 replacement — single-call resume rewrite

Added alongside the extraction swap. `POST /api/v1/resume-rewrites` sends the
CV's extracted text and the job post to the model together in one call; the
model does its own requirement extraction, so steps 7-9 are bypassed
entirely for this flow.

- `app/prompts/resume_rewrite_prompts.py` — author-supplied prompt, v1, with
  two corrections recorded in `RESUME_REWRITE_PROMPT_CHANGELOG`.
- `app/services/resume_rewrite.py` — one `generate_structured` call.
  Synchronous and stateless: no Celery job, no DB row, no migration.
- `app/api/v1/resume_rewrites.py` — the route.

Match-engine output is deliberately **not** fed into the prompt. Verified
against a real CV: the current job-post parser marks requirements as
unsupported that the CV plainly evidences (WCAG 2.1, design systems, UX
research). Passing those in as authoritative context makes the model
suppress genuine strengths, which is worse than sending nothing.

`GET /cvs/{id}/raw-text` was widened from `get_current_user` to
`get_current_user_or_trial_session`, because the tailor page shows the
extracted text back to the user before analysis and a first-time visitor
only has a trial session. Still scoped by `identity_owner_filter`; the IDOR
matrix (85 tests) passes unchanged.

## Tests moved here

These assert behaviour that no longer exists. Not collected by `pytest tests/`.

| File | Why |
|---|---|
| `tests_v1/test_confidence_and_merge.py` | `_compute_confidence` (step 3) and `merge_extractions` (step 5) |
| `tests_v1/test_pipeline_stage_transitions.py` | asserts the docling→textract→merge→cv_parse handoffs |
| `tests_v1/test_worker_jobs_cv_parse_new_sections_live.py` | step 6 |
| `tests_v1/test_worker_jobs_experience_split.py` | step 6 helpers |
| `tests_v1/test_worker_jobs_education_cert_project_split.py` | step 6 helpers |
| `tests_v1/test_worker_jobs_header_block.py` | step 6 helpers |
| `tests_v1/test_docling_convert_timeout.py` | split out of `tests/test_file_upload_security.py`; the rest of that file (magic bytes, storage keys, EICAR/ClamAV) still runs |
| `tests_v1/test_regression_full_chain.py` | waits for `cv_files.status == "parsed"`, which only step 6 ever set |

After the moves: **538 passed, 1 skipped** on the backend suite, and
**79 passed** on the frontend suite.
