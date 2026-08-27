"use client"

import { useEffect, useRef, useState } from "react"
import { toast } from "sonner"

import { ApiError, errorMessage } from "@/lib/api"
import {
  createResumeRewrite,
  createTrialSession,
  downloadResumePdf,
  getCvRawText,
  getJobPost,
  submitJobPostUrl,
  uploadCv,
  type ResumeRewriteResult,
} from "@/lib/trial-api"
import { useAuthStore } from "@/store/auth-store"
import { useTrialStore } from "@/store/trial-store"
import { ScoreBar } from "@/components/modernist/score-bar"
import { Tag } from "@/components/modernist/tag"
import { SegmentedControl } from "@/components/modernist/segmented-control"

type UploadState =
  | { phase: "idle" }
  | { phase: "uploading"; fileName: string }
  | { phase: "extracting"; fileName: string; cvId: string }
  | { phase: "ready"; fileName: string; cvId: string; text: string }
  | { phase: "failed"; fileName: string; message: string }

/** Rate limits are per client IP and easy to exhaust while testing
 *  (5 trial sessions/hour, 10 uploads/hour, 20 rewrites/hour). A 429 is not
 *  a bad file or a broken rewrite, so it must not be reported as one.
 *  errorMessage() only reads ApiError.body.detail, hence the explicit
 *  branch rather than a rethrown Error. */
function failureMessage(
  error: unknown,
  rateLimited: string,
  fallback: string
): string {
  if (error instanceof ApiError && error.status === 429) return rateLimited
  return errorMessage(error, fallback)
}

/** The job post can arrive as pasted text or be fetched from a URL by the
 *  backend's SSRF-guarded fetcher. Either way the analysis only ever reads
 *  the text in the textarea, so a fetch ends by filling it in. */
type JobFetchState =
  | { phase: "idle" }
  | { phase: "fetched"; url: string }
  | { phase: "failed"; message: string }

const EXTRACT_POLL_MS = 2000
const EXTRACT_TIMEOUT_MS = 120_000
// job_fetch writes raw_text at status "structuring", before
// job_post_parse runs, so this does not wait for "completed".
const JOB_FETCH_POLL_MS = 1500
const JOB_FETCH_TIMEOUT_MS = 60_000
// Mirrors the API's own min_length on jobDescription.
const MIN_JOB_TEXT_CHARS = 40

function SkillList({
  title, items, tone, testId,
}: {
  title: string
  items: string[]
  tone: "matched" | "transferable" | "missing" | "keyword"
  testId: string
}) {
  if (!items.length) return null
  const variant = {
    matched: "neutral",
    transferable: "accent-2",
    missing: "outline",
    keyword: "accent",
  }[tone] as "neutral" | "accent-2" | "outline" | "accent"
  return (
    <div data-testid={testId}>
      <h4
        style={{
          margin: "0 0 8px",
          fontSize: 11,
          fontWeight: 600,
          textTransform: "uppercase",
          letterSpacing: "0.08em",
          color: "var(--color-neutral-600)",
        }}
      >
        {title} <span style={{ marginLeft: 4 }}>({items.length})</span>
      </h4>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {items.map((item) => (
          <Tag key={item} variant={variant}>
            {item}
          </Tag>
        ))}
      </div>
    </div>
  )
}

