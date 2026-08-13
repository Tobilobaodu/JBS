"use client"

import { useQuery } from "@tanstack/react-query"
import { Badge } from "@/components/ui/badge"
import {
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table"
import { DataTableShell } from "@/components/data-table-shell"
import { listCoverLetterWorkflows } from "@/lib/dashboard-api"

export default function CoverLettersPage() {
  const query = useQuery({
    queryKey: ["dashboard-cover-letters"],
    queryFn: () => listCoverLetterWorkflows(),
  })

  return (
    <div>
      <h1 className="text-2xl font-semibold">Cover letters</h1>

      <div className="mt-6">
        <DataTableShell
          isLoading={query.isLoading}
          isError={query.isError}
          isEmpty={!!query.data && query.data.items.length === 0}
          emptyMessage="No cover letters yet — cover-letter generation is a premium feature, coming soon."
        >
          <TableHeader>
            <TableRow>
              <TableHead>Job</TableHead>
              <TableHead>Employer</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Step</TableHead>
              <TableHead>Created</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {query.data?.items.map((wf) => (
              <TableRow key={wf.id}>
                <TableCell className="font-medium">{wf.jobTitle ?? "—"}</TableCell>
                <TableCell>{wf.employer ?? "—"}</TableCell>
                <TableCell>
                  <Badge variant={wf.status === "approved" ? "default" : "secondary"}>
                    {wf.status}
                  </Badge>
                </TableCell>
                <TableCell>{wf.currentStep}</TableCell>
                <TableCell className="text-muted-foreground">
                  {new Date(wf.createdAt).toLocaleDateString()}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </DataTableShell>
      </div>
    </div>
  )
}
