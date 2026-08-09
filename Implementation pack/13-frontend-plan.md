# Frontend Plan

## 0. What this document is and isn't

This is a plan for a **developer-built internal test harness**, not a product frontend. Its job is to let the backend developer (and anyone reviewing progress) actually exercise real endpoints through a browser instead of curl/Postman, catching integration bugs early and giving a visible, demoable artifact at the end of each phase. It is explicitly *not* trying to anticipate what a designer will eventually want — see §6 for why building less, not more, is the right call here, and what happens when design joins.

If you're a developer picking this up: build the minimum each phase needs, resist adding polish, and don't be precious about deleting or rewriting harness code once design work starts. That's the deal this document is making with you in exchange for keeping scope small.

## 1. Why a harness, and why now

Phase 1 is functionally complete (pending the `confidence_score` fix in `12-project-status-and-roadmap.md`). Right now, the only way to verify the extraction pipeline actually works end-to-end is via direct API calls — which tests the API, but not the experience of using it, and doesn't catch anything that would only show up when a human uploads a real, messy file through a browser (a wrong `Content-Type` from a browser's file picker, a slow upload UX exposing a missing progress signal, a poll loop that never terminates because a status value arrives that the frontend didn't expect).

Building a thin harness now, rather than waiting for a "real" frontend later, means:
- Every phase gets a working, clickable demo the moment its backend work lands — matching the "demonstrable outcome" already defined for each phase in `01-implementation-plan.md`.
- Integration bugs (status enums, response shapes, polling behaviour, error envelope handling) get caught by a developer against real code, not discovered later by a designer or a QA pass.
- When a designer joins, they inherit a *working reference implementation* of every flow, not a blank page and an OpenAPI spec — they can see what the flow actually does before deciding how it should look.

## 2. Scope boundary: what the harness is and is not

**Is:**
- A minimal, unstyled (or barely styled) set of pages that call real backend endpoints and show real responses.
- Built and owned by the backend developer, growing one phase at a time alongside the API work it tests.
- Disposable. No component library investment, no design system, no responsive design work, no accessibility polish beyond basic semantic HTML. Every hour spent polishing the harness is an hour not spent on backend correctness, and it will likely be substantially rewritten once design joins anyway.

