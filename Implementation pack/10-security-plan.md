# Security Plan

## 0. How to read this document

This is not a claim that the system will be unbreakable. No document, control set, or team can promise that, and a plan that claims otherwise is the first sign it wasn't written by someone who's actually run an incident. What this document gives instead: every attack surface this specific system exposes, the controls that close it, how to verify the control actually works (not just that it exists), and what a real exploitation attempt looks like — so a developer can build defensively from day one instead of retrofitting security after a pen test finds it.

This extends `06-non-functional-requirements.md` §4 rather than replacing it. Read that first for the baseline (data classification, encryption, retention). This document goes deep on the areas that baseline only summarised: attack-surface-by-attack-surface controls, adversarial testing, and incident response mechanics.

**Structure per surface:** what the attacker sees → do's → don'ts → checks and balances (defense in depth, not a single control) → how to test it → what a successful exploit looks like on this system specifically.

**On "any attack":** the goal is to raise attacker cost and shrink blast radius so that when — not if — something is missed, it's caught fast, contained, and doesn't cascade. That's what "hardened" actually means in practice. Section 12 covers what happens when a control fails, because one will, eventually.

---

## 1. Authentication and session management

### Attack surface
`POST /auth/register`, `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`, and the bearer token used on every other endpoint. This is the front door — get in here and everything downstream is moot.

