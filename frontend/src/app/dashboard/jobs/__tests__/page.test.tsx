import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { server } from "@/test/msw/server"
import { createQueryWrapper } from "@/test/query-wrapper"
import JobsPage from "@/app/dashboard/jobs/page"

const BASE = "http://localhost:8000/api/v1"

function renderPage() {
  const Wrapper = createQueryWrapper()
  return render(
    <Wrapper>
      <JobsPage />
    </Wrapper>
  )
}

describe("JobsPage", () => {
  it("renders the list of job posts returned by the API", async () => {
    server.use(
      http.get(`${BASE}/job-posts`, () =>
        HttpResponse.json({
          items: [
            {
              id: "jp-1",
              sourceType: "text",
              sourceUrl: null,
              status: "completed",
              errorMessage: null,
              createdAt: new Date().toISOString(),
              updatedAt: new Date().toISOString(),
              profile: { jobTitle: "Senior Engineer", employer: "Acme" },
            },
          ],
          total: 1,
          limit: 20,
          offset: 0,
        })
      )
    )

    renderPage()

    expect(await screen.findByText("Senior Engineer")).toBeInTheDocument()
    expect(screen.getByText("Acme")).toBeInTheDocument()
  })

  it("shows an empty state when there are no jobs", async () => {
    server.use(
      http.get(`${BASE}/job-posts`, () =>
        HttpResponse.json({ items: [], total: 0, limit: 20, offset: 0 })
      )
    )

    renderPage()

    expect(
      await screen.findByText(
        "You haven't saved any jobs yet — paste a job link or description to get started."
      )
    ).toBeInTheDocument()
  })

  it("falls back gracefully when a job post has no structured profile yet", async () => {
    server.use(
      http.get(`${BASE}/job-posts`, () =>
        HttpResponse.json({
          items: [
            {
              id: "jp-2",
              sourceType: "url",
              sourceUrl: "https://example.com/job",
              status: "pending",
              errorMessage: null,
              createdAt: new Date().toISOString(),
              updatedAt: new Date().toISOString(),
              profile: null,
            },
          ],
          total: 1,
          limit: 20,
          offset: 0,
        })
      )
    )

    renderPage()

    expect(await screen.findByText("pending")).toBeInTheDocument()
    expect(screen.getAllByText("—").length).toBeGreaterThan(0)
  })
})
