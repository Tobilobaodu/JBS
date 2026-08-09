# API Reference

Human-readable index of the API surface. See `05-openapi.yaml` for the machine-readable spec with request/response schemas, and `03-data-model.md` for the field-by-field database schema (column types, indexes, constraints) that backs every entity referenced below — this document indexes endpoints and behaviour, it doesn't restate table structure.

Base path: `/api/v1`. All endpoints except `auth/register` and `auth/login` require authentication.

## Design rules

- **Upload/submission endpoints are synchronous for acceptance only.** They validate input, persist it, enqueue a background job, and return immediately with a job/entity ID. They never block on OCR, parsing, matching, or generation.
- **Every endpoint that triggers AI output returns an identifier, not a result.** The frontend polls `GET /jobs/{jobId}` or fetches the draft/entity endpoint directly once status flips to complete.
- **No export runs against an unapproved draft.** Export endpoints check `status = approved` server-side before generating output — this is not a frontend-only check.

## Authentication

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/auth/register` | Create user account |
| POST | `/auth/login` | Authenticate, issue session/token |
| POST | `/auth/logout` | End session |
| GET | `/auth/me` | Current user profile and permissions |

## CV upload and parsing

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/cvs` | Upload CV file, validate, store, create processing job |
| GET | `/cvs` | List uploaded CVs for current user |
| GET | `/cvs/{cvId}` | CV metadata and latest processing state |
| GET | `/cvs/{cvId}/raw-text` | Canonical merged extracted text |
| GET | `/cvs/{cvId}/extraction-detail` | Docling output, Textract output, completeness metadata |
| GET | `/cvs/{cvId}/parsed-profile` | Structured candidate profile (current version) |
| POST | `/cvs/{cvId}/reprocess` | Re-trigger extraction/parsing pipeline |
| DELETE | `/cvs/{cvId}` | Delete CV and derived records, subject to retention policy |
| POST | `/cvs/{cvId}/ats-check` | Run ATS structural-readability check — product extension, see `11-product-extensions.md` §1 |
| GET | `/cvs/{cvId}/ats-check` | Retrieve the latest ATS readiness result |

## Job post ingestion

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/job-posts/url` | Submit job post URL for fetch + structuring |
| POST | `/job-posts/text` | Submit pasted job post text for structuring |
| GET | `/job-posts` | List job posts for current user |
| GET | `/job-posts/{jobPostId}` | Raw and structured job post data |
| POST | `/job-posts/{jobPostId}/reprocess` | Re-run structuring logic |

## Multi-job-post coverage (product extension, see `11-product-extensions.md` §2)

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/job-post-collections` | Create a named collection of job posts |
| GET | `/job-post-collections` | List collections for current user |
| POST | `/job-post-collections/{collectionId}/coverage-report` | Run an aggregated gap report for a CV against every post in the collection |
| GET | `/coverage-reports/{reportId}` | Retrieve an aggregated coverage report |

## Matching and tailoring

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/matches` | Create match analysis between a CV profile and a job post |
| GET | `/matches/{matchId}` | Match analysis and evidence flags |
| POST | `/matches/{matchId}/tailored-cv` | Generate tailored CV draft from match result |
| GET | `/tailored-cvs/{draftId}` | Retrieve a tailored CV draft |
| POST | `/tailored-cvs/{draftId}/regenerate` | Regenerate with revised instructions/approved changes |
| POST | `/tailored-cvs/{draftId}/approve` | Mark draft approved for export |

## Cover letter workflow

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/cover-letters/start` | Start guided workflow from CV + job post |
| GET | `/cover-letters/{workflowId}/questions` | Next question set |
| POST | `/cover-letters/{workflowId}/answers` | Submit answers for active step |
| GET | `/cover-letters/{workflowId}/draft` | Current cover letter draft |
| POST | `/cover-letters/{workflowId}/regenerate` | Regenerate after new answers/edits |
| POST | `/cover-letters/{workflowId}/approve` | Mark letter approved for export |

## Jobs, audit, exports

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/jobs/{jobId}` | Async processing job status |
| GET | `/audit/{entityType}/{entityId}` | Evidence links and generation history |
| POST | `/exports/cv/{draftId}` | Export package for approved CV draft |
| POST | `/exports/cover-letter/{workflowId}` | Export package for approved cover letter |
| POST | `/exports/application-pack` | Export approved CV + cover letter together |

## Status values (used across job/draft entities)

- **Processing job status:** `queued`, `processing`, `completed`, `failed`, `retrying`
- **Draft status:** `generated`, `user_edited`, `approved`, `archived`
- **Match evidence support level:** `supported`, `partially_supported`, `unsupported`, `contradictory`, `unclear` — see `03-data-model.md` for what each means and what's permitted in generated output for each

## Request headers

```
Authorization: Bearer {access_token}
Content-Type: application/json
Accept: application/json
```

## Pagination

`GET /cvs` and `GET /job-posts` accept `limit` (default 20, max 100) and `offset` (default 0) query parameters, and an optional `status` filter matching that entity's status enum. Responses wrap the array in a `{ items, total, limit, offset }` envelope — see `CvListResponse` and `JobPostListResponse` in `05-openapi.yaml`. Apply the same pattern to any future list endpoint rather than returning a bare array, so clients don't have to special-case pagination per resource.

## Error response format

Every non-2xx response uses this envelope (see the `Error` schema in `05-openapi.yaml`):

```json
{
  "status": 400,
  "code": "VALIDATION_ERROR",
  "message": "Invalid file type. Only PDF and DOCX are supported.",
  "timestamp": "2026-08-03T10:00:00Z",
  "path": "/api/v1/cvs",
  "details": {
    "field": "file",
    "reason": "unsupported_mime_type",
    "allowed": ["application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"]
  }
}
```

`details` is optional and endpoint-specific — populate it with whatever helps the caller correct the request; omit it when there's nothing further to add. `code` should be stable and machine-readable (safe for frontend `switch` statements), distinct from the human-readable `message`.

## Standard error codes

| Code | Meaning |
|---|---|
| `400` | Validation error |
| `401` | Unauthorized |
| `403` | Forbidden (authenticated, but not the resource owner) |
| `404` | Resource not found |
| `409` | Conflict (e.g. duplicate email, approving an already-archived draft) |
| `413` | Payload too large |
| `415` | Unsupported media type |
| `422` | Semantically invalid request the schema can't catch (e.g. an unfetchable job post URL) |
| `429` | Rate limit exceeded |
| `500` | Internal server error |
| `503` | Service unavailable |

## Error handling expectations

Every failure mode must return a meaningful status code and message — never a silent failure. In particular:

- Unfetchable job post URL → `422` with a clear message directing the user to paste the text instead (this is the documented fallback, not an edge case to handle ad hoc).
- Structural anomaly detected in CV extraction → job still completes, but the response includes a `completeness_flag`/`structuralValidation` block the frontend can surface, rather than failing outright.
- Schema validation failure on a generation call → retry once internally; if it fails again, the job status is `failed` with `last_error` populated, not a partial/guessed draft.
- File too large → `413`. Unsupported file type → `415`, not a generic `400` — the more specific code lets the frontend give a precise message without parsing `details`.
