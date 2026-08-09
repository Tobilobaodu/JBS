# Test Plan

## Purpose

Validate the backend's parsing, matching, rewrite, and cover letter workflows, with particular weight on the non-fabrication guarantee: every generated claim must be evidence-bound, and unsupported requirements must be flagged, never papered over. A passing test suite that doesn't exercise this specifically hasn't actually validated the product's core promise.

## Test areas

### 1. Upload and validation
- Valid PDF, valid DOCX, invalid file type (e.g. `.txt`, `.jpg`), oversized file (over the configured limit), corrupted/unreadable file, empty file.
- Concurrent uploads from the same user.
- Concurrent uploads across different users — confirm no cross-user leakage in storage keys or processing job assignment.

### 2. Extraction and merge (Docling + Textract)
- Clean single-column digital PDF.
- Scanned/image-based PDF (OCR path via Textract).
- DOCX with complex formatting (tables, multiple columns, embedded images).
- Multi-page CV (3+ pages).
- Deliberately awkward layout (two-column, heavy table use) — confirm `structuralValidation.anomalyDetected` fires correctly and `anomalyDetail` is populated.
- A case where Docling and Textract disagree on a text block — confirm the merge layer resolves to the higher-confidence source and logs the disagreement in `merge_strategy_metadata`, rather than silently picking one.
- **Confidence score validity, not just presence** — confirm each parser's `confidence_score` actually tracks extraction quality: run the same parser against a clean, well-formatted CV and against a deliberately garbled or badly-corrupted one, and confirm the score is meaningfully lower for the second. A test that only checks `confidence_score is not None` or that it falls in `[0, 1]` does not catch a proxy heuristic standing in for real confidence — this exact failure mode (a length-based heuristic passing every type/range check while measuring the wrong thing) shipped once during this project's real implementation before being caught; see `02-architecture-overview.md` §4 for the full account. Test both parsers, since the risk applies to any future swapped-in implementation behind the `DocumentParser` interface, not just the current one.
- **Merge outcome sanity check tied to the above** — construct a case where one parser's extraction is genuinely much worse than the other's (e.g. one pass on a corrupted or partially-unreadable file, the other on the same file cleanly re-encoded) and confirm the merge layer's canonical text actually comes from the better pass. This is the end-to-end version of the confidence-validity test above: a correct-looking confidence score that still doesn't drive the merge decision correctly is its own separate failure mode worth catching independently.
- **Section-heading canonicalization** — a CV using non-standard heading text for a standard section (e.g. "Career History" instead of "Work Experience", "Areas of Expertise" instead of "Skills") — confirm it maps to the correct canonical `section_type` per the mapping table in `03-data-model.md`. A CV with a heading that doesn't match any canonical section — confirm it's stored as `section_type: unknown` with a low-confidence/review flag, not force-fitted into the closest-looking canonical section.
- **Duplicate sections** — a CV with the same section heading appearing twice (e.g. a template artifact producing two "Work Experience" headings) — confirm parsing either merges all entries correctly or flags the duplication for review, and does not silently drop one copy or double-count a single role as two positions.
- **Inconsistent job titles for the same apparent role** — a CV where the same employer/date range appears with a different job title in two places (e.g. a summary section and the detailed experience section disagree) — confirm this is either resolved with a clear precedence rule (and that rule is applied consistently, not per-CV guesswork) or flagged for review, not silently reconciled by picking whichever title happened to parse first.

### 3. Canonical profile versioning
- First parse of a CV produces `version_number = 1` and moves the `cv_profiles.current_version_id` pointer.
- Reprocessing the same CV produces a new version row without mutating the first.
- Profile hash is stable for identical input and changes when extraction output changes.
- A `match_run` created against version 1 still resolves its evidence correctly after the CV is reprocessed into version 2 — this directly tests the `cv_profile_version_id` foreign key fix in `03-data-model.md` §4 rule 2. This is a priority test, not a nice-to-have, given it was a real design bug caught during review.

### 4. Job post ingestion
- Valid URL, fetchable and parseable.
- Unfetchable URL (404, timeout, paywall/bot-blocked) → confirm `422` with the documented "paste the text instead" guidance, not a generic failure.
- Pasted text, minimum length boundary, well below minimum (should reject).
- Structuring correctly separates required vs. preferred criteria on a job post that clearly distinguishes them, and degrades gracefully (nulls, not guesses) on one that doesn't.

