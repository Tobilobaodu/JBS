# Job board – Conversation Export (with Frontend Best Practices)

This file collects the key content from our current chat, including:
- Backend security and rate-limiting work
- SSRF streaming-size enforcement
- Per-user concurrent jobs limit and its current blocked status
- Frontend product vision from your voicenote (the website your customers will use)
- Folded-in best practices from modern SaaS / free-trial / onboarding patterns

It is not a perfect word-for-word transcript, but it contains all important instructions, decisions, and reports that affect your project.

---

## Frontend product vision (transcribed voicenote)

You described the intended **customer-facing frontend** that will sit on top of this backend.

### Landing page and first fold

- Users land on a main page that looks like a polished app/marketing site ("the Apple website" feel).
- In the navigation and above the fold, there are **two primary actions**:
  - Existing customers: **“Log in”**
  - New customers: **“Try for free”**
- The hero/first fold also repeats those calls to action so it is very clear how to start.

### Second fold and general content

- The second fold highlights **features of the application**.
- Below that, additional folds can contain more general information and marketing copy ("general fluff"), which you will design.

### New customer journey – “Try for free”

1. New customer clicks **“Try for free”**.
2. They are **not** asked to create an account immediately.
3. Instead, they are sent to a trial page where they can:
   - Upload their **CV**.
   - Provide a **job posting** they want to test against, by pasting a **job URL** or job description text.
4. The platform backend:
   - Parses and analyzes the CV.
   - Fetches and parses the job post.
   - Compares CV vs job.
   - Computes a **score** and structured feedback.
5. The frontend shows a results page for the trial with at least:
   - An overall **match score**.
   - **ATS readiness** indicators.
   - Experience relevance and other key dimensions.
   - Visual presentation to make it easy to understand.

The exact layout and metrics on this scoring page will be defined in a later design step, but we know it needs to:
- Communicate value quickly.
- Show why the tailored CV is better aligned to the job.

### From score to tailored CV

- After seeing the score, the user can click a button such as **“Review my CV”**.
- Based on the engine’s recommendations, a **new tailored CV** is generated for that specific job.
- The user can then **view and download** this tailored CV.

### Cover letter step and login/registration

- After creating the tailored CV, the next step is to offer the user a **cover letter** for the same job.
- The cover-letter feature sits behind a **lock/paywall**:
  - When the user clicks something like **“Create cover letter for this job”**, they are taken to a **login / register** page.
  - The system must remember their current CV, job, and match context so they do **not** have to start over.
- After logging in or creating an account, the user should be able to **continue** where they left off:
  - Their uploaded CV and chosen job are already associated with their new account.
  - They can proceed to cover-letter generation without repeating the upload/match steps.

### User management and dashboard

- You want to think carefully about **user management** – whether to use Firebase, Supabase, or the existing backend auth – but the goal is the same:
  - Users can log in and have a persistent account.
- After login, there is a **dashboard** where users can:
  - See CVs they have previously uploaded.
  - See jobs they have matched against.
  - See tailored CVs that have been generated.
  - See cover letters that have been created.
- You want the dashboard to be **comprehensive** but **scalable**, so the infrastructure must support adding more features later.

### Overall product vision

- The app’s core purpose is to:
  - Help users **review and tailor CVs** against specific jobs.
  - Help users **create cover letters** for those jobs.
- Future extension: **company tracking and job alerts**.
  - Users can follow companies (e.g., Amazon, Meta, Google).
  - They add each company’s careers page.
  - When those companies post new jobs that match the user’s role/industry (e.g., Product Designer, UX Designer), the user receives a **notification**.
  - This company tracking + job alerts feature will live **behind a paywall**.
- Free tier:
  - A new user can only **try once** for free.
  - To continue using the app, they must pay (subscription or credits) and have an account.

---

## Frontend best practices folded into your design

This section merges your product vision with established patterns for SaaS free-trial onboarding, landing pages, and job-related dashboards.[web:45][web:46][web:49][web:53][web:56]

### Landing page: structure and copy

**Goal:** one primary action – "Try for free" – with a clear path for existing users to log in.

Best-practice elements:
- **Hero above the fold:**
  - Outcome-focused headline such as: "Get a job-ready CV and cover letter for every role you apply to".
  - Subheadline that names your audience and mechanism, e.g., "Upload your CV, paste a job link, and let our engine tailor your application in minutes".[web:45][web:49]
  - Primary CTA: **"Try it free – no credit card"** or **"Start my free trial"**.[web:45][web:46]
  - Secondary CTA: subtle **"Log in"** for existing users in the nav and perhaps a ghost button next to the primary CTA.[web:47]
- **Hero visual:**
  - Show the product in action: a mockup of the scoring/tailored CV screen, not an abstract illustration.[web:47][web:56]
- **Trust bar under hero:**
  - Logos of companies where users have gotten interviews (once you have them) or social proof stats (e.g., "Helped job seekers land interviews at…").[web:45][web:56]

Navigation and CTA rules:
- One primary action for new visitors: "Try for free".
- "Log in" visually secondary (outline/ghost) in the nav.[web:47][web:57]
- Repeat the primary CTA after:
  - The trust section.
  - The feature section.
  - The closing section (near the footer).[web:45][web:49]