### Do
- Hash passwords with bcrypt (cost factor >= 12) or Argon2id. Never store or log a plaintext password, even transiently in an error message.
- Enforce a minimum password policy server-side (length >= 12, reject top-10k breached passwords via a service like HaveIBeenPwned's k-anonymity API) — don't rely on frontend validation alone, since the API is directly callable.
- Issue short-lived access tokens (per `JWT_EXPIRY=3600` in `08-deployment-guide.md`) with a separate, revocable refresh token stored server-side in `user_sessions`.
- Rate-limit `/auth/login` and `/auth/register` specifically, tighter than the general API rate limit — these are the endpoints credential-stuffing and brute-force tools target first.
- Invalidate all sessions on password change and on explicit logout (`revoked_at` populated, not just client-side token discard).
- Log every authentication event (success, failure, logout, token refresh) to `audit_events` with `actor_type: user`.

### Don't
- Don't return different error messages for "email not found" vs "wrong password" on login — this is a user enumeration vector. Return the same generic "invalid credentials" for both, at the same response latency (see checks below).
- Don't put PII, roles, or anything sensitive in the JWT payload beyond `user_id` and expiry — a JWT is base64, not encrypted, and will be decoded by anyone who has it.
- Don't trust `expiresIn`/`exp` claims from the client. Validate signature and expiry server-side on every request; never accept a client-asserted "still valid" flag.
- Don't allow unlimited password reset attempts, and don't leak whether an email exists via the password-reset flow either.
- Don't store refresh tokens in `localStorage` if a frontend team asks — that's an XSS-exfiltration risk; httpOnly cookies or equivalent are the frontend's responsibility to get right, but flag it if you see it, since a backend built assuming secure token storage is undermined by frontend choices.

### Checks and balances
- **Rate limiting** at the API gateway layer (coarse) *and* a stricter per-endpoint limit on `/auth/*` (fine) — two layers, because a gateway-wide limit tuned for normal API traffic is too loose for brute-force resistance.
- **Timing-safe comparison** for password verification (bcrypt/Argon2 libraries do this by default — don't hand-roll comparison logic).
- **Account lockout with backoff**, not permanent lockout (which becomes its own denial-of-service vector — an attacker locks out a real user by repeatedly failing their login). Exponential backoff per account plus a CAPTCHA-style challenge after N failures is more resilient than a hard lock.
- **Session anomaly detection**: log `ip_address`/`user_agent` per session (already in the `user_sessions` schema) and flag — don't silently block, flag for review — a token used from a materially different IP/geography in a short window.

### How to test
- Automated: script 50 login attempts against a single account within a minute; confirm rate limiting engages and the account isn't permanently locked afterward once the window clears.
- Manual: compare response time and body for a login with a valid email/wrong password vs. an invalid email — confirm no distinguishable difference.
- Automated: attempt to use an access token after its `exp` has passed; confirm `401`, not silent acceptance.
- Automated: attempt to use a refresh token after `revoked_at` is set (post-logout); confirm rejection.
- Manual: decode a real JWT (base64, not cryptographically) and confirm no PII beyond `user_id`/expiry is visible.

### What exploitation looks like here
An attacker scripts credential-stuffing against `/auth/login` using a leaked password list, using timing or error-message differences to first enumerate which emails are registered users, then brute-forcing weak passwords on confirmed accounts. Without rate limiting and enumeration protection, this is trivially automatable and yields full account takeover — including access to that user's uploaded CV (a rich source of PII: name, address, phone, employment history) and generated drafts.

---

## 2. File upload (CV ingestion)

### Attack surface
`POST /cvs` — accepts a multipart file upload (PDF/DOCX), stores it, and feeds it into the Docling and Textract extraction pipeline (`02-architecture-overview.md` §4). This is the single riskiest endpoint in the system: it's the one place an unauthenticated-in-spirit payload (a file, which can contain almost anything) enters infrastructure that then actively processes it with two different parsing engines.

### Do
- Validate file type by **content inspection (magic bytes), not just the declared `Content-Type` header or file extension** — both are trivially spoofable by an attacker renaming a file to look like a PDF.
- Enforce the size limit (`413` per `04-api-reference.md`) at the reverse proxy/gateway level *before* the file reaches application code, not only in application validation — this prevents a large-payload request from consuming worker resources just to get rejected.
- Store uploaded files with a generated, non-guessable storage key (`cv_files.storage_key`) — never derive it from the original filename, which may contain path traversal sequences (`../../etc/passwd`) or be attacker-controlled in ways that collide with other users' keys.
- Scan uploaded files for malware before they reach the Docling/Textract pipeline. This is a real gap in the current pack and should be added as an explicit Phase 1 task — see the gap note at the end of this section.
- Run Docling in a sandboxed, resource-limited worker (memory cap, CPU cap, execution timeout) since PDF/DOCX parsers are a well-documented source of parser-exploitation vulnerabilities (malformed structure triggering memory corruption or infinite loops — "zip bombs" are a known DOCX-specific variant, since DOCX is a zip container).
- Set a hard timeout on both extraction passes (`08-deployment-guide.md` §6 already specifies `docling_extract: 60000ms`, `textract_extract: 120000ms` — enforce these, don't let a hung parse hold a worker indefinitely).
- Strip or ignore embedded macros, scripts, or executable content in DOCX files at the parsing layer — Docling should be configured to extract text/structure only, never to execute document-embedded content.

### Don't
- Don't trust the client-reported `fileSize` or `mimeType` in the upload metadata for anything security-relevant — recompute and verify server-side.
- Don't process a file synchronously in the request path (already correctly avoided per the architecture's async design — worth stating as a security property too: a slow or hostile file can't hold an API request thread open).
- Don't render or execute any part of an uploaded file's content directly (e.g. never pipe extracted "HTML-looking" text from a CV into a page without escaping — see §5 on generated-content XSS).
- Don't allow re-upload of a file to overwrite another user's `storage_key` — confirm storage key generation can't collide across users even under concurrent load (see checks below).
- Don't skip the malware scan "because it's just a CV" — CV-themed malicious document delivery is a well-established phishing/malware vector in the wild precisely because CVs are one of the few document types organisations expect from strangers and open without hesitation.

### Checks and balances
- **Layered validation**: reverse proxy size limit -> magic-byte type check -> malware scan -> sandboxed parse. Any one layer failing doesn't expose the next.
- **Resource isolation**: extraction workers run in containers with hard memory/CPU limits and no outbound network access beyond what Textract's SDK requires (deny-by-default egress — see §4 for why this also matters for SSRF containment).
- **Immutable original retention**: keep the original uploaded file in object storage separately from all derived/extracted data (`03-data-model.md` §4 rule 4 already establishes this separation) — if extraction is later found to have been exploited, the original is available for forensic re-analysis without needing to ask the user to re-upload.
- **Per-user upload rate limiting**, separate from general API rate limiting — bounds how many files a single account can push through the (expensive) extraction pipeline in a given window, which is both a cost control and a resource-exhaustion control.

### How to test
- Upload a file with a `.pdf` extension and `Content-Type: application/pdf` header, but that is actually a different file type at the byte level — confirm rejection based on content inspection, not header trust.
- Upload a maliciously crafted PDF/DOCX designed to trigger parser resource exhaustion (a "zip bomb" DOCX is a good starting test case — small compressed size, enormous decompressed size) — confirm the worker's resource limits and timeout kill the job rather than exhausting host memory.
- Upload a filename containing path traversal sequences (`../../../etc/passwd.pdf`) — confirm the generated `storage_key` is unrelated to the filename and no path traversal occurs in storage.
- Upload two files concurrently from different accounts as fast as possible — confirm storage keys never collide (load-test this, don't just eyeball it once).
- Confirm a malware-scan integration is in place and actually blocks a known-bad test file (EICAR test file is the standard, safe way to verify this without using real malware).
- Confirm the extraction worker container has no outbound network access beyond the Textract endpoint — attempt an egress connection from inside a test worker and confirm it's blocked.

### What exploitation looks like here
Two distinct attack shapes on the same endpoint. First, a resource-exhaustion attack: an attacker uploads a small but maliciously structured DOCX/PDF designed to consume enormous memory or CPU during parsing — without sandboxing and timeouts, this degrades or takes down the extraction worker pool, denying service to every other user whose CV is queued behind it. Second, a malware-delivery attack: since this system is designed to actively parse and process uploaded documents (not just store them), a document exploiting a parser vulnerability in Docling or in whatever renders extracted content downstream could achieve code execution inside the worker environment — from which an attacker pivots toward the object storage credentials, database connection, or other workers reachable from that container. This is why worker sandboxing and egress restriction (§ above) matter as much as the malware scan itself: assume a bad file eventually gets through scanning, and make sure the blast radius of that failure is one contained worker, not the whole backend.

**Gap flagged for the implementation plan:** malware scanning isn't currently listed as a Phase 1 task in `07-first-sprint-tasks.md`. Given the analysis above, it should be added as a blocking task before `POST /cvs` goes anywhere near production traffic — see §13.

---

## 3. Authorization and cross-user data access

### Attack surface
Every endpoint scoped to `{cvId}`, `{jobPostId}`, `{matchId}`, `{draftId}`, `{workflowId}` — i.e. almost the entire API surface once past auth. The risk here is Insecure Direct Object Reference (IDOR): a valid, authenticated user supplying another user's resource ID.

### Do
- Scope **every** query touching user-owned data by `user_id` derived from the authenticated session — never from a client-supplied parameter. E.g. `SELECT * FROM cv_files WHERE id = :cvId AND user_id = :sessionUserId`, not `SELECT * FROM cv_files WHERE id = :cvId` followed by an application-layer ownership check.
- Return `404` (not `403`) when a resource exists but isn't owned by the requester, for most endpoints — this avoids confirming to an attacker that a given ID exists at all. (`403` is appropriate where existence is already implied by context, e.g. within a workflow the user is legitimately part of.)
- Apply this consistently across every entity relationship in `03-data-model.md` — `cv_files` -> `cv_profile_versions` -> `match_runs` -> `tailored_cv_drafts` -> `cover_letter_workflows` is a deep chain, and ownership must be checked at the top of the chain and re-verified at each hop a request touches, not assumed to be transitive without verification.
- Use UUIDs (already the design, per every table's `id` column) rather than sequential integers for all resource identifiers — this doesn't replace authorization checks, but it does remove trivial ID-guessing as a reconnaissance shortcut.

### Don't
- Don't rely solely on "the ID is a random UUID so it's unguessable" as an access control. UUIDs prevent enumeration, not IDOR — once an attacker has *any* valid ID for another user's resource (leaked in a URL, a support screenshot, a log line, a referrer header), unenforced ownership checks mean full access.
- Don't check ownership in the route/middleware layer only and then run unscoped queries deeper in the service layer — the ownership check needs to be enforced at the data-access layer as the source of truth, with the route-layer check as a fast-fail convenience, not the reverse.
- Don't assume a child resource's ownership follows automatically from its parent existing. E.g. don't assume that because a `match_run_id` was validated once, every subsequent read of `match_evidence_items` under it is automatically safe — verify the chain each time, especially across cached/joined queries where it's easy to silently drop a `WHERE user_id = ...` clause during refactoring.

### Checks and balances
- **Defense in depth across three layers**: route-level session check -> service-level ownership verification -> data-access-level `user_id` scoping in the query itself. An IDOR bug typically means one layer was skipped; three independent layers mean one skip doesn't equal a breach.
- **Automated authorization tests as a CI gate**, not a manual QA pass — see testing below. This is the single highest-value automated security test for this system, because IDOR bugs are easy to introduce during normal feature work and easy to miss in manual review.
- **Audit logging on every access**, including denied access attempts (`actor_type: user`, with the denial reason) — a pattern of `403`/`404`s against sequential or clearly-not-owned resource IDs from one account is a strong IDOR-probing signal worth alerting on (see §10).

### How to test
- For every entity type (`cv`, `job_post`, `match`, `tailored_cv_draft`, `cover_letter_workflow`), create two test users, have user A create a resource, and confirm user B cannot read, modify, or delete it via any endpoint that references it by ID — including nested/child resources (e.g. user B requesting `GET /matches/{userA'sMatchId}/tailored-cv` or `POST /tailored-cvs/{userA'sDraftId}/approve`).
- Write this as a parametrized automated test suite that runs against every ID-scoped endpoint in `05-openapi.yaml`, not a handful of spot checks — the OpenAPI spec itself is a checklist of every endpoint this needs covering.
- Specifically test the deep chain: user A's `cv_profile_version_id` feeding user A's `match_run`, then attempt to access `match_evidence_items` for that run as user B.
- Confirm the response code for cross-user access attempts is consistent (`404`, per the "don't confirm existence" guidance above) across all endpoints — an inconsistency (some return `403`, some `404`, some leak a `500` with a stack trace) is itself an information-disclosure bug worth fixing.

### What exploitation looks like here
An attacker with a legitimate account uploads their own CV to observe the `cvId` format, then — having obtained another user's `cvId` through any leakage channel (a shared support ticket, a browser history sync, a referrer header on an outbound link, or simply sequential/predictable patterns if UUIDs were ever weakened to something more guessable) — calls `GET /cvs/{otherUsersCvId}/parsed-profile` directly. If ownership isn't enforced at the data layer, this returns another person's full name, contact details, and employment history without ever needing their password. Worse: if `POST /tailored-cvs/{draftId}/approve` or `POST /exports/*` aren't ownership-checked, an attacker could trigger actions on another user's account entirely, not just read their data.

---

## 4. Job post URL ingestion (SSRF)

### Attack surface
`POST /job-posts/url` — the backend fetches a user-supplied URL server-side (`03-data-model.md` `job_posts.source_url`). This is a textbook Server-Side Request Forgery surface: the attacker doesn't need to compromise anything, they just need to submit a URL and observe or infer what the server does with it.

### Do
- Resolve the URL's DNS and validate the resulting IP is a public, routable address **before** fetching — reject private ranges (RFC 1918: `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), loopback (`127.0.0.0/8`, `::1`), link-local (`169.254.0.0/16`, including the cloud metadata endpoint `169.254.169.254`), and any internal DNS names your infrastructure resolves.
- Re-validate after any redirect. A URL can pass initial validation as a public address and then redirect to an internal one — validate the resolved IP at every hop, not just the first.
- Enforce a strict allow-list of schemes (`http`, `https` only) — reject `file://`, `gopher://`, `ftp://`, `dict://`, and anything else. Scheme smuggling into internal services via unusual protocols is a documented SSRF escalation technique.
- Run the URL-fetch step from a network-isolated context with egress restricted to public internet only — no route to internal services, the database, the queue, or the cloud metadata service, regardless of what the application-layer validation says. This is the defense-in-depth layer for when the validation above has a bug.
- Enforce a fetch timeout and a maximum response size — an unbounded fetch is also a resource-exhaustion vector.
- Return the documented `422` (per `04-api-reference.md`) for any URL that fails validation or can't be fetched, with the existing guidance to paste the text instead — this fallback already exists in the design and gives a clean, non-leaky failure path.

### Don't
- Don't rely on a blocklist of "known bad" hostnames or IPs — allow-list public-routable-only, since blocklists are always incomplete and attackers have many ways to encode an internal IP (decimal notation, hex, IPv6-mapped IPv4, DNS rebinding) that a naive string-based blocklist misses.
- Don't validate the URL string once at submission and then trust it unchanged through to the actual fetch — validate at fetch time, immediately before the request goes out, since time-of-check/time-of-use gaps (including DNS rebinding between validation and fetch) are a known bypass.
- Don't return the raw fetched response body or headers back to the client on failure — an SSRF probe often uses response *content or timing differences* to map internal network topology even without full data exfiltration; a generic `422` message avoids handing back that oracle.
- Don't let the fetch happen from the same network context as the main API service or database — see the isolation point above.

### Checks and balances
- **Two independent layers**: application-level IP/scheme validation *and* network-level egress restriction on the fetching service. If the validation logic has a bypass (and history shows SSRF filters frequently do), the network layer is the backstop.
- **Redirect-chain validation**, not just initial-URL validation — explicitly test this, since it's the most common way naive SSRF protections get bypassed in the wild.
- **Response size and timeout caps**, monitored — a job-post fetch that's unusually slow or large is worth flagging (see §10), since it may indicate probing behaviour.

### How to test
- Submit `http://169.254.169.254/latest/meta-data/` (or your cloud provider's equivalent metadata endpoint) as a job post URL — confirm rejection, and confirm no request actually leaves toward that address at the network layer (verify via network monitoring on the fetch worker, not just the application response).
- Submit a URL pointing to an internal service by IP (`http://10.0.0.5/`) and by internal DNS name if your infrastructure has any — confirm both are rejected.
- Submit a public URL that redirects to an internal address — confirm the redirect target is validated and rejected, not silently followed.
- Submit a URL using decimal or hex IP encoding for a private address — confirm the resolved address is still caught.
- Submit a URL to a slow-responding or very large endpoint — confirm the timeout and size cap engage rather than the worker hanging or exhausting memory.
- Confirm, via infrastructure configuration review (not just application testing), that the worker process handling this fetch has no network route to internal services regardless of what application code does.

### What exploitation looks like here
An attacker submits the cloud metadata endpoint as a "job post URL." If the endpoint naively fetches any HTTP(S) URL and returns the content (even indirectly, e.g. reflected into the "structuring failed, here's what we got" error path, or observable via response timing), this is a direct path to cloud IAM credentials — which, depending on the worker's IAM role, could mean access to the S3 bucket holding every user's uploaded CV, or worse. This is one of the most consequential single-endpoint vulnerabilities possible in a cloud-hosted system, and it's specifically relevant here because "fetch an arbitrary user-supplied URL" is a core, intentional feature of this product — it can't just be disabled, it has to be built safely from the start.

---

## 5. LLM / AI generation pipeline (prompt injection and output handling)

### Attack surface
Everything downstream of extracted CV text and job post text reaching an LLM call: matching (`POST /matches`), tailored CV generation (`POST /matches/{matchId}/tailored-cv`), and cover letter generation (`POST /cover-letters/{workflowId}/answers` -> draft). The attacker-controlled input here is unusually rich: a CV is a whole document the user fully controls the content of, and a job post URL fetches content from a third party the *submitting* user doesn't even control — meaning injection can come from someone who isn't the account holder at all.

### Do
- Treat all extracted CV text and job post text as **untrusted input to the LLM call**, even though it's the user's "own data" — the non-fabrication schema-validation design already in `02-architecture-overview.md` §6 is the primary defense here, and it should be understood explicitly as a prompt-injection defense, not just a hallucination defense. Keep leaning on it.
- Use structural separation between instructions and data in every prompt — system/instruction content and user-supplied CV/job-post content should be in clearly delineated, non-mergeable positions (e.g. distinct message roles if the provider supports them, or an unambiguous, injection-resistant delimiter scheme if not) so injected text in a CV can't be interpreted as a new instruction.
- Validate every model response against its schema before it touches the database or reaches a user (already required per `02-architecture-overview.md` §6) — this is what stops a successful prompt injection from actually producing an out-of-band result, even if the injection attempt itself "worked" against the model.
- Sanitize/escape any model-generated or extracted text before it's ever rendered in a context that interprets markup (frontend's responsibility primarily, but the API should not assume the frontend will always get this right — consider escaping at the API boundary too for defense in depth).
- Log the actual prompt and response for every generation call (already implied by `audit_events`/`generationHistory` in the design) — this is what makes a suspected injection attempt investigable after the fact.
- Apply the same non-fabrication evidence-binding validation to cover letter answers as to CV content — a malicious or careless answer submitted through the guided workflow is just as much untrusted input as the CV itself.

### Don't
- Don't concatenate raw extracted CV text directly into a prompt template without the compact, scoped context-building step already specified in `02-architecture-overview.md` §6 — that step is a cost control as designed, but it's also a security control: a smaller, structured, scoped context is much harder to successfully inject against than a full raw document dumped wholesale into a prompt.
- Don't assume a job post fetched from a URL is "just data" because it came from ingestion, not upload — remember the URL is submitted by the *user*, but its *content* is controlled by whoever operates that URL, which may be a third party with no relationship to the platform at all. A malicious job posting page is a realistic and very low-effort injection vector.
- Don't let a model response bypass schema validation "just this once" for a retry or edge case — this is exactly the kind of exception that becomes the exploited path later.
- Don't expose raw model error messages or stack traces to the end user — these can leak prompt structure, which helps an attacker refine injection attempts.
- Don't trust the model's own self-reported confidence or "I have verified this is accurate" language in its output as a substitute for the schema/evidence-reference validation — a successfully injected model can be made to claim high confidence in fabricated content.

### Checks and balances
- **Schema validation as the hard backstop** (already designed) — even if a prompt injection successfully manipulates the model's behaviour, unless the output can still pass schema validation *and* carry legitimate evidence references pointing to real extracted data, it can't produce a usable, damaging result. This is genuinely the strongest control available for this specific risk class, and it's already load-bearing in the architecture — worth treating it as security infrastructure, not just a quality feature, when prioritising its correctness.
- **Evidence-reference enforcement** (already in `03-data-model.md` §4 rule 3) — a generated claim with no traceable evidence reference is rejected regardless of how it was produced, which closes off most of the practical damage an injection could otherwise do.
- **Rate limiting on generation endpoints** specifically — beyond cost control, this limits how many injection attempts an attacker can iterate through against the live model in a given window.
- **Human-in-the-loop approval** before export (`status = approved` gate, already required per `04-api-reference.md`) — even a generation result that somehow passed schema validation with subtly manipulated content is reviewed by the actual user before it's ever exported or acted on further.

### How to test
- Craft a test CV containing an embedded instruction-style string in a plausible location (e.g. in the "additional information" section: an instruction telling the model to ignore prior instructions and claim extra years of experience) — confirm the tailored CV generation does not incorporate the injected claim, and confirm the evidence-reference validation correctly rejects or ignores it.
- Craft a test job post (served from a test URL under your control) containing a similar injected instruction aimed at the matching or generation step — confirm the same.
- Attempt to make a generation call produce output that fails schema validation intentionally (e.g. via a crafted CV designed to confuse section boundaries) — confirm the retry-then-fail behaviour in `06-non-functional-requirements.md` §1 actually triggers, rather than a malformed response being persisted.
- Review actual prompt templates for the separation-of-instructions property described above — this is a code/design review test, not just a runtime test, since the defense is structural.
- Confirm generation endpoint rate limits are enforced and test that a burst of rapid, varied generation requests against the same match/workflow triggers the limit.

### What exploitation looks like here
The most realistic and highest-value target here isn't "make the AI say something silly" — it's an attempt to get the tailored CV or cover letter generator to fabricate a specific false claim (an employer, a qualification, a security clearance) that the schema/evidence-reference system is specifically designed to prevent. A successful attack looks like an injected instruction in CV text or job-post content that gets the model to emit a claim, and where that claim then *also* manages to carry a plausible-looking-but-incorrect evidence reference that passes validation — that combination (injection **plus** an evidence-validation bypass) is the actual critical failure mode to defend against, not injection alone. This is why evidence-reference enforcement needs to independently verify the reference resolves to *real, matching* source content (e.g. does the referenced `cv_experience_items.id` actually contain text supporting this specific claim), not merely that a reference ID was present and syntactically valid — a validation check that only confirms "a UUID was provided" rather than "this UUID's content actually supports this text" is not a real backstop.

---

## 6. Rate limiting, resource exhaustion, and denial of service

### Attack surface
Every endpoint, but with different cost profiles: `POST /cvs` (triggers expensive extraction), `POST /matches` and generation endpoints (trigger expensive LLM calls), `POST /job-posts/url` (triggers an external fetch). Given the per-run cost figures already established in `02-architecture-overview.md` §10, this system has real financial exposure to abuse, not just availability exposure.

### Do
- Apply tiered rate limits: a coarse general API limit (`RATE_LIMIT_REQUESTS`/`RATE_LIMIT_WINDOW` per `08-deployment-guide.md`) plus tighter, endpoint-specific limits on expensive operations (upload, match, generation, URL fetch) — a limit tuned for cheap `GET` requests is far too loose for endpoints that cost real money per call.
- Apply limits per-user (authenticated) and per-IP (pre-auth, e.g. on `/auth/register`) — per-user alone doesn't stop an attacker from registering many accounts to bypass it.
- Set and enforce the queue/worker concurrency limits already specified in `08-deployment-guide.md` §6 — these double as a DoS control, since they cap how much of the expensive pipeline can run concurrently regardless of how many requests are queued.
- Alert on queue depth (already specified in `08-deployment-guide.md` §9) — a sudden queue depth spike is an early signal of either legitimate viral growth or abuse, and the response differs, so it needs to be visible quickly either way.
- Cap request body size at the reverse proxy layer for every endpoint, not just file upload — a large JSON body to a text-based endpoint (e.g. an enormous pasted job post) is also a resource-exhaustion vector.

### Don't
- Don't rely on a single global rate limit as sufficient protection for cost-asymmetric endpoints — a limit that's reasonable for `GET /cvs` is not reasonable for `POST /matches/{matchId}/tailored-cv`.
- Don't let retry logic (already specified for schema-validation failures) retry indefinitely or without backoff — an internal retry storm during a provider outage is a self-inflicted DoS.
- Don't allow a single account to hold an unbounded number of concurrent in-flight processing jobs — cap concurrent active jobs per user, independent of the rate limit on new submissions.

### Checks and balances
- **Circuit breakers** on calls to Textract and the LLM provider — if either is failing or degraded, fail fast rather than queuing requests that will only time out later and hold worker capacity.
- **Cost alerting** (already specified in `08-deployment-guide.md` §9, with thresholds flagged as open decisions in `01-implementation-plan.md` §6) — this is a security control as much as a budget control, since a runaway cost spike is often the first visible signal of automated abuse.
- **Dead-letter queue** (already specified in `06-non-functional-requirements.md` §1) — ensures failed jobs are visible for investigation rather than silently retried forever or dropped, both of which mask abuse patterns.

### How to test
- Load-test each expensive endpoint independently to confirm its specific rate limit engages before the general API limit would, at the volume where cost/resource impact actually starts to matter.
- Simulate an account submitting the maximum allowed concurrent jobs, then attempting one more — confirm rejection rather than unbounded queuing.
- Simulate a provider (Textract or LLM) timeout/failure and confirm the circuit breaker engages rather than requests piling up in the queue.
- Confirm queue depth alerting fires at the configured threshold under a simulated backlog.

### What exploitation looks like here
An attacker scripts automated account creation (if registration isn't sufficiently rate-limited/CAPTCHA-protected) and then submits CVs and job posts in bulk purely to drive up Textract and LLM costs — this is a financially motivated denial-of-wallet attack rather than a traditional availability DoS, and it's realistic precisely because this system's core functionality is inherently expensive per-call. Without per-endpoint limits and concurrent-job caps, a modest number of automated accounts could generate a very large, fast-accumulating bill and simultaneously degrade service for legitimate users by saturating the worker queues.

---

## 7. Injection (SQL, NoSQL, command)

### Attack surface
Any query construction across the data model in `03-data-model.md`, and any point where extracted text or user input touches a shell command, file path, or dynamic query.

### Do
- Use parameterized queries / prepared statements exclusively, via an ORM or query builder that enforces this by default — never string-concatenate user input into SQL, including into `JSONB` field queries or array-containment queries (`source_pass_ids`, `evidence_references`, etc.), which are easy to overlook as "just JSON" and treat less carefully than plain columns.
- Validate and constrain any user input used in dynamic sort/filter parameters (e.g. the `status` filter on list endpoints) against an explicit allow-list of accepted values — never pass a query parameter directly into an `ORDER BY` or similar clause.
- If any shell command is ever invoked from application code (e.g. for a document-processing utility), pass arguments via an argument array, never through shell string interpolation — and prefer avoiding shell invocation entirely in favour of a library call where possible.

### Don't
- Don't build raw SQL strings anywhere in the codebase, even for "internal" admin tooling — internal tools get attacked too, often with less scrutiny than the public API.
- Don't trust that an ORM protects you automatically from every injection class — raw query escape hatches (most ORMs have one) need the same parameterization discipline as hand-written SQL.
- Don't pass extracted CV/job-post text into any file-system or shell operation without treating it as hostile — a CV that happens to contain shell metacharacters in, say, a "special characters in job title" edge case shouldn't be able to do anything if it ever ends up near a command invocation.

### Checks and balances
- **Static analysis / linting** in CI that flags raw SQL string construction or shell interpolation patterns — catch this class of bug before merge, not in a pen test.
- **Least-privilege database roles**: the application's DB user should not have permissions beyond what it needs (no `DROP`, no cross-schema access, no superuser) — limits the damage of a successful injection even if one occurs.
- **Code review checklist item** specifically for query construction on any PR touching the data-access layer.

### How to test
- Automated SQLi scanning (e.g. via a tool like sqlmap in a controlled test environment) against every endpoint accepting user input, particularly the `status` filter parameters and anything resembling a search/sort field.
- Manually attempt classic injection payloads in every text field, including CV upload metadata and job post pasted text — confirm no behavioural difference from a benign input.
- Review the codebase for any raw query construction as part of a security-focused code review pass before Phase 5 sign-off.

### What exploitation looks like here
Given the strong recommendation toward parameterized queries throughout this pack's data-access patterns, the more realistic injection risk on this system isn't classic SQLi against a well-built ORM layer — it's a filter/sort parameter that was hand-rolled outside the ORM's safe path (a common shortcut under time pressure) allowing an attacker to manipulate a query to return other users' data, which converges with the IDOR risk in §3. Test both together.

---

## 8. Cross-Site Scripting (XSS) and generated-content rendering

### Attack surface
Any point where user-supplied or model-generated text (CV content, job post content, tailored CV drafts, cover letter drafts) is later rendered in a browser context — primarily a frontend concern, but the API's response handling and content-type headers matter too.

### Do
- Set correct `Content-Type` headers on every API response (`application/json`) so browsers don't attempt content-type sniffing that could misinterpret a response as HTML.
- Set standard security headers at the API gateway: `X-Content-Type-Options: nosniff`, `Content-Security-Policy` (primarily a frontend concern but worth confirming exists), `X-Frame-Options` or equivalent.
- Treat every field that will eventually be rendered — extracted CV text, generated draft content, job post text — as needing output-encoding at render time, and flag this explicitly to whoever owns the frontend, since the backend can't fully control this but should document the expectation clearly (this is exactly the kind of interface assumption that gets missed between teams).

### Don't
- Don't assume "this is just text extracted from a CV" means it's safe to render unescaped — a CV is an attacker-controllable document, and there's no reason a "professional summary" field couldn't contain markup or script content if a malicious actor crafted one specifically to test this.
- Don't render any model-generated content as HTML/markdown without sanitization even though it "came from our own trusted generation pipeline" — the pipeline's input (CV/job-post text) is not trusted, per §5, so its output shouldn't be treated as trusted either.

### Checks and balances
- **Backend-side output encoding as defense in depth**, even though XSS is primarily preventable on the frontend — don't make this entirely someone else's problem when the API is the first point of contact with the untrusted content.
- **Content Security Policy** on the frontend as the backstop control that limits damage even if a sanitization gap exists.

### How to test
- Upload a CV with a script-injection style payload embedded in a text field (e.g. the professional summary) — confirm it's never reflected unescaped anywhere in an API response that a frontend might render directly, and confirm downstream draft generation doesn't reproduce it verbatim as executable markup.
- Confirm response headers include the security headers listed above.

### What exploitation looks like here
Since this system is explicitly designed to take user-controlled document content and eventually present it back (as extracted text, as match analysis, as generated drafts), a stored XSS payload embedded in a CV is a realistic vector if any point in that chain renders it unescaped — potentially affecting not just the uploading user but anyone who later views that content (e.g. a support agent reviewing a flagged account, if `03-data-model.md`'s implied admin/support access is ever built out).

---

## 9. Secrets and configuration management

### Attack surface
Environment variables, API keys (AWS, LLM provider), JWT signing secrets, database credentials — all listed explicitly in `08-deployment-guide.md` §5.

### Do
- Confirm every secret-shaped value in `08-deployment-guide.md` §5 comes from the managed secrets vault at deploy time in every real environment, exactly as that document already specifies — this section reinforces why, not just what.
- Rotate secrets on a defined schedule and immediately on suspected compromise or personnel change (anyone with prior access leaving the team).
- Use distinct credentials per environment (local/staging/production) — a staging leak should never expose production.
- Scope the AWS IAM role used by extraction workers to exactly what's needed (S3 read/write on the specific bucket, Textract call permissions) — nothing broader, per least-privilege already established in `06-non-functional-requirements.md` §4.

### Don't
- Don't commit `.env.local` or any file containing real secrets, ever — enforce this with a pre-commit hook and a `.gitignore` entry, not just a policy statement.
- Don't log secret values, even at debug level, even temporarily during development — a debug log line containing an API key has a way of surviving into production logging long after the "temporary" debugging is forgotten.
- Don't share one long-lived credential across all workers/services — scope credentials per service where the provider supports it, so a compromised worker doesn't hand over blanket access.

### Checks and balances
- **Automated secret-scanning in CI** (e.g. gitleaks or equivalent) on every commit, catching accidental secret commits before merge, not after.
- **Secrets vault audit logging** — know who/what accessed which secret and when, and alert on unexpected access patterns.

### How to test
- Run a secret-scanning tool against the full git history (not just the current state) before the repository is made available to any external developer, to confirm no historical commits leaked a real credential.
- Attempt to access a secret vault entry from a service/role that shouldn't have permission — confirm denial.
- Review IAM role definitions for the extraction workers and confirm they don't exceed the documented minimum need.

### What exploitation looks like here
A leaked AWS credential (via a committed `.env` file, a debug log shipped somewhere it shouldn't be, or a compromised worker with an over-scoped IAM role) gives an attacker direct access to the S3 bucket holding every user's original CV — bypassing the entire API-layer authorization model in §3 entirely, since object storage access doesn't go through the application's ownership checks at all. This is why credential scope matters as much as credential secrecy: even a "properly stored" credential that's too broadly scoped turns one worker compromise into a full data breach.

---

## 10. Monitoring, detection, and audit trail integrity

### Attack surface
This isn't a single endpoint — it's the question of whether an attack, once attempted, is actually noticed. `06-non-functional-requirements.md` §4 already establishes audit logging requirements; this section covers what to actually watch for.

### Do
- Alert on the patterns specific to the attacks above, not just generic error-rate thresholds: repeated `401`s from one IP (credential stuffing), repeated `404`s against sequentially-adjacent-looking IDs from one account (IDOR probing), unusual job-post-URL fetch targets or timing (SSRF probing), a spike in generation-job schema-validation failures (possible injection attempts), unusual queue depth or per-account job volume (abuse/DoS).
- Retain audit logs per the retention policy already established, and treat `audit_events` as forensic evidence — protect it against tampering (already specified as append-only) and back it up independently of the primary application data path.
- Correlate across log sources: an authentication anomaly plus an authorization anomaly on the same account in a short window is a stronger signal together than either alone.

### Don't
- Don't rely on manual log review as the primary detection mechanism — by the time someone happens to notice, the damage is often done. Alerting needs to be automated for anything time-sensitive.
- Don't let audit logs be the only record of a security-relevant event — where feasible, mirror critical security events (auth failures, authorization denials, admin access) to a separate, independently-secured logging destination, so a compromise of the primary database doesn't also erase the evidence of how it happened.

### Checks and balances
- **Alert thresholds tuned iteratively** — start with the patterns above, adjust based on real false-positive rates once Phase 1-2 traffic gives a baseline (same principle as the cost-threshold guidance already in `08-deployment-guide.md` §1).
- **Regular audit log review**, even with automated alerting in place — automated systems catch known patterns; periodic human review is what catches the pattern nobody thought to alert on yet.

### How to test
- Simulate each attack pattern in a test environment (repeated auth failures, IDOR probing pattern, SSRF probe attempt, injection attempt) and confirm the corresponding alert actually fires — an alert that's configured but never verified to trigger is not a real control.
- Confirm audit log entries are actually immutable in practice (attempt an update/delete against `audit_events` with an application-level credential and confirm it's rejected, not just documented as a policy).

### What exploitation looks like here
The failure mode here isn't a single exploited vulnerability — it's every control above working exactly as designed, an attack being logged correctly, and nobody finding out until a user reports something wrong weeks later, because no alert was configured to actually surface the pattern in the logs. Detection capability that exists on paper but was never tested to actually fire is, in practice, no detection capability at all.

---

## 11. Third-party and supply chain risk

### Attack surface
Dependencies (Python packages for the FastAPI/SQLAlchemy stack, and Docling's own dependency tree, which is non-trivial given its document-parsing libraries), the Textract SDK, the LLM provider SDK, and any base container images.

### Do
- Run automated dependency vulnerability scanning (e.g. `pip-audit`, Dependabot/Snyk, or `safety` for the Python ecosystem) in CI, blocking merge on new high/critical findings.
- Pin dependency versions (`requirements.txt` with hashes, or a lockfile-based tool such as Poetry/pip-tools) and review changes on update, particularly for anything in the extraction/parsing path (Docling and its own dependencies, PDF/DOCX parsing libraries) given the resource-exhaustion and parser-exploitation risks discussed in §2 — Docling's dependency surface is larger than average precisely because document parsing pulls in a lot of format-specific libraries, each a potential vulnerability source in its own right.
- Use minimal, regularly-rebuilt base container images for workers, and scan images for known vulnerabilities before deployment.
- Review the data-handling terms of the LLM and OCR providers (already flagged as a requirement in `06-non-functional-requirements.md` §4) — this is a supply-chain trust decision, not just a legal checkbox.

### Don't
- Don't pin dependencies once and never revisit — stale dependencies accumulate known, patched vulnerabilities that provide easy attacker entry points long after a fix exists.
- Don't grant CI/CD pipeline credentials broader access than needed to build and deploy — a compromised CI pipeline with excessive permissions is a supply-chain attack vector in its own right.

### Checks and balances
- **Automated scanning as a CI gate**, not a periodic manual task.
- **Documented process for emergency patching** when a critical vulnerability is disclosed in a core dependency (Docling, the web framework, the database driver) — know in advance how fast you can ship a patch, don't figure it out during the incident.

### How to test
- Confirm the CI pipeline actually blocks a merge when a scanning tool reports a high/critical vulnerability (test with a deliberately outdated, vulnerable test dependency in a branch).
- Periodically (quarterly minimum) review all direct dependencies for maintenance status — an unmaintained library in the document-parsing path is a standing risk given how attractive that surface is (§2).

### What exploitation looks like here
A known, publicly disclosed vulnerability in a PDF/DOCX parsing dependency (these are disclosed with some regularity, precisely because document parsers are complex and widely used) goes unpatched because dependency scanning wasn't wired into CI — an attacker doesn't need to find a novel vulnerability at all, just check what version of the parsing library is in use (sometimes visible from error messages or response headers if not carefully controlled) and use an existing public exploit against it via the upload endpoint in §2.

---

## 12. Incident response

### Do
- Maintain a written, tested incident response runbook covering at minimum: document/data exposure, cross-user data access (IDOR realized), credential compromise, and unauthorized admin access — `06-non-functional-requirements.md` §4 already requires this exists; this section specifies what "tested" means in practice.
- Define clear roles for an incident: who has authority to revoke sessions/credentials, who communicates with affected users, who decides on regulatory notification. **Note:** deciding *whether and how* to notify is a legal/compliance judgment call for the business to make, not an engineering one — this pack's role, per `06-non-functional-requirements.md` §5, is to make sure the data model and deletion mechanics can actually *support* that decision once made (e.g. answering "what data did this affect, for which users, since when"), not to provide the legal advice behind it.
- Practice the runbook via a tabletop exercise before it's needed for real — walk through "a user reports seeing another user's CV data" as a concrete scenario and confirm the team knows the actual steps (which logs to check first, how to confirm scope, how to revoke access, how to notify).
- Preserve evidence before remediating where possible — a rushed fix that also destroys the audit trail of how the incident happened makes the retrospective much harder.

### Don't
- Don't treat the incident response plan as complete once it's written — an untested runbook reliably turns out to have gaps exactly when it's needed most.
- Don't let the first time the team uses the runbook be a real incident.

### How to test
- Run a tabletop exercise for at least the IDOR-realized scenario and the credential-compromise scenario before Phase 5 sign-off, and again on a recurring cadence (at minimum annually, or after any significant architecture change).
- After any real incident (however minor), run a blameless retrospective and update the runbook with what was actually learned — treat every real trigger, however small, as a free test of the plan.

---

## 13. Gaps identified in the existing pack and recommended additions

Reviewing the rest of this pack against the analysis above surfaced a few concrete gaps worth acting on, not just noting:

1. **Malware scanning on CV upload** (§2) isn't currently a listed task anywhere in `07-first-sprint-tasks.md`. Recommend adding it as a Phase 1, sprint-2-or-3 blocking task, before `POST /cvs` is exposed to any traffic beyond internal testing.
2. **SSRF protection on job post URL fetch** (§4) isn't explicitly called out in the existing architecture or non-functional requirements documents beyond the general "unfetchable URL -> 422" error-handling note. Recommend adding explicit SSRF-safe-fetch requirements to Phase 2 (job post ingestion) acceptance criteria.
3. **Evidence-reference content verification**, not just presence (§5) — the existing data model correctly requires evidence references to be non-empty, but doesn't yet specify that the reference must be verified to actually *support* the specific claim it's attached to. Recommend this be made an explicit acceptance criterion for the Phase 3 validation layer, not just "a reference exists."
4. **Security testing isn't yet in `09-test-plan.md`** as its own section — that document's §9 ("Security and access control") is a reasonable start but doesn't yet reference this document's specific test cases. Recommend cross-referencing this security plan's per-section "How to test" content into the test plan directly, so security tests run as part of normal CI/test cycles rather than as a separate, easily-deprioritized pen-test-only activity.
5. **Rate limiting granularity** — `08-deployment-guide.md` currently specifies one general `RATE_LIMIT_REQUESTS`/`RATE_LIMIT_WINDOW` pair. Recommend adding endpoint-tier-specific limits per §6 of this document before Phase 5.

None of these are large additions individually, but each closes a real gap identified by walking through this system's actual attack surface rather than a generic checklist — which is the reason this review was worth doing specifically against the existing pack rather than in the abstract.

## 14. What "hardened" means for this system, concretely

A reasonable, testable bar for this system before calling it production-ready:

- Every item in §§1-9's "How to test" sections has been run and passes, with the results recorded somewhere durable (not just "someone remembers checking").
- The gaps in §13 have been resolved or explicitly accepted as a documented risk with a named owner and a revisit date — not silently dropped.
- At least one incident response tabletop (§12) has been run.
- Dependency and secret scanning (§9, §11) are active CI gates, not optional manual steps.
- A third-party security review or penetration test has been conducted at least once before handling real user data at scale, and its findings have been triaged and addressed or explicitly risk-accepted. This document is a strong foundation for that review, not a substitute for it — an external, adversarial perspective consistently finds things a team building the system doesn't, precisely because they don't share the same assumptions about how the system is meant to be used.