export default function TailorPage() {
  const trialSessionId = useTrialStore((s) => s.trialSessionId)
  const setTrialSession = useTrialStore((s) => s.setTrialSession)
  const isAuthenticated = useAuthStore((s) => !!s.accessToken)

  const [upload, setUpload] = useState<UploadState>({ phase: "idle" })
  const [jobDescription, setJobDescription] = useState("")
  const [jobSource, setJobSource] = useState<"text" | "url">("text")
  const [jobUrl, setJobUrl] = useState("")
  const [jobFetch, setJobFetch] = useState<JobFetchState>({ phase: "idle" })
  const [targetTitle, setTargetTitle] = useState("")
  const [result, setResult] = useState<ResumeRewriteResult | null>(null)
  // null when idle. "fetching" only occurs on the URL tab, where one
  // click covers both steps.
  const [busy, setBusy] = useState<null | "fetching" | "analysing">(null)
  const [cvPanelOpen, setCvPanelOpen] = useState(false)
  const [isExporting, setIsExporting] = useState(false)
  const pollRef = useRef<number | null>(null)
  const jobPollRef = useRef<number | null>(null)

  // A trial session is needed before the very first upload, since upload
  // now fires on file selection rather than on a submit the user reaches
  // after /try has already minted one.
  const sessionPromiseRef = useRef<Promise<void> | null>(null)
  useEffect(() => {
    if (isAuthenticated || trialSessionId) return
    void ensureIdentity().catch(() => {
      /* surfaced on the first upload attempt instead */
    })
    // ensureIdentity is a hoisted declaration and reads identity from the
    // store at call time, so it needs no dependency entry.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthenticated, trialSessionId])

  useEffect(() => {
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current)
      if (jobPollRef.current) window.clearInterval(jobPollRef.current)
    }
  }, [])

  function pollForText(cvId: string, fileName: string) {
    const startedAt = Date.now()
    if (pollRef.current) window.clearInterval(pollRef.current)
    pollRef.current = window.setInterval(async () => {
      if (Date.now() - startedAt > EXTRACT_TIMEOUT_MS) {
        if (pollRef.current) window.clearInterval(pollRef.current)
        setUpload({
          phase: "failed", fileName,
          message: "Extraction is taking longer than expected. Try uploading again.",
        })
        return
      }
      try {
        const raw = await getCvRawText(cvId)
        if (raw.canonicalText?.trim()) {
          if (pollRef.current) window.clearInterval(pollRef.current)
          setUpload({ phase: "ready", fileName, cvId, text: raw.canonicalText })
          setCvPanelOpen(true)
        }
      } catch {
        // 404 until extraction writes cv_raw_text — keep polling.
      }
    }, EXTRACT_POLL_MS)
  }

  /** Uploading on file selection races the bootstrap effect: a user who picks
   *  a file within the first moment would otherwise hit "Missing
   *  authentication token or trial session" (seen in e2e before this
   *  existed). Both paths share one in-flight promise — creating a second
   *  session would spend two of the five a client gets per hour. */
  function ensureIdentity(): Promise<void> {
    if (isAuthenticated) return Promise.resolve()
    if (useTrialStore.getState().trialSessionId) return Promise.resolve()
    if (!sessionPromiseRef.current) {
      sessionPromiseRef.current = createTrialSession()
        .then((session) => {
          setTrialSession(session.trialSessionId, session.expiresAt)
        })
        .catch((error) => {
          sessionPromiseRef.current = null // let the next attempt retry
          throw error
        })
    }
    return sessionPromiseRef.current
  }

  async function onFileSelected(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ""
    if (!file) return

    setResult(null)
    setUpload({ phase: "uploading", fileName: file.name })

    try {
      await ensureIdentity()
    } catch (error) {
      setUpload({
        phase: "failed", fileName: file.name,
        message: failureMessage(
          error,
          "This browser has used its free trial sessions for the hour. " +
            "Sign in to keep going, or try again later.",
          "We couldn't start a session for this upload."
        ),
      })
      return
    }

    let uploaded
    try {
      uploaded = await uploadCv(file)
    } catch (error) {
      setUpload({
        phase: "failed", fileName: file.name,
        message: failureMessage(
          error,
          "Upload limit reached for the hour. Try again later.",
          "We couldn't upload that file."
        ),
      })
      return
    }

    setUpload({ phase: "extracting", fileName: file.name, cvId: uploaded.cvId })
    pollForText(uploaded.cvId, file.name)
  }

  function stopJobPoll() {
    if (jobPollRef.current) window.clearInterval(jobPollRef.current)
    jobPollRef.current = null
  }

  /** Submit the URL and poll until the fetched text is available. Resolves
   *  with the text; rejects with a message already fit to show the user.
   *  Promise-shaped rather than setState-shaped because "Tailor my CV" has
   *  to fetch and then analyse within one click. */
  function fetchJobPostText(url: string): Promise<string> {
    return new Promise<string>((resolve, reject) => {
      ensureIdentity()
        .then(() => submitJobPostUrl(url))
        .then((accepted) => {
          const startedAt = Date.now()
          stopJobPoll()
          jobPollRef.current = window.setInterval(async () => {
            if (Date.now() - startedAt > JOB_FETCH_TIMEOUT_MS) {
              stopJobPoll()
              reject(
                new Error(
                  "Fetching that URL is taking longer than expected. " +
                    "Paste the description instead."
                )
              )
              return
            }
            try {
              const post = await getJobPost(accepted.jobPostId)
              if (post.status === "failed") {
                stopJobPoll()
                // job_fetch writes a specific reason for both SSRF
                // rejections and transport failures, and both already tell
                // the user to paste instead — surface it as-is.
                reject(
                  new Error(
                    post.errorMessage ?? "We couldn't fetch that job posting."
                  )
                )
                return
              }
              if (post.rawText?.trim()) {
                stopJobPoll()
                resolve(post.rawText)
              }
            } catch {
              // 404 until the worker writes the row — keep polling.
            }
          }, JOB_FETCH_POLL_MS)
        })
        .catch((error) =>
          reject(
            new Error(
              failureMessage(
                error,
                "URL-fetch limit reached for the hour. Try again later.",
                "We couldn't fetch that URL. Paste the description instead."
              )
            )
          )
        )
    })
  }

  async function onAnalyse() {
    if (upload.phase !== "ready") return
    setResult(null)
    setJobFetch({ phase: "idle" })

    // On the URL tab this is the only button: fetch first, then analyse,
    // without making the user press anything in between.
    let jobText = jobDescription.trim()
    if (jobSource === "url") {
      const url = jobUrl.trim()
      if (!url) return
      setBusy("fetching")
      try {
        jobText = (await fetchJobPostText(url)).trim()
      } catch (error) {
        setJobFetch({
          phase: "failed",
          message:
            error instanceof Error
              ? error.message
              : "We couldn't fetch that URL. Paste the description instead.",
        })
        setBusy(null)
        return
      }
      setJobDescription(jobText)
      setJobFetch({ phase: "fetched", url })
      // Show what will actually be analysed, and leave it editable.
      setJobSource("text")
    }

    if (jobText.length < MIN_JOB_TEXT_CHARS) {
      setJobFetch({
        phase: "failed",
        message:
          "That page didn't give us enough text to work with. " +
          "Paste the description instead.",
      })
      setBusy(null)
      return
    }

    setBusy("analysing")
    try {
      const rewrite = await createResumeRewrite({
        cvId: upload.cvId,
        jobDescription: jobText,
        targetTitle: targetTitle.trim() || undefined,
      })
      setResult(rewrite)
      setCvPanelOpen(false)
    } catch (error) {
      toast.error(
        failureMessage(
          error,
          "Rewrite limit reached for the hour. Try again later.",
          "The rewrite could not be completed."
        )
      )
    } finally {
      setBusy(null)
    }
  }

  // On the URL tab the URL is the input, so a description is not required
  // up front — "Tailor my CV" fetches it.
  const hasJobInput =
    jobSource === "url"
      ? jobUrl.trim().length > 0
      : jobDescription.trim().length >= MIN_JOB_TEXT_CHARS
  async function onDownloadPdf() {
    if (!result) return
    setIsExporting(true)
    try {
      const blob = await downloadResumePdf({
        tailoredResumeMarkdown: result.tailoredResumeMarkdown,
        fileName: targetTitle.trim()
          ? `Tailored CV - ${targetTitle.trim()}`
          : "Tailored CV",
      })
      // Object URL rather than a data: URI — a resume PDF is tens of KB
      // and this avoids base64-inflating it through the address bar.
      const url = URL.createObjectURL(blob)
      const link = document.createElement("a")
      link.href = url
      link.download = "tailored-cv.pdf"
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    } catch (error) {
      toast.error(
        failureMessage(
          error,
          "Export limit reached for the hour. Try again later.",
          "We couldn't build the PDF. Please try again."
        )
      )
    } finally {
      setIsExporting(false)
    }
  }

  const canAnalyse = upload.phase === "ready" && hasJobInput && !busy

  return (
    <div style={{ maxWidth: 1280, margin: "0 auto", padding: "40px 24px" }}>
      <header style={{ marginBottom: 32 }}>
        <h1 style={{ fontSize: 32, margin: "0 0 8px" }}>TAILOR YOUR CV</h1>
        <p style={{ margin: 0, maxWidth: "60ch", fontSize: 15, color: "var(--color-neutral-700)" }}>
          Your CV starts extracting the moment you choose a file. Add the role you
          want, and we&apos;ll show what already lands and what doesn&apos;t.
        </p>
      </header>

      <div style={{ display: "grid", gap: 24, gridTemplateColumns: "minmax(320px, 0.85fr) minmax(0, 1.15fr)" }}>
        {/* ── Left column: source ─────────────────────────────────── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
          <div className="card">
            <div className="card-title">1. YOUR CV</div>
            <div className="field">
              <label htmlFor="cv-file">CV (PDF or DOCX)</label>
              <input
                id="cv-file"
                type="file"
                accept=".pdf,.docx"
                className="input"
                data-testid="input-cv-file"
                onChange={onFileSelected}
              />
            </div>

            {upload.phase === "uploading" && (
              <div data-testid="status-uploading" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <p style={{ margin: 0, fontSize: 13, color: "var(--color-neutral-700)" }}>
                  Uploading {upload.fileName}…
                </p>
                <ProgressBar value={35} />
              </div>
            )}

            {upload.phase === "extracting" && (
              <div data-testid="status-extracting" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <p style={{ margin: 0, fontSize: 13, color: "var(--color-neutral-700)" }}>
                  Extracting text from {upload.fileName}…
                </p>
                <ProgressBar value={70} />
              </div>
            )}

            {upload.phase === "ready" && (
              <div
                data-testid="status-ready"
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 12,
                  background: "var(--color-bg)",
                  border: "1px solid var(--color-divider)",
                  padding: 12,
                }}
              >
                <div style={{ minWidth: 0 }}>
                  <p style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>{upload.fileName}</p>
                  <p style={{ margin: 0, fontSize: 12, color: "var(--color-neutral-700)" }}>
                    {upload.text.length.toLocaleString()} characters extracted
                  </p>
                </div>
                <button
                  type="button"
                  className="btn btn-secondary"
                  data-testid="button-view-extracted"
                  onClick={() => setCvPanelOpen(true)}
                >
                  View extracted CV
                </button>
              </div>
            )}

            {upload.phase === "failed" && (
              <p data-testid="status-upload-failed" style={{ margin: 0, fontSize: 13, color: "var(--color-accent-700)" }}>
                {upload.message}
              </p>
            )}
          </div>

          <div className="card">
            <div className="card-title">2. THE ROLE YOU WANT</div>
            <div className="field">
              <label htmlFor="target-title">Target title (optional)</label>
              <input
                id="target-title"
                className="input"
                data-testid="input-target-title"
                placeholder="e.g. Senior Product Designer"
                value={targetTitle}
                onChange={(e) => setTargetTitle(e.target.value)}
              />
            </div>

            <SegmentedControl
              name="job-source"
              value={jobSource}
              onChange={setJobSource}
              options={[
                { value: "text", label: "Paste description", testId: "tab-job-text" },
                { value: "url", label: "From a URL", testId: "tab-job-url" },
              ]}
            />

            {jobSource === "text" ? (
              <div className="field" style={{ marginTop: 16 }}>
                <label htmlFor="job-text">Job description</label>
                <textarea
                  id="job-text"
                  rows={10}
                  className="input"
                  data-testid="input-job-description"
                  placeholder="Paste the job posting text here…"
                  value={jobDescription}
                  onChange={(e) => setJobDescription(e.target.value)}
                />
                {jobFetch.phase === "fetched" && (
                  <p data-testid="status-job-fetched" style={{ margin: "6px 0 0", fontSize: 12, color: "var(--color-neutral-700)" }}>
                    Fetched from {jobFetch.url}. This is the text the analysis
                    reads — trim anything the page brought along with it.
                  </p>
                )}
                <p style={{ margin: "6px 0 0", fontSize: 12, color: "var(--color-neutral-700)" }}>
                  {jobDescription.trim().length < 40
                    ? `${40 - jobDescription.trim().length} more characters needed`
                    : "Job description looks ready"}
                </p>
              </div>
            ) : (
              <div className="field" style={{ marginTop: 16 }}>
                <label htmlFor="job-url">Job posting URL</label>
                <input
                  id="job-url"
                  type="url"
                  className="input"
                  data-testid="input-job-url"
                  placeholder="https://example.com/careers/role"
                  value={jobUrl}
                  onChange={(e) => setJobUrl(e.target.value)}
                />
                {jobFetch.phase === "failed" && (
                  <p data-testid="status-job-fetch-failed" style={{ margin: "6px 0 0", fontSize: 13, color: "var(--color-accent-700)" }}>
                    {jobFetch.message}
                  </p>
                )}
                <p style={{ margin: "6px 0 0", fontSize: 12, color: "var(--color-neutral-700)" }}>
                  Tailor my CV fetches the page, drops the text into the box
                  next door so you can see and edit exactly what gets
                  analysed, then runs the analysis. Sites that block
                  automated fetching, and private or internal addresses, are
                  refused — paste the description instead.
                </p>
              </div>
            )}
            <button
              type="button"
              className="btn btn-primary btn-block"
              style={{ justifyContent: "center", textAlign: "center" }}
              data-testid="button-analyse"
              disabled={!canAnalyse}
              onClick={onAnalyse}
            >
              {busy === "fetching"
                ? "Fetching job post…"
                : busy === "analysing"
                  ? "Analysing…"
                  : "Tailor my CV"}
            </button>
          </div>
        </div>

        {/* ── Right column: results ───────────────────────────────── */}
        <div>
          {busy && (
            <div className="card" data-testid="state-loading">
              <ProgressBar value={60} />
              <p style={{ margin: 0, textAlign: "center", fontSize: 13, color: "var(--color-neutral-700)" }}>
                {busy === "fetching"
                  ? "Fetching the job post…"
                  : "Reading the role against your experience…"}
              </p>
            </div>
          )}

          {!busy && !result && (
            <div
              className="card"
              data-testid="state-empty"
              style={{ minHeight: 420, alignItems: "center", justifyContent: "center", textAlign: "center" }}
            >
              <h2 style={{ fontSize: 20, margin: 0 }}>Your tailored CV appears here</h2>
              <p style={{ margin: "8px 0 0", maxWidth: 360, fontSize: 13, color: "var(--color-neutral-700)" }}>
                Add your CV and the job description. We&apos;ll show the fit score,
                what matches, what&apos;s transferable, and what&apos;s missing.
              </p>
            </div>
          )}

          {!busy && result && (
            <div data-testid="state-complete" style={{ display: "flex", flexDirection: "column", gap: 24 }}>
              <div className="card" style={{ flexDirection: "row", alignItems: "center", gap: 24, flexWrap: "wrap" }}>
                <div style={{ width: 140 }} data-testid="metric-ats-score">
                  <ScoreBar score={result.stats.atsScore} />
                </div>
                <div style={{ minWidth: 0 }}>
                  <Tag variant="accent" data-testid="text-match-label" >
                    {result.stats.matchLabel}
                  </Tag>
                  <p style={{ margin: "10px 0 0", fontSize: 13, color: "var(--color-neutral-700)" }}>
                    {result.stats.matchedSkills.length} matched ·{" "}
                    {result.stats.transferableSkills.length} transferable ·{" "}
                    {result.stats.missingSkills.length} missing
                  </p>
                  {result.stats.sameOccupation === false &&
                    result.stats.cvOccupation &&
                    result.stats.jobOccupation && (
                      <p
                        data-testid="text-occupation-gap"
                        style={{ margin: "8px 0 0", fontSize: 13, fontWeight: 600, color: "var(--color-accent-700)" }}
                      >
                        Career change: your CV evidences{" "}
                        {result.stats.cvOccupation}, this role is{" "}
                        {result.stats.jobOccupation}. The score is capped
                        for a different profession.
                      </p>
                    )}
                </div>
              </div>

              <div className="card">
                <div className="card-title">Matching criteria</div>
                <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
                  <SkillList title="Matched" tone="matched" testId="list-matched"
                             items={result.stats.matchedSkills} />
                  <SkillList title="Transferable" tone="transferable" testId="list-transferable"
                             items={result.stats.transferableSkills} />
                  <SkillList title="Not evidenced" tone="missing" testId="list-missing"
                             items={result.stats.missingSkills} />
                  <SkillList title="Priority keywords" tone="keyword" testId="list-keywords"
                             items={result.stats.priorityKeywords} />
                </div>
              </div>

              {result.matchNotes.length > 0 && (
                <div className="card">
                  <div className="card-title">Evidence-based match notes</div>
                  <ul data-testid="list-match-notes" style={{ margin: 0, paddingLeft: 20, fontSize: 13, display: "flex", flexDirection: "column", gap: 8 }}>
                    {result.matchNotes.map((note) => <li key={note}>{note}</li>)}
                  </ul>
                </div>
              )}

              {result.informationNeeded.length > 0 && (
                <div className="card">
                  <div className="card-title">Information that would strengthen this</div>
                  <ul data-testid="list-information-needed" style={{ margin: 0, paddingLeft: 20, fontSize: 13, display: "flex", flexDirection: "column", gap: 8 }}>
                    {result.informationNeeded.map((q) => <li key={q}>{q}</li>)}
                  </ul>
                </div>
              )}

              <div className="card">
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16 }}>
                  <div className="card-title" style={{ margin: 0 }}>Tailored CV</div>
                  <button
                    type="button"
                    className="btn btn-primary"
                    data-testid="button-download-pdf"
                    disabled={isExporting}
                    onClick={onDownloadPdf}
                  >
                    {isExporting ? "Building PDF…" : "Download PDF"}
                  </button>
                </div>
                <pre
                  data-testid="text-tailored-cv"
                  style={{
                    maxHeight: 520,
                    overflow: "auto",
                    whiteSpace: "pre-wrap",
                    background: "var(--color-bg)",
                    border: "1px solid var(--color-divider)",
                    padding: 16,
                    fontSize: 13,
                    margin: 0,
                  }}
                >
                  {result.tailoredResumeMarkdown}
                </pre>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Left slide-over: the extracted CV text ─────────────────── */}
      {cvPanelOpen && upload.phase === "ready" && (
        <div style={{ position: "fixed", inset: 0, zIndex: 50, display: "flex" }} data-testid="modal-extracted-cv">
          <button
            type="button"
            aria-label="Close extracted CV"
            data-testid="button-close-extracted-backdrop"
            style={{ position: "absolute", inset: 0, background: "color-mix(in srgb, var(--color-neutral-900) 55%, transparent)", border: 0, cursor: "pointer" }}
            onClick={() => setCvPanelOpen(false)}
          />
          <aside
            style={{
              position: "relative",
              display: "flex",
              flexDirection: "column",
              height: "100%",
              width: "100%",
              maxWidth: 560,
              borderRight: "1px solid var(--color-divider)",
              background: "var(--color-bg)",
              boxShadow: "var(--shadow-lg)",
            }}
          >
            <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16, borderBottom: "1px solid var(--color-divider)", padding: 16 }}>
              <div style={{ minWidth: 0 }}>
                <h2 style={{ fontSize: 20, margin: 0 }}>Extracted CV</h2>
                <p style={{ margin: "4px 0 0", fontSize: 12, color: "var(--color-neutral-700)" }}>
                  {upload.fileName} · {upload.text.length.toLocaleString()} characters
                </p>
              </div>
              <button
                type="button"
                className="btn btn-ghost"
                data-testid="button-close-extracted"
                onClick={() => setCvPanelOpen(false)}
              >
                Close
              </button>
            </div>
            <div style={{ flex: 1, overflow: "auto", padding: 16 }}>
              <pre
                data-testid="text-extracted-cv"
                style={{ whiteSpace: "pre-wrap", fontFamily: "monospace", fontSize: 12, lineHeight: 1.6, margin: 0 }}
              >
                {upload.text}
              </pre>
            </div>
            <div style={{ borderTop: "1px solid var(--color-divider)", padding: 12 }}>
              <p style={{ margin: 0, fontSize: 12, color: "var(--color-neutral-700)" }}>
                This is exactly the text the analysis reads. If something is missing
                or garbled here, it will be missing from the tailored CV too.
              </p>
            </div>
          </aside>
        </div>
      )}
    </div>
  )
}

function ProgressBar({ value }: { value: number }) {
  return (
    <div style={{ height: 6, background: "var(--color-neutral-300)" }}>
      <div style={{ height: "100%", width: `${value}%`, background: "var(--color-accent)" }} />
    </div>
  )
}
