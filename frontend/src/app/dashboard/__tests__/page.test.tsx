import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { server } from "@/test/msw/server"
import { createQueryWrapper } from "@/test/query-wrapper"
import DashboardPage from "@/app/dashboard/page"
import { useAuthStore } from "@/store/auth-store"

const BASE = "http://localhost:8000/api/v1"

function renderPage() {
  const Wrapper = createQueryWrapper()
  return render(
    <Wrapper>
      <DashboardPage />
    </Wrapper>
  )
}

const emptyList = () => HttpResponse.json({ items: [], total: 0, limit: 20, offset: 0 })

describe("DashboardPage", () => {
  it("shows summary counts for all four lists and recent items from CVs/jobs", async () => {
    useAuthStore.getState().setAuth("token-1", { id: "u1", email: "a@b.com" })
    server.use(
      http.get(`${BASE}/cvs`, () =>
        HttpResponse.json({
          items: [
            {
              id: "cv-1",
              originalFilename: "resume.pdf",
              mimeType: "application/pdf",
              fileSizeBytes: 1024,
              status: "parsed",
              uploadStatus: "completed",
              processingStatus: "completed",
              jobStatus: null,
              createdAt: new Date().toISOString(),
              updatedAt: new Date().toISOString(),
            },
          ],
          total: 4,
          limit: 20,
          offset: 0,
        })
      ),
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
          total: 2,
          limit: 20,
          offset: 0,
        })
      ),
      http.get(`${BASE}/matches`, () =>
        HttpResponse.json({ items: [], total: 3, limit: 20, offset: 0 })
      ),
      http.get(`${BASE}/cover-letters`, () =>
        HttpResponse.json({ items: [], total: 1, limit: 20, offset: 0 })
      )
    )

    renderPage()

    expect(screen.getByText("Signed in as a@b.com.")).toBeInTheDocument()
    expect(await screen.findByText("4")).toBeInTheDocument()
    expect(await screen.findByText("2")).toBeInTheDocument()
    expect(await screen.findByText("3")).toBeInTheDocument()
    expect(await screen.findByText("1")).toBeInTheDocument()
    expect(await screen.findByText("resume.pdf")).toBeInTheDocument()
    expect(await screen.findByText("Senior Engineer")).toBeInTheDocument()
  })

  it("shows 'No CVs yet.' / 'No jobs yet.' when both lists are empty", async () => {
    useAuthStore.getState().setAuth("token-1", { id: "u1", email: "a@b.com" })
    server.use(
      http.get(`${BASE}/cvs`, emptyList),
      http.get(`${BASE}/job-posts`, emptyList),
      http.get(`${BASE}/matches`, emptyList),
      http.get(`${BASE}/cover-letters`, emptyList)
    )

    renderPage()

    expect(await screen.findByText("No CVs yet.")).toBeInTheDocument()
    expect(await screen.findByText("No jobs yet.")).toBeInTheDocument()
  })
})
