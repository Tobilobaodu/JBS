# Frontend Product Roadmap for the CV Tailoring App

## 1. Context and goals

This roadmap turns the recent backend-focused conversation and product voice note into a concrete frontend plan.
The frontend is the real customer-facing layer for the CV tailoring platform, not just a developer harness.
Its main goals:

- Let new users "try for free" without friction.
- Turn that trial into an account + subscription without losing progress.
- Give logged-in users a clear dashboard of CVs, jobs, matches, cover letters, and tracked companies.
- Respect backend constraints around rate limiting, job concurrency, and security.

---

## 2. Core user journeys

### 2.1 Landing and trial

- **Landing page** (`/`)
  - Hero explaining the value proposition: "Evidence-backed CV tailoring and cover letters".
  - Primary CTAs: "Try for free" (for new users), "Log in" (for existing users).
  - Secondary content: high-level feature summary, credibility signals, simple explanation of the workflow.

- **Trial start** (`/try`)
  - Form to upload a CV (PDF/DOCX).
  - Field to paste a job URL or full job description.
  - Submit button triggers backend calls to create a CV, job post, and match.
  - Anonymous user; no account yet.

### 2.2 Trial results and tailored CV

- **Results page** (`/try/results` or `/results/[sessionId]`)
  - Shows:
    - Overall match score between CV and job.
    - ATS/readiness indicators (e.g., structure, keywords, role fit).
    - Key insights (skills missing, experience gaps, keyword suggestions).
  - Tailored CV preview based on the match engine’s recommendation.
  - Clear messaging that this is a trial and some actions are locked.

- **Actions on results page**
  - "Download trial CV" (one-time, free-tier allowed).
  - "Create cover letter for this job" → leads into auth/paywall.

### 2.3 Auth handoff without losing context

- When an anonymous user clicks "Create cover letter" or attempts a premium-only action:
  - Show a modal or interstitial explaining that an account is needed to continue.
  - Offer "Log in" and "Create account" paths.
  - Preserve trial context (CV, job, match) via:
    - Query parameters (e.g., `?trialMatchId=…`), and/or
    - Client state (Zustand store) and `sessionStorage` backup.

- After successful login/registration:
  - Backend attaches the trial entities to the new user.
  - Frontend redirects the user back to a "Continue where you left off" screen.
  - The user sees the same match and tailored CV, now in an authenticated context.

### 2.4 Authenticated dashboard and workflows

- **Dashboard home** (`/dashboard`)
  - Summary cards: number of CVs, jobs, matches, cover letters, followed companies.
  - Recent activity list (e.g., last 3 matches, last 3 cover letters).

- **CVs section** (`/dashboard/cvs`)
  - List of uploaded CVs.
  - Actions: upload new, view details, view associated matches, start new match.

- **Jobs section** (`/dashboard/jobs`)
  - List of saved job posts.
  - Actions: view job, see matched CVs, start new match, link to company details.

- **Matches section** (could be `/dashboard` or its own tab)
  - List of match runs (CV + job combinations).
  - Status (pending/processing/completed/failed).
  - Links to results and tailored CV.

- **Cover letters** (`/dashboard/cover-letters`)
  - List of generated cover letters.
  - Status, job link, CV reference.
  - Download and copy-to-clipboard actions.

- **Company tracking** (`/dashboard/company-tracking`)
  - Table of followed companies, industries, status (active/inactive).
  - "Track new company" action.
  - Recent alerts widget (e.g., new roles for followed companies).

### 2.5 Settings

- **Settings** (`/dashboard/settings`)
  - **Account tab:** email, password change — existing backend auth endpoints, no new backend surface needed.
  - **Billing tab:** current plan/status (read from `/me` entitlements, §4.1), plus a single **"Manage billing"** button.
    - Clicking it calls `POST /billing/portal-session` and redirects the user to a Stripe-hosted **Customer Portal** session.
    - Payment-method updates, invoice history/download, and subscription cancellation all happen inside that Stripe-hosted portal — not as custom in-app screens.
    - Rationale: Stripe's portal already handles these flows correctly and keeps raw payment data and PCI scope entirely off this app's frontend and backend. Trade-off: less brand/visual control than a fully custom billing UI — acceptable for v1, revisit only if that becomes a real product complaint.
  - On return from the portal (or from Checkout, §4.2), the frontend refetches `/me` to refresh entitlements, same pattern already used for the upgrade flow.

