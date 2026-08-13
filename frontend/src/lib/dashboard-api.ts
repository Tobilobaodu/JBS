import { apiFetch } from "@/lib/api"

export type CvFileListItem = {
  id: string
  originalFilename: string
  mimeType: string
  fileSizeBytes: number
  status: string
  uploadStatus: string
  processingStatus: string
  jobStatus: string | null
  createdAt: string
  updatedAt: string
}

export type CvListResponse = {
  items: CvFileListItem[]
  total: number
  limit: number
  offset: number
}

export function listCvs(limit = 20, offset = 0) {
  return apiFetch<CvListResponse>(`/cvs?limit=${limit}&offset=${offset}`)
}

export type JobPostProfileSummary = {
  jobTitle: string | null
  employer: string | null
}

export type JobPostListItem = {
  id: string
  sourceType: string
  sourceUrl: string | null
  status: string
  errorMessage: string | null
  createdAt: string
  updatedAt: string
  profile: JobPostProfileSummary | null
}

export type JobPostListResponse = {
  items: JobPostListItem[]
  total: number
  limit: number
  offset: number
}

export function listJobPosts(limit = 20, offset = 0) {
  return apiFetch<JobPostListResponse>(`/job-posts?limit=${limit}&offset=${offset}`)
}

export type MatchListItem = {
  id: string
  jobPostId: string
  jobTitle: string | null
  employer: string | null
  status: string
  score: number | null
  createdAt: string
  completedAt: string | null
}

export type MatchListResponse = {
  items: MatchListItem[]
  total: number
  limit: number
  offset: number
}

export function listMatches(limit = 20, offset = 0) {
  return apiFetch<MatchListResponse>(`/matches?limit=${limit}&offset=${offset}`)
}

export type CoverLetterWorkflowListItem = {
  id: string
  jobPostId: string
  jobTitle: string | null
  employer: string | null
  status: string
  currentStep: number
  createdAt: string
}

export type CoverLetterWorkflowListResponse = {
  items: CoverLetterWorkflowListItem[]
  total: number
  limit: number
  offset: number
}

export function listCoverLetterWorkflows(limit = 20, offset = 0) {
  return apiFetch<CoverLetterWorkflowListResponse>(
    `/cover-letters?limit=${limit}&offset=${offset}`
  )
}
