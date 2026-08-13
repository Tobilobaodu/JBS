"use client"

import Link from "next/link"
import { useQuery } from "@tanstack/react-query"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { useAuthStore } from "@/store/auth-store"
import { listCvs, listJobPosts, listMatches, listCoverLetterWorkflows } from "@/lib/dashboard-api"

export default function DashboardPage() {
  const user = useAuthStore((state) => state.user)

  const cvsQuery = useQuery({ queryKey: ["dashboard-cvs"], queryFn: () => listCvs() })
  const jobsQuery = useQuery({
    queryKey: ["dashboard-job-posts"],
    queryFn: () => listJobPosts(),
  })
  const matchesQuery = useQuery({
    queryKey: ["dashboard-matches"],
    queryFn: () => listMatches(),
  })
  const coverLettersQuery = useQuery({
    queryKey: ["dashboard-cover-letters"],
    queryFn: () => listCoverLetterWorkflows(),
  })

  const recentCvs = cvsQuery.data?.items.slice(0, 3) ?? []
  const recentJobs = jobsQuery.data?.items.slice(0, 3) ?? []

  return (
    <div>
      <h1 className="text-2xl font-semibold">Dashboard</h1>
      <p className="mt-2 text-muted-foreground">Signed in as {user?.email}.</p>

      <div className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Card>
          <CardHeader>
            <CardTitle className="text-sm text-muted-foreground">CVs</CardTitle>
          </CardHeader>
          <CardContent className="text-2xl font-semibold">
            {cvsQuery.data?.total ?? "—"}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-sm text-muted-foreground">Jobs</CardTitle>
          </CardHeader>
          <CardContent className="text-2xl font-semibold">
            {jobsQuery.data?.total ?? "—"}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-sm text-muted-foreground">Matches</CardTitle>
          </CardHeader>
          <CardContent className="text-2xl font-semibold">
            {matchesQuery.data?.total ?? "—"}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-sm text-muted-foreground">Cover letters</CardTitle>
          </CardHeader>
          <CardContent className="text-2xl font-semibold">
            {coverLettersQuery.data?.total ?? "—"}
          </CardContent>
        </Card>
      </div>

      <div className="mt-8 grid grid-cols-2 gap-6">
        <div>
          <h2 className="text-sm font-medium text-muted-foreground">Recent CVs</h2>
          {recentCvs.length === 0 ? (
            <p className="mt-2 text-sm text-muted-foreground">No CVs yet.</p>
          ) : (
            <ul className="mt-2 flex flex-col gap-1">
              {recentCvs.map((cv) => (
                <li key={cv.id} className="text-sm">
                  {cv.originalFilename}
                </li>
              ))}
            </ul>
          )}
          <Link href="/dashboard/cvs" className="mt-2 inline-block text-sm underline">
            View all
          </Link>
        </div>
        <div>
          <h2 className="text-sm font-medium text-muted-foreground">Recent jobs</h2>
          {recentJobs.length === 0 ? (
            <p className="mt-2 text-sm text-muted-foreground">No jobs yet.</p>
          ) : (
            <ul className="mt-2 flex flex-col gap-1">
              {recentJobs.map((job) => (
                <li key={job.id} className="text-sm">
                  {job.profile?.jobTitle ?? job.sourceUrl ?? "Untitled job"}
                </li>
              ))}
            </ul>
          )}
          <Link href="/dashboard/jobs" className="mt-2 inline-block text-sm underline">
            View all
          </Link>
        </div>
      </div>

      <div className="mt-8">
        <Link href="/try/upload" className="text-sm underline">
          Upload new CV
        </Link>
      </div>
    </div>
  )
}
