"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { cn } from "@/lib/utils"

const links = [
  { href: "/dashboard", label: "Overview" },
  { href: "/dashboard/cvs", label: "CVs" },
  { href: "/dashboard/jobs", label: "Jobs" },
  { href: "/dashboard/matches", label: "Matches" },
  { href: "/dashboard/cover-letters", label: "Cover letters" },
]

export function DashboardNav() {
  const pathname = usePathname()

  return (
    <nav className="flex gap-1 border-b pb-2">
      {links.map((link) => {
        const isActive =
          link.href === "/dashboard" ? pathname === link.href : pathname.startsWith(link.href)
        return (
          <Link
            key={link.href}
            href={link.href}
            className={cn(
              "rounded-md px-3 py-1.5 text-sm",
              isActive
                ? "bg-muted font-medium text-foreground"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            {link.label}
          </Link>
        )
      })}
    </nav>
  )
}
