import { useQuery } from "@tanstack/react-query"
import { getJob, type ProcessingJob } from "@/lib/trial-api"

const TERMINAL_STATUSES = new Set(["completed", "failed"])
const POLL_INTERVAL_MIN_MS = 2000
const POLL_INTERVAL_MAX_MS = 15000

/**
 * Polls GET /jobs/{jobId} — the backend's single source of truth for async
 * job status (see app/api/v1/jobs.py) — until it reaches a terminal state.
 * Pass jobId=null to skip polling (e.g. before the job has been created).
 *
 * Exponential backoff (2s -> 15s cap) rather than a fixed interval — most
 * jobs here run tens of seconds to minutes (docling/textract extraction,
 * LLM generation), so polling every 2s for the whole duration is mostly
 * wasted requests; the addendum's frontend checklist calls this out
 * directly ("Use exponential backoff for processing-status polling").
 */
export function useJobPoll(jobId: string | null) {
  const query = useQuery<ProcessingJob>({
    queryKey: ["job", jobId],
    queryFn: () => getJob(jobId as string),
    enabled: jobId !== null,
    refetchInterval: (q) => {
      const status = q.state.data?.status
      if (status && TERMINAL_STATUSES.has(status)) return false
      const attempt = q.state.dataUpdateCount
      return Math.min(POLL_INTERVAL_MIN_MS * 2 ** attempt, POLL_INTERVAL_MAX_MS)
    },
  })

  return {
    job: query.data,
    isPolling: jobId !== null && !TERMINAL_STATUSES.has(query.data?.status ?? ""),
    isCompleted: query.data?.status === "completed",
    isFailed: query.data?.status === "failed",
    error: query.error,
  }
}
