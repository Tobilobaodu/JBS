# AI CV Tailoring and Cover Letter Platform — Developer Pack

This pack gives a backend developer everything needed to start implementation without further scoping conversations, plus a lightweight frontend plan so backend work is testable end-to-end from Phase 1 onward. It covers backend services, processing pipelines, data model, APIs, and a developer-built test harness — full product frontend design and user journey remain a separate, later effort once a designer joins (see `13-frontend-plan.md` §6).

## How to use this pack

1. **Read `01-implementation-plan.md` first.** Stack recommendation, phased delivery plan, team shape, sequencing dependencies, and a short list of open decisions worth confirming early (§6).
2. **Read `02-architecture-overview.md` next.** This explains *why* the system is built the way it is — most importantly, the non-fabrication constraint that shapes every downstream decision, and the two-pass Docling + Textract extraction strategy.
3. **Check `12-project-status-and-roadmap.md` for where the project actually stands.** This is the canonical, code-verified status tracker — read it before trusting any other status claim (including a developer's own progress report), since it exists specifically because a submitted status claim didn't match the real codebase once checked.
4. **Read `10-security-plan.md` before writing any code that touches file upload, URL fetching, or generation.** These are the system's highest-risk surfaces, and the controls need to be built in from the start — see §13 of that document for the specific gaps this pack had before it was added.
5. **Start work from `07-first-sprint-tasks.md`.** Ticket-sized tasks for Phase 1, ready to pick up immediately — it now includes the malware-scanning task the security review surfaced. A Phase 2 equivalent doesn't exist yet — see `12-project-status-and-roadmap.md`'s immediate next actions.
6. **Reference `03-data-model.md` and `05-openapi.yaml` while building.** These are the two files you'll have open constantly during implementation — full column-level schema and a validated OpenAPI spec with request/response examples.
7. **Check `04-api-reference.md`** for a faster human-readable index of the API surface, shared error format, and pagination pattern when you don't need the full OpenAPI detail.
8. **Check `06-non-functional-requirements.md`** before Phase 5, and periodically throughout — particularly the security and evidence-traceability requirements, which need to be built in from Phase 1 rather than retrofitted. `10-security-plan.md` extends this document's §4 in depth.
9. **Use `08-deployment-guide.md`** when setting up local, staging, or production environments — includes the tiered rate-limiting config `10-security-plan.md` §6 requires.
10. **Use `09-test-plan.md`** to write tests as each phase lands, not just at the end — several test cases (particularly §3, profile-version integrity, and §9, which now points into the security plan's detailed adversarial tests) are there because they catch real design mistakes if skipped.
11. **Check `11-product-extensions.md` when Phase 3 begins.** Three of its six ideas (ATS structural validation, the fix-it checklist, and two schema-only reservations) are meant to be built alongside the core Phase 3 work, not bolted on afterward — see that document for which three, and why the other three are deliberately scoped differently (two as schema-only reservations, one flagged for a separate decision entirely).
12. **Build `13-frontend-plan.md`'s harness alongside each backend phase**, not after all backend work is done. It's a developer-owned test tool, not a product frontend — read §0 and §2 there before starting, since the scope boundary is deliberately tight and easy to accidentally blow past.

## Files in this pack

| File | Purpose |
|---|---|
| `00-README.md` | This file |
| `01-implementation-plan.md` | Stack, phases, timeline, team shape, sequencing dependencies, open decisions |
| `02-architecture-overview.md` | System architecture, extraction strategy, non-fabrication controls, cost estimate |
| `03-data-model.md` | Full entity list, column-level schema, relationships, JSON schemas, modelling rules |
| `04-api-reference.md` | Human-readable endpoint index, shared error format, pagination, API design rules |
| `05-openapi.yaml` | Machine-readable OpenAPI 3.0 spec (validated), request/response schemas and examples |
| `06-non-functional-requirements.md` | Security, compliance, reliability, performance requirements (baseline) |
| `07-first-sprint-tasks.md` | Ticket-sized Phase 1 tasks, ready to assign |
| `08-deployment-guide.md` | Environments, config, worker settings, monitoring, rollback, deploy checklist |
| `09-test-plan.md` | Test areas and exit criteria, including non-fabrication-specific test cases |
| `10-security-plan.md` | Attack-surface-by-attack-surface do's/don'ts, defense-in-depth controls, adversarial tests, exploitation scenarios, incident response |
| `11-product-extensions.md` | Six ideas for making the tool more useful than the core spec alone — three ready to build, two schema-reserved for later, one flagged for a separate scoping decision |
| `12-project-status-and-roadmap.md` | Canonical, code-verified status tracker — what's actually built vs. planned, corrected against a submitted status report that didn't fully match the codebase |
| `13-frontend-plan.md` | Developer-built test harness plan, phase by phase, plus the handoff plan for when a designer joins |

A few config values in `08-deployment-guide.md` (LLM model, export formats, cost alert thresholds, rate-limit numbers, malware scanner choice) are placeholders rather than settled decisions — see `01-implementation-plan.md` §6 before treating them as final.

## On trusting status claims

`12-project-status-and-roadmap.md` exists because a developer-submitted "complete" status for part of Phase 1 turned out, on direct code review, to be inaccurate for one specific claim (a bug fix that was described as done but wasn't actually applied). This isn't a comment on the developer's competence — the rest of their submitted status was accurate, and the actual implementation work reviewed was generally solid. It's a reminder that "done" claims, from any source including a future update to this pack, are worth spot-checking against the real code before being trusted as the basis for what to build next, especially where one phase's correctness depends on an earlier one's.

## On security specifically

`10-security-plan.md` is thorough, but it is not — and no document can be — a guarantee that this system will withstand any possible attack. What it gives instead: a concrete, testable control for every attack surface this specific system exposes (not a generic checklist), a way to verify each control actually works rather than just exists, and a clear-eyed account of what a real exploitation attempt looks like against this product's actual endpoints and data model. Treat its §14 "what hardened means" bar as the real target, and get an external security review before handling real user data at scale — that document says so itself, and it's worth taking at face value rather than as a formality.

## The one thing to hold onto throughout

Every generated sentence in a tailored CV or cover letter must be traceable to either the user's parsed CV or an answer they gave in the guided workflow. No invented employers, figures, dates, skills, or achievements — ever. Where evidence is missing, the system omits, flags, or asks; it never guesses. This isn't a content-quality nice-to-have, it's a correctness requirement baked into the schema and validation layer (see `02-architecture-overview.md` §6 and `03-data-model.md` §4). If a design decision during implementation ever seems to trade this off for convenience or speed, that's worth raising rather than working around.