**Is not:**
- A preview of the final product's look and feel.
- A place to make UX decisions that should wait for design (copy tone, layout, information hierarchy, error messaging style) — use the plainest possible version of each ("Upload failed: invalid file type" is fine; there's no need to workshop it).
- Built with any framework lock-in that would be expensive to abandon. See stack recommendation below — the goal is fast to build and easy to throw away, not fast to scale.

## 3. Recommended stack for the harness

| Layer | Choice | Why |
|---|---|---|
| Framework | Plain HTML + vanilla JS, or a minimal React setup (Vite + React, no router library needed yet) | Either is fine — the point is minimal setup overhead. If the eventual product frontend is already known to be React (common, given the backend team likely knows JS/TS from adjacent work), starting the harness in React means less throwaway work later, but this isn't load-bearing. Don't spend more than an hour deciding. |
| Styling | None, or a single unstyled CSS reset | Explicitly do not reach for a component library or design system here — see §2. |
| State management | None — component-local state or plain variables | The harness has no complex cross-page state to manage yet; don't add a state library pre-emptively. |
| API calls | `fetch`, called directly against the documented endpoints in `05-openapi.yaml` | No API client generation, no SDK — call the real endpoints directly so the harness stays honest about what the API actually returns. |
| Auth | Store the JWT in memory or a plain variable for the harness session; re-login on refresh is fine | Don't build "remember me," secure token storage, or refresh-token rotation UX into the harness — that's product frontend work, and building it here risks becoming load-bearing prematurely (see §6's warning about scope creep). |
| Hosting | Run locally via the dev server (`vite dev` or a plain static file server), pointed at the local API (`http://localhost:8000`) | No deployment needed for the harness at this stage — it's a local developer tool, not a shipped artifact. Revisit if the team wants a shared staging harness later. |

## 4. Build plan, phase by phase

Each phase's harness work should ship in the same sprint window as the backend work it tests, not trail behind it — the whole point is catching integration issues while the backend developer still has full context on what they just built.

### Phase 1 harness (build now — backend is ready)

- **Login/register page.** Plain form, calls `POST /auth/register` and `POST /auth/login`, stores the returned token, redirects to the upload page on success. Shows the raw error envelope on failure (`04-api-reference.md`'s error format) — don't prettify it, seeing the real shape is the point.
- **Upload page.** A file input, calls `POST /cvs`, shows the returned `cvId` and `processingJobId`.
- **Status page.** Given a `cvId`, polls `GET /jobs/{jobId}` on an interval (2-3s is fine) and displays the raw `status` value as it changes (`queued` → `extracting` → `merging` → `completed`/`failed`). This is the single most valuable page in the Phase 1 harness — it's the only way to *see* the async pipeline behaving correctly (or not) instead of inferring it from logs.
- **Result page.** Once status is `completed`, fetch and display `GET /cvs/{cvId}/raw-text` and `GET /cvs/{cvId}/extraction-detail` as raw JSON (a `<pre>` tag is genuinely fine). Seeing the actual `structural_validation_result` output — including whether `confidence_score` looks sane once that fix lands — is more useful here than any formatted view would be at this stage.
- **CV list page.** Calls `GET /cvs`, lists uploaded CVs with their status, links to each one's status/result page.

This is enough to demo Phase 1 end-to-end in a browser: register, log in, upload a CV, watch it move through the pipeline, see the extracted result.

### Phase 2 harness additions

- **Parsed profile view.** Once `GET /cvs/{cvId}/parsed-profile` exists, add a page (or extend the result page) showing the structured profile — this is the first point where a human can actually eyeball whether section-heading canonicalization and parsing are working, which matters more here than almost anywhere else since it's easy for a parsing bug to look correct in a JSON blob and only be obviously wrong when a human reads it as a CV.
- **Job post submission page.** Two simple forms (URL and pasted text) calling `POST /job-posts/url` and `POST /job-posts/text`, plus a status/result view mirroring the CV one. Specifically worth testing here: submitting a URL that should trigger the SSRF protections (§4 job post ingestion in `10-security-plan.md`) and confirming the harness correctly surfaces the `422` "paste the text instead" response rather than hanging or erroring unclearly — this is a good, cheap way to manually sanity-check the SSRF work as it's built, not just via automated tests.
- **Job post list page**, mirroring the CV list page.

### Phase 3 harness additions

- **Match trigger and result view.** Form to select a CV and job post, calls `POST /matches`, then displays the match result — critically, this should show the support-level breakdown per requirement (`supported`/`partially_supported`/`unsupported`/`contradictory`/`unclear`) as a simple list, not just a score. Seeing all five support levels rendered distinctly, including the newer `contradictory`/`unclear` ones, is a good manual check that the matching engine is actually using all five rather than collapsing edge cases into the familiar three.
- **Tailored CV draft view.** Calls `POST /matches/{matchId}/tailored-cv`, then polls and displays the result, including the `improvement_checklist` field (product extension #3) as a plain list — this is a good place to manually eyeball whether checklist suggestions ever look like they're implying experience the user doesn't have (the specific fabrication risk flagged in `11-product-extensions.md` §3).
- **ATS check view**, if extension #1 is built in this phase: calls `POST /cvs/{cvId}/ats-check`, displays the score and per-check breakdown.
- **Approve button**, calling `POST /tailored-cvs/{draftId}/approve` — simple, no confirmation dialog needed at harness quality.

### Phase 4 harness additions

- **Cover letter workflow pages.** Start workflow, display returned questions as a plain form, submit answers, show the draft, allow regeneration. This is inherently the most multi-step flow in the product, so the harness version doesn't need to be elegant, but it does need to correctly walk through the actual state machine (`in_progress` → step increments → `draft_ready` → `approved`) so the developer building it can confirm the state transitions work before a designer ever has to think about how to present them.

### Phase 5 harness additions

- **Export trigger and download link**, once export format is decided (`01-implementation-plan.md` §6 open decision).
- **Coverage report view** (extension #2), if built: a simple list of collections, a button to run a report, and the aggregate-gaps list displayed plainly.

By the end of Phase 5, the harness covers every documented endpoint in `05-openapi.yaml` in some minimal clickable form — not because that's a goal in itself, but because it falls out naturally from building one page per phase's new capability.

## 5. What NOT to build into the harness, even if it seems easy

Worth naming explicitly, since these are exactly the kind of thing that quietly creeps into a "quick test page" and become hard to unwind later:

- **No responsive/mobile layout.** Desktop-only, fixed-width is fine.
- **No client-side form validation beyond what's needed to avoid obviously broken requests.** Let the API's real validation errors surface — that's more useful for testing than pre-empting them.
- **No loading skeletons, animations, or transitions.** A visible "Loading..." text node is enough.
- **No routing library.** Plain links or even manually typed URLs with query params are fine for a harness this size; don't add React Router or equivalent pre-emptively.
- **No component abstraction for its own sake.** Duplicate a bit of markup across pages rather than building a shared component layer — the harness doesn't live long enough to pay back that investment, and premature abstraction here is wasted effort against §6's plan.
- **No attempt to handle every error case gracefully.** Showing a raw error is fine and arguably better for testing purposes than a polished "something went wrong" message that hides what actually happened.

## 6. Design handoff — what happens when a designer joins

This is the part worth planning for now, even though it's not immediate work, because getting the handoff wrong either wastes the harness's value or blocks the designer unnecessarily.

**What carries forward:** the harness's functional knowledge — which endpoints exist, what each flow's real steps and state transitions are, what edge cases showed up in practice (e.g. "the status polling needs a max-retry cutoff, we found a job that got stuck in `processing`"). This is genuinely valuable and should be captured, not just left implicit in throwaway code — see the handoff note below.

**What does NOT carry forward:** the harness's actual markup, styling (if any), and UI decisions. The designer should not be handed the harness and asked to "make it look nice" — that anchors their thinking on developer-driven layout choices made under time pressure with zero design intent behind them. Anchoring effects are real and hard to fully undo even with good intentions; a designer working from a blank page with the *functional* spec (this document plus the OpenAPI spec) will produce meaningfully different, better work than one editing an existing implementation.

**Concrete handoff artifact:** before a designer joins, the developer should produce a short **flow-and-state summary** — not a new document from scratch, but a lightweight addition to this one: for each user-facing flow (upload → track → view result; submit job post; run match; generate draft; cover letter workflow; export), list the actual steps a user goes through, every distinct state the UI needs to represent (loading, success, each error type, empty states), and anything non-obvious learned while building the harness (timing quirks, fields that are sometimes null and need a fallback, etc.). This is the artifact that actually transfers value from the harness phase to the design phase — the harness code itself is disposable, but this knowledge isn't. Add it as §7 of this document once Phase 2 or 3 is far enough along to write it meaningfully; it's premature before then.

**Sequencing:** design should join once there's enough built (realistically, once Phase 3's core loop — upload, match, tailored draft — is working end-to-end) to design against real, working flows rather than a spec on paper. Joining earlier risks designing for flows that shift as backend implementation reveals real constraints; joining much later wastes time the design phase could have used in parallel with Phase 4/5 backend work. Phase 3 completion is a reasonable trigger point to revisit this timing, not a fixed rule.

## 7. Flow-and-state summary

*Not yet written — see §6. Add this once Phase 2 or 3 is far enough along that the flows and edge cases are actually known from harness use, not guessed in advance.*