---

## 3. Technology choices (frontend)

### 3.1 Framework and structure

- **Framework:** Next.js 14+ with App Router and React 18.
- **Styling:** Tailwind CSS.
- **Components:** shadcn/ui for consistent, accessible primitives.
- **Routing structure (high level):**

  ```text
  frontend/
  ├── app/
  │   ├── (auth)/
  │   │   ├── login/
  │   │   ├── register/
  │   │   └── layout.tsx
  │   ├── (dashboard)/
  │   │   ├── dashboard/
  │   │   ├── cvs/
  │   │   ├── jobs/
  │   │   ├── cover-letters/
  │   │   ├── company-tracking/
  │   │   └── layout.tsx
  │   ├── try/
  │   │   ├── upload/
  │   │   ├── results/
  │   │   └── page.tsx
  │   ├── cover-letter/[workflowId]/
  │   ├── layout.tsx
  │   └── page.tsx (landing)
  ├── components/
  ├── lib/
  ├── hooks/
  ├── types/
  └── public/
  ```

### 3.2 State management

- **Server state:** TanStack Query (React Query)
  - For data backed by the backend API:
    - `/me` (user profile & entitlements).
    - CVs, jobs, matches, cover letters, companies, alerts.
    - Match results, tailored CV content, cover-letter outputs.
  - Benefits: automatic caching, retries, refetch on focus/network change.

- **Client/global state:** Zustand (or React Context for simpler slices)
  - For short-lived and cross-page state:
    - Auth session token (if not fully cookie-based).
    - Trial workflow state: `trialSessionId`, `cvId`, `jobPostId`, `matchId`.
    - UI state: modals, toasts, step indicators.
    - Local flags like "hasSeenTrialExplanation".

- **Forms & validation:** React Hook Form + Zod schemas.
  - Shared schemas with backend where possible to avoid divergence.

### 3.3 Auth & accounts

- **Backend of record:** existing FastAPI auth and user accounts.
- **Frontend integration:**
  - Use NextAuth.js (or a custom auth client) configured with:
    - Credentials provider pointing at backend `/auth/login` and `/auth/register`.
  - Store JWT/session as per backend security guidance (likely secure cookies).
  - On login and registration success:
    - Refetch `/me` to refresh entitlements.
    - If a trial continuation is pending, redirect back to the appropriate page.

---

## 4. Pricing and feature management

### 4.1 Entitlements model

Frontend treats the backend as the source of truth for plans and permissions.

- Backend exposes:
  - `plan`: e.g. `"free" | "trial" | "premium"`.
  - Feature flags per user: `canCreateCoverLetter`, `canTrackCompanies`, `trialRemaining`, etc.

- Frontend normalizes into an `Entitlements` object stored in context/Zustand:
  - `entitlements = { canUseTrial, canCreateCoverLetter, canTrackCompanies }`.

- Every feature checks both:
  - User entitlements (from `/me`).
  - Static or remote feature flags (for staged rollouts).

### 4.2 Paywall behavior

- For locked actions (e.g., generating cover letters, company tracking):
  - If user is not logged in → show auth paywall.
  - If user is logged in but not entitled → show upgrade paywall.
  - Clicking "Upgrade" calls backend to create a checkout session (Stripe Checkout).
  - On return from checkout, frontend refetches `/me` and updates entitlements.

- A simple feature flag module on the frontend controls visibility for experimental or future features.

- **Managing an existing subscription** (payment method, invoices, cancellation) is handled separately from the upgrade paywall — see §2.5 Settings. It uses the Stripe Customer Portal rather than the Checkout flow above.

---

## 5. Integration with backend APIs

### 5.1 Key flows and endpoints

- **Upload CV**: `POST /cvs` → returns `cvId`.
- **Submit job URL**: `POST /job-posts/url` → `jobPostId`.
- **Submit job text**: `POST /job-posts/text` → `jobPostId`.
- **Create match**: `POST /matches` → `matchId`.
- **Fetch match result**: `GET /matches/{matchId}` → match score, breakdown, recommended changes.
- **Generate tailored CV**: existing backend endpoint; returns structured content or a downloadable format.
- **Generate cover letter**: existing/Planned endpoint; returns cover-letter content.
- **Company tracking**: endpoints for create/list/delete followed companies and alerts.

