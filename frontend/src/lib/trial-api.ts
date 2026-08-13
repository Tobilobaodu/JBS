import { apiFetch, apiFetchBlob } from "@/lib/api"

export type TrialSessionCreated = {
  trialSessionId: string
  expiresAt: string
}

export function createTrialSession() {
  return apiFetch<TrialSessionCreated>("/trial-sessions", { method: "POST" })
}

export type ClaimTrialResult = {
  claimed: boolean
  cvFilesReassigned: number
  jobPostsReassigned: number
  matchRunsReassigned: number
}

/** Call immediately after register/login when a trial session is active — reassigns its data to the new account. Requires the account's Bearer token (get_current_user-only). */
export function claimTrialSession(trialSessionId: string) {
  return apiFetch<ClaimTrialResult>("/auth/claim-trial", {
    method: "POST",
    body: { trialSessionId },
  })
}

export type CvUploadAccepted = {
  cvId: string
  processingJobId: string
  status: string
  filename: string
  fileSize: number
  mimeType: string
}

export function uploadCv(file: File) {
  const formData = new FormData()
  formData.append("file", file)
  return apiFetch<CvUploadAccepted>("/cvs", { method: "POST", body: formData })
}

export type JobPostAccepted = {
  jobPostId: string
  processingJobId: string
}

export function submitJobPostUrl(url: string) {
  return apiFetch<JobPostAccepted>("/job-posts/url", {
    method: "POST",
    body: { url },
  })
}

export function submitJobPostText(text: string) {
  return apiFetch<JobPostAccepted>("/job-posts/text", {
    method: "POST",
    body: { text },
  })
}

export type ProcessingJob = {
  id: string
  jobType: string
  sourceEntityType: string
  sourceEntityId: string
  status: "queued" | "processing" | "completed" | "failed" | "retrying"
  retryCount: number
  lastError: string | null
  createdAt: string
  completedAt: string | null
}

/** GET /jobs/{jobId} — the single source of truth for async job status; poll here, never infer from a domain resource's own status field. */
export function getJob(jobId: string) {
  return apiFetch<ProcessingJob>(`/jobs/${jobId}`)
}

export type ParsedCvProfile = {
  cvId: string
  profileVersionId: string
  versionNumber: number
  structuredPayload: {
    basics?: { summary?: string }
    [key: string]: unknown
  }
}

export function getParsedCvProfile(cvId: string) {
  return apiFetch<ParsedCvProfile>(`/cvs/${cvId}/parsed-profile`)
}

export type JobPostProfile = {
  jobTitle: string | null
  employer: string | null
  location: string | null
  requiredSkills: string[] | null
  preferredSkills: string[] | null
  responsibilities: string[] | null
  qualifications: string[] | null
  keywords: string[] | null
  seniority: string | null
  confidence: number | null
}

export type JobPostDetail = {
  id: string
  sourceType: string
  sourceUrl: string | null
  status: string
  errorMessage: string | null
  profile: JobPostProfile | null
}

export function getJobPost(jobPostId: string) {
  return apiFetch<JobPostDetail>(`/job-posts/${jobPostId}`)
}

export type MatchAccepted = {
  matchId: string
  processingJobId: string
}

export function createMatch(cvProfileVersionId: string, jobPostId: string) {
  return apiFetch<MatchAccepted>("/matches", {
    method: "POST",
    body: { cvProfileVersionId, jobPostId },
  })
}

export type MatchResult = {
  id: string
  status: string
  score: number | null
  supportedCount: number | null
  partialCount: number | null
  unsupportedCount: number | null
  totalRequirements: number | null
  summaryAnalysis: string | null
}

export function getMatch(matchId: string) {
  return apiFetch<MatchResult>(`/matches/${matchId}`)
}

export type ProcessingJobRef = {
  jobId: string
  status: string
}

export function createTailoredCv(matchId: string) {
  return apiFetch<ProcessingJobRef>(`/matches/${matchId}/tailored-cv`, {
    method: "POST",
  })
}

export type TailoredCvSection = {
  id: string
  sectionType: string
  contentText: string
  orderIndex: number
}

export type TailoredCvDraft = {
  id: string
  matchRunId: string
  versionNumber: number
  status: string
  sections: TailoredCvSection[]
  improvementChecklist: string[] | null
}