### Free-trial / "Try for free" page

**Goal:** let a new user experience the core value (score + tailored CV) with minimal friction.

Best-practice adjustments:
- **Minimal form:** no upfront account; the only required inputs are:
  - CV upload.
  - Job input (URL or pasted description).
  - Optional email for sending results (but do not block the flow on it).[web:46][web:48]
- **Page layout:**
  - Left: a short explanation and step-by-step timeline:
    - Step 1 – Upload your CV.
    - Step 2 – Paste a job link.
    - Step 3 – See your match score and tailored CV.
  - Right: the uploader and job URL field, plus a primary **"Run my match"** button.[web:46][web:48]
- **Friction control:**
  - No navigation menu on the dedicated trial-execution page (to avoid exits).[web:48]
  - Clear notice: "No credit card required • One free tailored CV and score".

### Score and feedback page

**Goal:** show the value clearly and lead users into the next meaningful action: downloading the tailored CV and starting the cover letter step.

Recommended structure:
- **Header:** job title and company, plus their CV title.
- **Top block:** large overall match score (e.g., 0–100) with a short interpretation ("Good fit", "Needs work").
- **Segmented metrics:** separate sections for:
  - ATS readiness (format, keyword coverage, length, structure).
  - Experience match to key responsibilities.
  - Skills match.
  - Gaps and suggestions.
- **Action bar:**
  - Primary: **"Review tailored CV"**.
  - Secondary: **"See improvement suggestions"**.

Keep this page focused on clarity and value, not account creation. The only friction you may introduce here is a small inline prompt: "Want to save this result? Add your email" – but you still let them proceed without it.

### Tailored CV view and download

**Goal:** confirm that the engine created something useful and set up the cover-letter upsell.

Pattern:
- Show the tailored CV in a reader-friendly layout (e.g., centered A4 preview with scroll, plus a download button).
- Provide a small side panel with:
  - Job context.
  - Key improvements the engine made.
  - A small, persistent CTA: **"Create a cover letter for this job"**.

At this stage, still no forced account creation; you are delivering on the "free trial" promise.

### Cover letter step and account creation

**Goal:** convert an engaged trial user into a registered user without making them start over.

Best practice:
- When the user clicks **"Create cover letter"**, show a lightbox or dedicated page that:
  - Reminds them what they are getting: "We’ll generate a tailored cover letter for [Job Title] at [Company] based on your CV and match analysis".
  - Offers **quick sign-up**:
    - Email + password (2–3 fields max), **or**
    - Social login (Google / Microsoft) as primary options.[web:45][web:46][web:54]
- Copy pattern:
  - Headline: "Create your account to continue".
  - Subheadline: "Save your tailored CV, generate cover letters, and track jobs – free for one application".
- Do not discard the trial context:
  - The backend must associate the anonymous trial with a temporary identifier (cookie/session/token) and then attach it to the account post registration.
  - After signup, redirect them directly to the cover-letter generation screen for the same CV and job.

### Dashboard design and information architecture

**Goal:** give authenticated users a clear home for their CVs, jobs, matches, and cover letters.

Best-practice sections (top-level navigation inside the app):[web:52]
- **Home / Overview:**
  - Recent matches, recent jobs, and quick actions ("Upload new CV", "Match against job", "Generate cover letter").
- **CVs:**
  - List of uploaded and generated CVs.
  - For each: date, number of jobs used on, quick actions.
- **Jobs:**
  - Saved jobs the user has matched against.
  - Status tags (e.g., "Matched", "Applied", "Interviewing").
- **Cover letters:**
  - Generated cover letters with link to corresponding job and CV.
- **Companies / Alerts (premium):**
  - Companies the user follows.
  - Alert preferences by role/keywords.

Design patterns:
- Cards or table-style lists with clear primary action per item (e.g., "Open", "Match again", "Generate cover letter").
- Filters for job status, company, and date.
- Empty-state designs that guide first-time behavior (e.g., "You haven’t saved any jobs yet – paste a job link to get started").

### Company tracking and alerts (premium)

**Goal:** make it easy to follow companies and receive relevant job alerts, while keeping this clearly as a paid feature.

Best-practice framing:
- Inside the dashboard, a "Companies" tab that:
  - Lets the user add company careers URLs.
  - Lets them set preferences: roles, locations, seniority.
- Alerts:
  - Email notifications and/or in-app notifications when new matching jobs appear.
- Paywall pattern:
  - Show the UI, but gate actions like "Add more than 1 company" or "Enable alerts" with an inline upsell.
  - Clearly state the benefit and limits (e.g., "Track unlimited companies and get real-time alerts with Pro").

### Free trial and paywall policy

You want one free trial; modern best practices suggest:
- Let users get to first value (tailored CV + basic score) without friction.[web:54][web:55]
- Gate **repeated** use and **higher-value** features (cover letters, multiple companies, advanced analytics).

Implementation guidance:
- Enforce the "one free trial per person" policy at the backend using:
  - Accounts and, for anonymous users, device or browser identifiers; do not rely only on frontend checks.
- Align the paywall messaging on the frontend with backend rules to avoid surprises.

---

## Backend security and rate limiting – Task 2.1

(…same as in the previous export; backend sections unchanged, omitted here for brevity in this snippet…)