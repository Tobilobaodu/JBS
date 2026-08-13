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
import { AtsCheckDialog } from "@/components/ats-check-dialog"
import { listCvs } from "@/lib/dashboard-api"

export default function CvsPage() {
  const query = useQuery({
    queryKey: ["dashboard-cvs"],
    queryFn: () => listCvs(),
  })

  return (
    <div>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">CVs</h1>
        <Button asChild size="sm">
          <Link href="/try/upload">Upload new</Link>
        </Button>
      </div>

      <div className="mt-6">
        <DataTableShell
          isLoading={query.isLoading}
          isError={query.isError}
          isEmpty={!!query.data && query.data.items.length === 0}
          emptyMessage="You haven't uploaded a CV yet — upload one to get started."
        >
          <TableHeader>
            <TableRow>
              <TableHead>Filename</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Uploaded</TableHead>
              <TableHead>ATS</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {query.data?.items.map((cv) => (
              <TableRow key={cv.id}>
                <TableCell className="font-medium">{cv.originalFilename}</TableCell>
                <TableCell>
                  <Badge variant={cv.status === "parsed" ? "default" : "secondary"}>
                    {cv.status}
                  </Badge>
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {new Date(cv.createdAt).toLocaleDateString()}
                </TableCell>
                <TableCell>
                  <AtsCheckDialog cvId={cv.id} cvName={cv.originalFilename} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </DataTableShell>
      </div>
    </div>
  )
}