Frontend should:

- Use React Query mutations for POST/PUT/DELETE calls.
- Use React Query queries for GET endpoints.
- Standardize error handling (e.g., show toast on network error, inline validation errors for 4xx responses).

---

## 6. Phased delivery plan

### Phase 0 — Frontend skeleton

**Goal:** Set up the frontend repo, shell, and core infrastructure.

- Initialize Next.js 14 app with TypeScript, Tailwind, shadcn/ui.
- Add QueryClientProvider and a basic Zustand store.
- Implement global layout with navbar and empty `page.tsx` for `/`.
- Implement `/login` and `/register` pages wired to backend auth.
- Add simple route guards for authenticated dashboard routes.

### Phase 1 — Anonymous trial flow

**Goal:** Let new users upload a CV and job, and see a trial match.

- Build `/try/upload` page with:
  - CV file input (React Hook Form).
  - Job URL/text input.
  - Submit button that calls `/cvs` and job-post endpoints, then creates a match.
- Add minimal loading and error states.
- Implement `/try/results` (or `/results/[sessionId]`) page:
  - Fetch match result via `matchId` in query or Zustand.
  - Display match score and basic breakdown.
  - Show tailored CV preview if available.
- Store trial identifiers in Zustand + `sessionStorage` for resiliency.

### Phase 2 — Auth handoff and continuation

**Goal:** Smoothly transition from trial to account without losing context.

- Add a paywall modal for "Create cover letter" on the trial results page.
- Implement trial-aware login/register:
  - Pass `trialMatchId` (and related IDs) through auth.
  - After auth, call a backend endpoint that links the trial run to the user.
- Implement a "Continue where you left off" screen post-login.

### Phase 3 — Dashboard & history

**Goal:** Give authenticated users a clear view of their data.

- Build `/dashboard` overview with summary cards.
- Build `/dashboard/cvs`, `/dashboard/jobs`, `/dashboard/cover-letters` lists.
- Implement detail pages or modals for items as needed.
- Ensure each list uses React Query and respects entitlements.

### Phase 4 — Premium features: cover letters, company tracking, billing

**Goal:** Deliver premium value and gating.

- Implement cover-letter workflow pages, locked behind `canCreateCoverLetter`.
- Implement `/dashboard/company-tracking` with:
  - Company list.
  - Track/unfollow actions.
  - Recent alert list.
- Integrate job alerts view and interactions (mark as read, navigate to job).
- Implement upgrade flow and basic pricing section (Stripe Checkout).
- Implement `/dashboard/settings` (§2.5): Account tab, and Billing tab wired to `POST /billing/portal-session` (Stripe Customer Portal) for payment method, invoices, and cancellation.
  - Depends on the same backend Stripe integration as the upgrade flow above (customer/subscription IDs, webhook-driven entitlement updates) — sequence after Checkout is working, not before.

### Phase 5 — UX polish and experimentation

**Goal:** Improve experience and prepare for design-led iteration.

- Refine results visualizations (charts, gauges).
- Improve copy, edge-case error handling, empty states.
- Add simple analytics hooks (page views, funnel drop-off points).
- Keep code modular so a future design system can replace components with minimal backend impact.

---

## 7. Open questions and decisions to make

- **Auth provider:** Confirm whether to use NextAuth.js with backend credentials or a different client-side auth library.
- **Anonymous trial persistence:** Decide how long to persist trial sessions and how to handle trial re-use across devices.
- **Billing provider:** ~~Choose Stripe (or alternative) and define backend subscription APIs.~~ **Decided (2026-08-12): Stripe.** Checkout for upgrades, Customer Portal for payment method/invoices/cancellation (§2.5, §4.2) — no custom billing UI. Backend needs `stripe_customer_id`/`stripe_subscription_id`/`plan`/`subscription_status` on the user, `POST /billing/checkout-session`, `POST /billing/portal-session`, and a `POST /webhooks/stripe` handler — not yet implemented (zero billing code exists in `backend/` today); scope for a future sprint.
- **Notification channel priorities:** Decide which alerts are email vs in-app first.
- **Company data source:** Confirm how company and job data will be sourced for tracking (API vs custom scraper).

These can be clarified as you hit each phase, but it helps to record them explicitly now.
