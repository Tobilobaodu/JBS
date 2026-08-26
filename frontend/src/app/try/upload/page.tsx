"use client"

import { useEffect, useRef, useState } from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Progress } from "@/components/ui/progress"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
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

/** Score ring — same read as the stat card in the reference app: the
 *  number is the headline, the ring is secondary reinforcement. */
function ScoreRing({ score }: { score: number }) {
  const radius = 45
  const circumference = 2 * Math.PI * radius
  const clamped = Math.max(0, Math.min(score, 100))
  const offset = circumference - (clamped / 100) * circumference
  return (
    <div className="relative h-28 w-28 shrink-0" data-testid="metric-ats-score">
      <svg className="h-full w-full -rotate-90" viewBox="0 0 116 116" aria-hidden="true">
        <circle cx="58" cy="58" r={radius} fill="none" stroke="currentColor"
                className="text-muted" strokeWidth="8" />
        <circle cx="58" cy="58" r={radius} fill="none" stroke="currentColor"
                className="text-primary" strokeLinecap="round" strokeWidth="8"
                strokeDasharray={circumference} strokeDashoffset={offset} />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-3xl font-bold tabular-nums">{Math.round(clamped)}</span>
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
          out of 100
        </span>
      </div>
    </div>
  )
}

function SkillList({
  title, items, tone, testId,
}: {
  title: string
  items: string[]
  tone: "matched" | "transferable" | "missing" | "keyword"
  testId: string
}) {
  if (!items.length) return null
  const toneClass = {
    matched: "border-emerald-600/30 bg-emerald-600/10 text-emerald-800 dark:text-emerald-300",
    transferable: "border-amber-600/30 bg-amber-600/10 text-amber-800 dark:text-amber-300",
    missing: "border-destructive/30 bg-destructive/10 text-destructive",
    keyword: "border-primary/30 bg-primary/10 text-primary",
  }[tone]
  return (
    <div data-testid={testId}>
      <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        {title} <span className="ml-1 tabular-nums">({items.length})</span>
      </h4>
      <div className="flex flex-wrap gap-1.5">
        {items.map((item) => (
          <span key={item}
                className={`inline-flex rounded-md border px-2 py-1 text-xs font-medium ${toneClass}`}>
            {item}
          </span>
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
    <div className="mx-auto max-w-7xl px-4 py-10">
      <header className="mb-8">
        <h1 className="text-3xl font-bold tracking-tight">Tailor your CV</h1>
        <p className="mt-2 max-w-2xl text-muted-foreground">
          Your CV starts extracting the moment you choose a file. Add the role you
          want, and we&apos;ll show what already lands and what doesn&apos;t.
        </p>
      </header>

      <div className="grid gap-6 lg:grid-cols-[minmax(320px,0.85fr)_minmax(0,1.15fr)]">
        {/* ── Left column: source ─────────────────────────────────── */}
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">1. Your CV</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-2">
                <Label htmlFor="cv-file">CV (PDF or DOCX)</Label>
                <Input id="cv-file" type="file" accept=".pdf,.docx"
                       data-testid="input-cv-file" onChange={onFileSelected} />
              </div>

              {upload.phase === "uploading" && (
                <div data-testid="status-uploading" className="space-y-2">
                  <p className="text-sm text-muted-foreground">
                    Uploading {upload.fileName}…
                  </p>
                  <Progress value={35} />
                </div>
              )}

              {upload.phase === "extracting" && (
                <div data-testid="status-extracting" className="space-y-2">
                  <p className="text-sm text-muted-foreground">
                    Extracting text from {upload.fileName}…
                  </p>
                  <Progress value={70} />
                </div>
              )}

              {upload.phase === "ready" && (
                <div data-testid="status-ready"
                     className="flex items-center justify-between gap-3 rounded-md border bg-muted/40 p-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">{upload.fileName}</p>
                    <p className="text-xs text-muted-foreground">
                      {upload.text.length.toLocaleString()} characters extracted
                    </p>
                  </div>
                  <Button type="button" variant="outline" size="sm"
                          data-testid="button-view-extracted"
                          onClick={() => setCvPanelOpen(true)}>
                    View extracted CV
                  </Button>
                </div>
              )}

              {upload.phase === "failed" && (
                <p data-testid="status-upload-failed" className="text-sm text-destructive">
                  {upload.message}
                </p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">2. The role you want</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-2">
                <Label htmlFor="target-title">Target title (optional)</Label>
                <Input id="target-title" data-testid="input-target-title"
                       placeholder="e.g. Senior Product Designer"
                       value={targetTitle}
                       onChange={(e) => setTargetTitle(e.target.value)} />
              </div>
              <Tabs value={jobSource}
                    onValueChange={(v) => setJobSource(v as "text" | "url")}>
                <TabsList className="grid w-full grid-cols-2">
                  <TabsTrigger value="text" data-testid="tab-job-text">
                    Paste description
                  </TabsTrigger>
                  <TabsTrigger value="url" data-testid="tab-job-url">
                    From a URL
                  </TabsTrigger>
                </TabsList>

                <TabsContent value="text" className="mt-4">
                  <div className="grid gap-2">
                    <Label htmlFor="job-text">Job description</Label>
                    <Textarea id="job-text" rows={10} data-testid="input-job-description"
                              placeholder="Paste the job posting text here…"
                              value={jobDescription}
                              onChange={(e) => setJobDescription(e.target.value)} />
                    {jobFetch.phase === "fetched" && (
                      <p data-testid="status-job-fetched"
                         className="text-xs text-muted-foreground">
                        Fetched from {jobFetch.url}. This is the text the analysis
                        reads — trim anything the page brought along with it.
                      </p>
                    )}
                    <p className="text-xs text-muted-foreground">
                      {jobDescription.trim().length < 40
                        ? `${40 - jobDescription.trim().length} more characters needed`
                        : "Job description looks ready"}
                    </p>
                  </div>
                </TabsContent>

                <TabsContent value="url" className="mt-4">
                  <div className="grid gap-2">
                    <Label htmlFor="job-url">Job posting URL</Label>
                    <Input id="job-url" type="url" data-testid="input-job-url"
                           placeholder="https://example.com/careers/role"
                           value={jobUrl}
                           onChange={(e) => setJobUrl(e.target.value)} />
                    {jobFetch.phase === "failed" && (
                      <p data-testid="status-job-fetch-failed"
                         className="text-sm text-destructive">
                        {jobFetch.message}
                      </p>
                    )}
                    <p className="text-xs text-muted-foreground">
                      Tailor my CV fetches the page, drops the text into the box
                      next door so you can see and edit exactly what gets
                      analysed, then runs the analysis. Sites that block
                      automated fetching, and private or internal addresses, are
                      refused — paste the description instead.
                    </p>
                  </div>
                </TabsContent>
              </Tabs>
              <Button type="button" size="lg" className="w-full"
                      data-testid="button-analyse"
                      disabled={!canAnalyse} onClick={onAnalyse}>
                {busy === "fetching"
                  ? "Fetching job post…"
                  : busy === "analysing"
                    ? "Analysing…"
                    : "Tailor my CV"}
              </Button>
            </CardContent>
          </Card>
        </div>

        {/* ── Right column: results ───────────────────────────────── */}
        <div>
          {busy && (
            <Card data-testid="state-loading">
              <CardContent className="space-y-4 py-10">
                <Progress value={60} />
                <p className="text-center text-sm text-muted-foreground">
                  {busy === "fetching"
                    ? "Fetching the job post…"
                    : "Reading the role against your experience…"}
                </p>
              </CardContent>
            </Card>
          )}

          {!busy && !result && (
            <Card data-testid="state-empty">
              <CardContent className="flex min-h-[420px] flex-col items-center justify-center text-center">
                <h2 className="text-xl font-semibold">Your tailored CV appears here</h2>
                <p className="mt-2 max-w-sm text-sm text-muted-foreground">
                  Add your CV and the job description. We&apos;ll show the fit score,
                  what matches, what&apos;s transferable, and what&apos;s missing.
                </p>
              </CardContent>
            </Card>
          )}

          {!busy && result && (
            <div data-testid="state-complete" className="space-y-6">
              <Card>
                <CardContent className="flex flex-col gap-6 pt-6 sm:flex-row sm:items-center">
                  <ScoreRing score={result.stats.atsScore} />
                  <div className="min-w-0">
                    <Badge data-testid="text-match-label">{result.stats.matchLabel}</Badge>
                    <p className="mt-3 text-sm text-muted-foreground">
                      {result.stats.matchedSkills.length} matched ·{" "}
                      {result.stats.transferableSkills.length} transferable ·{" "}
                      {result.stats.missingSkills.length} missing
                    </p>
                    {result.stats.sameOccupation === false &&
                      result.stats.cvOccupation &&
                      result.stats.jobOccupation && (
                        <p data-testid="text-occupation-gap"
                           className="mt-2 text-sm font-medium text-amber-700 dark:text-amber-400">
                          Career change: your CV evidences{" "}
                          {result.stats.cvOccupation}, this role is{" "}
                          {result.stats.jobOccupation}. The score is capped
                          for a different profession.
                        </p>
                      )}
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader><CardTitle className="text-base">Matching criteria</CardTitle></CardHeader>
                <CardContent className="space-y-5">
                  <SkillList title="Matched" tone="matched" testId="list-matched"
                             items={result.stats.matchedSkills} />
                  <SkillList title="Transferable" tone="transferable" testId="list-transferable"
                             items={result.stats.transferableSkills} />
                  <SkillList title="Not evidenced" tone="missing" testId="list-missing"
                             items={result.stats.missingSkills} />
                  <SkillList title="Priority keywords" tone="keyword" testId="list-keywords"
                             items={result.stats.priorityKeywords} />
                </CardContent>
              </Card>

              {result.matchNotes.length > 0 && (
                <Card>
                  <CardHeader><CardTitle className="text-base">Evidence-based match notes</CardTitle></CardHeader>
                  <CardContent>
                    <ul data-testid="list-match-notes" className="list-disc space-y-2 pl-5 text-sm">
                      {result.matchNotes.map((note) => <li key={note}>{note}</li>)}
                    </ul>
                  </CardContent>
                </Card>
              )}

              {result.informationNeeded.length > 0 && (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-base">Information that would strengthen this</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <ul data-testid="list-information-needed" className="list-disc space-y-2 pl-5 text-sm">
                      {result.informationNeeded.map((q) => <li key={q}>{q}</li>)}
                    </ul>
                  </CardContent>
                </Card>
              )}

              <Card>
                <CardHeader className="flex flex-row items-center justify-between gap-4 space-y-0">
                  <CardTitle className="text-base">Tailored CV</CardTitle>
                  <Button type="button" size="sm" data-testid="button-download-pdf"
                          disabled={isExporting} onClick={onDownloadPdf}>
                    {isExporting ? "Building PDF…" : "Download PDF"}
                  </Button>
                </CardHeader>
                <CardContent>
                  <pre data-testid="text-tailored-cv"
                       className="max-h-[520px] overflow-auto whitespace-pre-wrap rounded-md bg-muted/40 p-4 text-sm">
                    {result.tailoredResumeMarkdown}
                  </pre>
                </CardContent>
              </Card>
            </div>
          )}
        </div>
      </div>

      {/* ── Left slide-over: the extracted CV text ─────────────────── */}
      {cvPanelOpen && upload.phase === "ready" && (
        <div className="fixed inset-0 z-50 flex" data-testid="modal-extracted-cv">
          <button type="button" aria-label="Close extracted CV"
                  data-testid="button-close-extracted-backdrop"
                  className="absolute inset-0 bg-black/50"
                  onClick={() => setCvPanelOpen(false)} />
          <aside className="relative flex h-full w-full max-w-xl flex-col border-r bg-background shadow-xl">
            <div className="flex items-start justify-between gap-4 border-b p-4">
              <div className="min-w-0">
                <h2 className="truncate text-lg font-semibold">Extracted CV</h2>
                <p className="text-xs text-muted-foreground">
                  {upload.fileName} · {upload.text.length.toLocaleString()} characters
                </p>
              </div>
              <Button type="button" variant="ghost" size="sm"
                      data-testid="button-close-extracted"
                      onClick={() => setCvPanelOpen(false)}>
                Close
              </Button>
            </div>
            <div className="flex-1 overflow-auto p-4">
              <pre data-testid="text-extracted-cv"
                   className="whitespace-pre-wrap font-mono text-xs leading-relaxed">
                {upload.text}
              </pre>
            </div>
            <div className="border-t p-3">
              <p className="text-xs text-muted-foreground">
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