export function getTailoredCvDraft(draftId: string) {
  return apiFetch<TailoredCvDraft>(`/tailored-cvs/${draftId}`)
}

/** Required before export — app/api/v1/exports.py rejects a non-'approved' draft with 409. */
export function approveTailoredCv(draftId: string) {
  return apiFetch<TailoredCvDraft>(`/tailored-cvs/${draftId}/approve`, {
    method: "POST",
  })
}

export type ExportRequestOut = {
  id: string
  status: string
  format: string
}

export function createCvExport(draftId: string, templateId?: string) {
  return apiFetch<ExportRequestOut>(`/exports/cv/${draftId}`, {
    method: "POST",
    body: templateId ? { templateId } : {},
  })
}

export function getExport(exportId: string) {
  return apiFetch<ExportRequestOut>(`/exports/${exportId}`)
}

/**
 * The download endpoint is re-checked (auth/trial header) on every request —
 * it can't be a plain <a href>, which would send no identity header at all.
 * Fetches the file with the right header, then triggers a normal browser
 * save via a temporary object URL.
 */
export async function downloadExport(exportId: string, filename: string) {
  const blob = await apiFetchBlob(`/exports/${exportId}/download`)
  const url = URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

export type ExportTemplate = {
  id: string
  name: string
  description: string
}

export function listExportTemplates() {
  return apiFetch<ExportTemplate[]>("/exports/templates")
}

export function exportCoverLetter(workflowId: string, templateId?: string) {
  return apiFetch<ExportRequestOut>(`/exports/cover-letter/${workflowId}`, {
    method: "POST",
    body: templateId ? { templateId } : {},
  })
}

export function exportApplicationPack(
  tailoredCvDraftId: string,
  coverLetterWorkflowId: string,
  templateId?: string
) {
  return apiFetch<ExportRequestOut>("/exports/application-pack", {
    method: "POST",
    body: {
      tailoredCvDraftId,
      coverLetterWorkflowId,
      ...(templateId ? { templateId } : {}),
    },
  })
}

/** Derives a PDF version of an already-downloaded docx export — must call
 * downloadExport() on the source export first (see exports.py::export_pdf's
 * precondition). Returns a new Export, polled/downloaded the same way. */
export function exportPdf(exportId: string) {
  return apiFetch<ExportRequestOut>(`/exports/${exportId}/pdf`, { method: "POST" })
}

export type AtsCheckItem = {
  checkType: string
  passed: boolean
  severity: string
  detail: string
}

export type AtsReadinessCheckResponse = {
  id: string
  cvId: string
  cvProfileVersionId: string | null
  overallScore: number
  contactInfoParseable: boolean | null
  checks: AtsCheckItem[]
  createdAt: string
}

export function triggerAtsCheck(cvId: string) {
  return apiFetch<ProcessingJobRef>(`/cvs/${cvId}/ats-check`, {
    method: "POST",
  })
}

/** 404s until a check has run — callers should treat that as "no result yet", not an error. */
export function getAtsCheck(cvId: string) {
  return apiFetch<AtsReadinessCheckResponse>(`/cvs/${cvId}/ats-check`)
}

export type JobPostCollection = {
  id: string
  name: string
  jobPostIds: string[]
  createdAt: string
  updatedAt: string
}

export function createJobPostCollection(name: string, jobPostIds: string[]) {
  return apiFetch<JobPostCollection>("/job-post-collections", {
    method: "POST",
    body: { name, jobPostIds },
  })
}

export function listJobPostCollections() {
  return apiFetch<JobPostCollection[]>("/job-post-collections")
}

export function triggerCoverageReport(collectionId: string, cvId: string) {
  return apiFetch<ProcessingJobRef>(
    `/job-post-collections/${collectionId}/coverage-report`,
    { method: "POST", body: { cvId } }
  )
}

export type AggregateGap = {
  requirementTextCluster: string
  recurrenceCount: number
  recurrenceRatio: number
  affectedJobPostIds: string[]
  currentSupportLevelDistribution: Record<string, number>
}

export type CoverageReport = {
  id: string
  cvProfileVersionId: string
  collectionId: string
  matchRunIds: string[]
  status: string
  aggregateGaps: AggregateGap[]
  skippedJobPostIds: string[] | null
  createdAt: string
  completedAt: string | null
}

export function getCoverageReport(reportId: string) {
  return apiFetch<CoverageReport>(`/coverage-reports/${reportId}`)
}
