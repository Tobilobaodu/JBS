import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import { DashboardNav } from "@/components/dashboard-nav"

let currentPathname = "/dashboard"
vi.mock("next/navigation", () => ({
  usePathname: () => currentPathname,
}))

describe("DashboardNav", () => {
  it("renders links for every dashboard section", () => {
    currentPathname = "/dashboard"
    render(<DashboardNav />)

    expect(screen.getByRole("link", { name: "Overview" })).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "CVs" })).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Jobs" })).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Matches" })).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Cover letters" })).toBeInTheDocument()
  })

  it("marks the Overview link active only on the exact /dashboard path, not sub-routes", () => {
    currentPathname = "/dashboard/cvs"
    render(<DashboardNav />)

    expect(screen.getByRole("link", { name: "Overview" })).not.toHaveClass("bg-muted")
    expect(screen.getByRole("link", { name: "CVs" })).toHaveClass("bg-muted")
  })
})
