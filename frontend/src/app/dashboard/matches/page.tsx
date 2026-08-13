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
import { listMatches } from "@/lib/dashboard-api"

export default function MatchesPage() {
  const query = useQuery({
    queryKey: ["dashboard-matches"],
    queryFn: () => listMatches(),
  })

  return (
    <div>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Matches</h1>
        <Button asChild size="sm">
          <Link href="/try/upload">Start a new match</Link>
        </Button>
      </div>

      <div className="mt-6">
        <DataTableShell
          isLoading={query.isLoading}
          isError={query.isError}
          isEmpty={!!query.data && query.data.items.length === 0}
          emptyMessage="No matches yet — upload a CV and a job to see how well they fit."
        >
          <TableHeader>
            <TableRow>
              <TableHead>Job</TableHead>
              <TableHead>Employer</TableHead>
              <TableHead>Score</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Created</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {query.data?.items.map((match) => (
              <TableRow key={match.id}>
                <TableCell className="font-medium">{match.jobTitle ?? "—"}</TableCell>
                <TableCell>{match.employer ?? "—"}</TableCell>
                <TableCell>{match.score ?? "—"}</TableCell>
                <TableCell>
                  <Badge variant={match.status === "completed" ? "default" : "secondary"}>
                    {match.status}
                  </Badge>
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {new Date(match.createdAt).toLocaleDateString()}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </DataTableShell>
      </div>
    </div>
  )
}
