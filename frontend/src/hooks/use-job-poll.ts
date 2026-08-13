import { useQuery } from "@tanstack/react-query"
import { getJob, type ProcessingJob } from "@/lib/trial-api"

const TERMINAL_STATUSES = new Set(["completed", "failed"])

/**
 * Polls GET /jobs/{jobId} — the backend's single source of truth for async
 * job status (see app/api/v1/jobs.py) — until it reaches a terminal state.
 * Pass jobId=null to skip polling (e.g. before the job has been created).
 */
export function useJobPoll(jobId: string | null) {
  const query = useQuery<ProcessingJob>({
    queryKey: ["job", jobId],
    queryFn: () => getJob(jobId as string),
    enabled: jobId !== null,
    refetchInterval: (q) => {
      const status = q.state.data?.status
      return status && TERMINAL_STATUSES.has(status) ? false : 2000
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