### 5. Match analysis
- All requirements clearly supported by CV content.
- Mixed: some supported, some partial, some unsupported — confirm counts in `summaryAnalysis` add up to `total_requirements`.
- A requirement genuinely absent from the CV → confirm `supportLevel: unsupported`, empty `sourceReferences`, and no fabricated evidence text.
- False-positive check: a requirement that superficially matches a keyword in the CV but isn't actually substantively supported (e.g. CV mentions "Docker" in a certifications list with no usage context vs. a job post requiring "production Docker experience") — confirm the matching engine doesn't over-credit surface keyword overlap as `supported`.
- **Contradictory evidence** — construct a test CV with conflicting employment dates for what looks like the same role (e.g. one section says 2021–2024, another mentions the same employer with 2020–2023), or inconsistent job titles across sections for what appears to be one position. Confirm the matching engine returns `supportLevel: contradictory` rather than picking one date/title silently or falling back to `unsupported` (which would lose the fact that evidence exists at all). Confirm `sourceReferences` holds both conflicting sources, and `warning` explains the conflict in a way a reviewer could act on.
- **Unclear evidence (low extraction confidence)** — construct a test CV where the relevant section extracted with deliberately low confidence (e.g. from a badly scanned or heavily columnar source that stresses the extraction pipeline per §2's layout tests). Confirm `supportLevel: unclear` is returned rather than the matching engine either asserting `supported` on shaky evidence or discarding it as `unsupported`.
- Confirm the §2 duplicate-sections case, once parsed, produces a sensible match result — either the merged/deduplicated entries are matched normally, or an unresolved duplication flag from parsing propagates through to a `contradictory` or `unclear` match result rather than silently disappearing between the parsing and matching stages.
- Confirm `contradictory` and `unclear` results are never used as generation evidence — this is the direct link to §6 below; a section 5 test that only checks the match result and doesn't verify §6 also refuses to build on it hasn't actually confirmed the guarantee holds end to end.

### 6. Tailored CV generation
- Draft uses only verified evidence — spot-check that every `tailored_cv_sections.content_text` claim traces to a real `cv_experience_items`/`cv_education_items`/`cv_skill_items` row via `evidence_references`.
- A section with no evidence available is omitted from the draft entirely, not filled with a vague or invented placeholder.
- Regeneration with revised instructions produces a new version, and the old version remains retrievable.
- Attempt to construct a scenario that would tempt fabrication (e.g. instructing "emphasise leadership" when the CV has thin leadership evidence) and confirm the system reweights/rewords existing evidence rather than inventing new claims.
- Feed a match result containing a `contradictory` support-level item (from §5's conflicting-dates test case) into generation — confirm the draft either omits the affected claim entirely or surfaces it as needing the user's resolution, and never silently resolves the conflict by picking one of the two conflicting values on its own.
- Feed a match result containing an `unclear` support-level item into generation — confirm the same omit-or-flag behaviour, distinct from how a genuinely `unsupported` item is handled (§7's cover-letter question flow is the intended path for `unsupported`; `unclear` more often means the source document needs re-review, not a user question, so confirm the system doesn't conflate the two remediation paths).
- Every `tailored_cv_sections` row produced during these tests has `generation_task`, `prompt_version`, and `model_id` populated — confirm this from Phase 3 onward, since these fields are meant to exist from the first working version, not be backfilled later once something needs debugging (`03-data-model.md`, `tailored_cv_sections`).

### 7. Cover letter workflow
- Question generation produces relevant questions given a CV/job-post pair with an evidence gap (this is the intended mechanism for closing gaps without fabrication).
- Answers are correctly stored and attributable (`cover_letter_answers.question_id` resolves back to the right question).
- Draft generation incorporates submitted answers into `evidence_references`, not just into prose without a traceable link.
- Regeneration after a new answer reflects the new answer in the output.
- A required question left unanswered is handled explicitly (block progression, or generate with a visible gap) rather than silently proceeding as if it were answered.

### 8. Export flow
- Export attempted against an unapproved draft → rejected with `409`.
- Export attempted against an approved draft → succeeds.
- Application-pack export requires both the CV draft and cover letter to be approved — confirm partial approval is rejected, not partially exported.

### 9. Security and access control
This section is the summary; `10-security-plan.md` is the authoritative source for security test cases and should be run as part of this test plan, not treated as a separate pen-test-only activity. Specifically:
- Authentication required on every endpoint except register/login — see `10-security-plan.md` §1 for the full auth test list (rate limiting, enumeration, token expiry/revocation).
- A user cannot read, modify, or delete another user's CV, job post, match, draft, or workflow — test this explicitly per entity type, not just once generically. See `10-security-plan.md` §3 for the full IDOR test pattern, which should run as an automated, parametrized suite against every ID-scoped endpoint in `05-openapi.yaml`.
- File upload: malicious file content, resource-exhaustion payloads, path traversal in filenames — see `10-security-plan.md` §2.
- Job post URL ingestion: SSRF probes against internal/metadata addresses and redirect chains — see `10-security-plan.md` §4.
- Prompt injection via CV or job post content — see `10-security-plan.md` §5, and note this overlaps directly with the non-fabrication tests in §6 above: an injection attempt that produces a false claim with a passing evidence reference is the critical failure mode, not injection alone.
- Deletion actually removes the record and derived data (not just a `deleted_at` flag) where the retention policy calls for hard deletion.
- Every security-relevant action (upload, login, export, deletion, admin access) produces an `audit_events` row, and the alerting patterns in `10-security-plan.md` §10 actually fire when simulated.

### 10. Negative and edge cases
- Empty request bodies where a body is required.
- Missing required fields.
- Invalid URLs (malformed, not just unfetchable).
- Oversized payloads.
- Malformed JSON in request bodies.
- Rate limit exceeded → `429` with a clear retry signal.

### 11. Performance testing
- Single-user baseline timing against the targets in `08-deployment-guide.md` §10.
- Multiple concurrent users through the full pipeline.
- Large documents (multi-page, image-heavy) through extraction.
- Queue backlog behaviour: confirm jobs don't get dropped under load, and that queue depth alerts (§9 of the deployment guide) would actually fire at the configured threshold.

### 12. Cost tracking
- Textract usage is logged per call and aggregable to a daily figure.
- LLM token usage is logged per generation call, broken out by generation type (CV draft vs. cover letter).
- Prompt cache hit rate is measurable — this is the main lever on LLM cost per `02-architecture-overview.md` §6, so confirm it's actually being exercised, not just implemented and unused.

### 13. Product extensions (see `11-product-extensions.md`)
- **ATS structural validation (#1):** a CV with a genuinely clean, ATS-friendly layout scores high; a CV with a known-hostile pattern (two-column layout, text-in-image, contact info in a header) scores low on the specific corresponding check, not just a vague overall penalty. Confirm `overallScore` is a deterministic function of `checks` (same input CV always produces the same score) — this is a rules-based check, not a model call, so non-determinism here would indicate an implementation bug, not expected model variance. Confirm the check runs independently of job post data (no job post required to trigger it).
- **Coverage reporting (#2):** a collection of job posts with a genuinely recurring gap (the same missing skill across most posts) produces that gap ranked at or near the top of `aggregateGaps`; a requirement that appears in only one post out of many doesn't get inflated by the clustering step. Confirm a `coverage_report` never triggers new matching logic — verify it only reads existing `match_runs` and doesn't silently create new ones with different matching behaviour than a standalone `POST /matches` call would produce.
- **Fix-it checklist (#3):** confirm `improvementChecklist` entries never contain suggestion text implying the user has experience beyond what's in their CV — this is a direct extension of the non-fabrication tests in §6, applied to a different output surface. Confirm suggestion text is template-derived and traceable to a fixed set of templates keyed by `supportLevel`/`requirementType`, not free-form per-item generation, unless that's been deliberately upgraded with its own schema validation per the design note in `11-product-extensions.md` §3.
- **Schema-only extensions (#4, #5):** confirm `cv_profile_versions.master_profile_id` and `match_evidence_items.user_feedback` exist, are nullable, and default to null/unused without breaking any existing Phase 1–4 functionality — these columns should have zero behavioural effect until their features are actually built.

## Exit criteria

- All critical-path tests pass (upload → extraction → parse → match → generate → approve → export, end to end).
- No test scenario produces an unsupported claim rendered as fact in a draft — this is the single non-negotiable exit gate, and it now explicitly extends to `improvementChecklist` suggestion text per §13, not just CV/cover-letter body content.
- Cross-user access control tests pass with no exceptions.
- Performance stays within the targets in `08-deployment-guide.md` §10, or targets are explicitly revised with sign-off if real measurements diverge.
- Error handling covers every edge case listed above with a meaningful response, not a generic 500.
- Profile-versioning integrity test (§3, reprocess-then-resolve-old-match) passes specifically — flagged separately because it's the one most likely to regress silently if someone "simplifies" the schema later.
- The concrete "hardened" bar in `10-security-plan.md` §14 is met before this system handles real user data at scale — this test plan's §9 covers the functional security tests, but §14 also requires the gaps in `10-security-plan.md` §13 to be resolved or explicitly risk-accepted, and at least one incident response tabletop to have been run. Passing this test plan is necessary but not sufficient on its own for that bar.
- If product extensions #1–#3 are in scope for the release being tested, §13's tests pass; if they're deferred, confirm their absence doesn't degrade any core-pack functionality (e.g. `improvementChecklist` being null shouldn't break `GET /tailored-cvs/{draftId}` for any consumer).
