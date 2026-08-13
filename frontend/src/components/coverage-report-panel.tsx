"use client"

import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { errorMessage } from "@/lib/api"
import { listCvs } from "@/lib/dashboard-api"
import {
  createJobPostCollection,
  triggerCoverageReport,
  getCoverageReport,
} from "@/lib/trial-api"
import { useJobPoll } from "@/hooks/use-job-poll"

/**
 * Sprint 5's multi-job-post coverage reporting (job-post-collections +
 * coverage-reports) had zero dashboard UI before this. Self-contained: pick
 * a CV, create a collection from the selected job posts, trigger the
 * report, poll, render aggregate gaps. Reuses useJobPoll (ProcessingJobRef)
 * the same way ATS-check does.
 */
export function CoverageReportPanel({
  selectedJobPostIds,
  onClearSelection,
}: {
  selectedJobPostIds: string[]
  onClearSelection: () => void
}) {
  const [cvId, setCvId] = useState<string>("")
  const [jobId, setJobId] = useState<string | null>(null)
  const [isStarting, setIsStarting] = useState(false)
  const { job, isCompleted, isFailed } = useJobPoll(jobId)

  const cvsQuery = useQuery({ queryKey: ["dashboard-cvs-for-coverage"], queryFn: () => listCvs() })

  // POST .../coverage-report only returns a ProcessingJobRef, not the
  // report's own id — but worker_jobs.py creates that ProcessingJob with
  // source_entity_type="coverage_report", source_entity_id=report.id, and
  // GET /jobs/{jobId} exposes sourceEntityId, so the completed job's own
  // status response *is* the report id, no separate lookup needed.
  const reportId = job?.sourceEntityType === "coverage_report" ? job.sourceEntityId : null

  const reportQuery = useQuery({
    queryKey: ["coverage-report", reportId],
    queryFn: () => getCoverageReport(reportId as string),
    enabled: !!reportId && isCompleted,
  })

  async function handleRun() {
    if (!cvId || selectedJobPostIds.length === 0) return
    setIsStarting(true)
    try {
      const collection = await createJobPostCollection(
        `Coverage report ${new Date().toLocaleString()}`,
        selectedJobPostIds
      )
      const job = await triggerCoverageReport(collection.id, cvId)
      setJobId(job.jobId)
    } catch (error) {
      toast.error(errorMessage(error, "Couldn't start the coverage report."))
    } finally {
      setIsStarting(false)
    }
  }

  if (selectedJobPostIds.length === 0) return null

  return (
    <Card className="mt-4">
      <CardHeader>
        <CardTitle className="text-base">
          Coverage report — {selectedJobPostIds.length} job{selectedJobPostIds.length === 1 ? "" : "s"} selected
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center gap-2">
          <select
            className="h-8 rounded-md border border-border bg-background px-2 text-sm"
            value={cvId}
            onChange={(e) => setCvId(e.target.value)}
          >
            <option value="">Select a CV…</option>
            {cvsQuery.data?.items.map((cv) => (
              <option key={cv.id} value={cv.id}>
                {cv.originalFilename}
              </option>
            ))}
          </select>
          <Button size="sm" onClick={handleRun} disabled={!cvId || isStarting || !!jobId}>
            {isStarting ? "Starting…" : "Run coverage report"}
          </Button>
          <Button size="sm" variant="ghost" onClick={onClearSelection}>
            Clear selection
          </Button>
        </div>

        {jobId && !isCompleted && !isFailed && (
          <p className="text-sm text-muted-foreground">Running report across selected jobs…</p>
        )}
        {isFailed && <p className="text-sm text-destructive">The report failed. Please try again.</p>}
        {isCompleted && reportQuery.isLoading && (
          <p className="text-sm text-muted-foreground">Loading results…</p>
        )}
        {reportQuery.data && (
          <div className="space-y-2">
            {reportQuery.data.aggregateGaps.length === 0 ? (
              <p className="text-sm text-muted-foreground">No recurring gaps found.</p>
            ) : (
              reportQuery.data.aggregateGaps.map((gap, i) => (
                <div key={i} className="rounded-md border border-border p-2 text-sm">
                  <div className="flex items-center justify-between">
                    <span className="font-medium">{gap.requirementTextCluster}</span>
                    <Badge variant="secondary">
                      {gap.recurrenceCount} of {selectedJobPostIds.length} jobs
                    </Badge>
                  </div>
                </div>
              ))
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
