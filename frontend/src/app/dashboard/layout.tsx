"use client"

import { useRequireAuth } from "@/hooks/use-require-auth"
import { DashboardNav } from "@/components/dashboard-nav"

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const { isReady } = useRequireAuth()

  if (!isReady) {
    return (
      <div className="mx-auto max-w-6xl px-4 py-24 text-center text-muted-foreground">
        Loading…
      </div>
    )
  }

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-8">
      <DashboardNav />
      {children}
    </div>
  )
}
