"use client"

import Link from "next/link"
import { useQuery } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import {
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table"
import { DataTableShell } from "@/components/data-table-shell"
import { listJobPosts } from "@/lib/dashboard-api"

export default function JobsPage() {
  const query = useQuery({
    queryKey: ["dashboard-job-posts"],
    queryFn: () => listJobPosts(),
  })

  return (
    <div>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Jobs</h1>
        <Button asChild size="sm">
          <Link href="/try/upload">Add a job</Link>
        </Button>
      </div>

      <div className="mt-6">
        <DataTableShell
          isLoading={query.isLoading}
          isError={query.isError}
          isEmpty={!!query.data && query.data.items.length === 0}
          emptyMessage="You haven't saved any jobs yet — paste a job link or description to get started."
        >
          <TableHeader>
            <TableRow>
              <TableHead>Title</TableHead>
              <TableHead>Employer</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Added</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {query.data?.items.map((job) => (
              <TableRow key={job.id}>
                <TableCell className="font-medium">
                  {job.profile?.jobTitle ?? "—"}
                </TableCell>
                <TableCell>{job.profile?.employer ?? "—"}</TableCell>
                <TableCell>
                  <Badge variant={job.status === "completed" ? "default" : "secondary"}>
                    {job.status}
                  </Badge>
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {new Date(job.createdAt).toLocaleDateString()}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </DataTableShell>
      </div>
    </div>
  )
}
