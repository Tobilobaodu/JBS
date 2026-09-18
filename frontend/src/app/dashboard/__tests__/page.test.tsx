import { beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { server } from "@/test/msw/server"
import { createQueryWrapper } from "@/test/query-wrapper"
import DashboardPage from "@/app/dashboard/page"
import { useAuthStore } from "@/store/auth-store"

// Shared spy so tests can assert navigation — the old bug was a click that
// silently did nothing, so the positive path must be asserted on the mock
// (same convention as dashboard/continue's page test).
const push = vi.fn()
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}))

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
  beforeEach(() => {
    push.mockClear()
  })

  it("shows the current resume, stat band, and recent matches from real data", async () => {
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
              resumeScore: 85,
              issueCount: 9,
              createdAt: new Date().toISOString(),
              updatedAt: new Date().toISOString(),
            },
          ],
          total: 1,
          limit: 20,
          offset: 0,
        })
      ),
      http.get(`${BASE}/cvs/cv-1/analysis`, () =>
        HttpResponse.json({}, { status: 404 })
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
        HttpResponse.json({
          items: [
            {
              id: "match-1",
              jobPostId: "jp-1",
              jobTitle: "Senior Engineer",
              employer: "Acme",
              status: "completed",
              score: 82,
              createdAt: new Date().toISOString(),
              completedAt: new Date().toISOString(),
            },
          ],
          total: 3,
          limit: 20,
          offset: 0,
        })
      ),
      http.get(`${BASE}/job-post-collections`, () => HttpResponse.json([]))
    )

    renderPage()

    expect(await screen.findByText("OVERVIEW")).toBeInTheDocument()
    expect(await screen.findByText("resume.pdf")).toBeInTheDocument()
    expect(await screen.findByText("Senior Engineer")).toBeInTheDocument()
    expect(screen.getByText("Acme")).toBeInTheDocument()

    // The positive path of the regression: with a match present the button
    // must actually navigate to that match's report — it used to no-op.
    await userEvent.click(screen.getByTestId("button-view-full-report"))
    expect(push).toHaveBeenCalledWith("/dashboard/matches/match-1")
  })

  it("offers a way forward instead of a dead 'View full report' when there are no matches", async () => {
    // Regression: the button was enabled on having a CV, but a report
    // belongs to a match — with none, clicking it did nothing at all.
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
              resumeScore: 85,
              issueCount: 2,
              createdAt: new Date().toISOString(),
              updatedAt: new Date().toISOString(),
            },
          ],
          total: 1, limit: 20, offset: 0,
        })
      ),
      http.get(`${BASE}/cvs/cv-1/analysis`, () => HttpResponse.json({}, { status: 404 })),
      http.post(`${BASE}/cvs/cv-1/analysis`, () =>
        HttpResponse.json({ jobId: "job-1", status: "queued" }, { status: 202 })
      ),
      http.get(`${BASE}/jobs/job-1`, () =>
        HttpResponse.json({ id: "job-1", jobType: "cv_analyze", status: "queued" })
      ),
      http.get(`${BASE}/job-posts`, emptyList),
      http.get(`${BASE}/matches`, emptyList),
      http.get(`${BASE}/job-post-collections`, () => HttpResponse.json([]))
    )

    renderPage()

    const link = await screen.findByTestId("link-first-report")
    expect(link).toHaveAttribute("href", "/dashboard/new")
    expect(screen.queryByTestId("button-view-full-report")).toBeNull()
  })

  it("offers nothing clickable while it can't yet tell whether a report exists", async () => {
    // Regression: while /matches was still loading, a working link to
    // /dashboard/new showed "Loading…" — a quick click sent a user who DOES
    // have matches to "New match" instead of their report.
    useAuthStore.getState().setAuth("token-1", { id: "u1", email: "a@b.com" })
    let releaseMatches: () => void = () => {}
    const matchesGate = new Promise<void>((resolve) => { releaseMatches = resolve })
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
              resumeScore: 85,
              issueCount: 2,
              createdAt: new Date().toISOString(),
              updatedAt: new Date().toISOString(),
            },
          ],
          total: 1, limit: 20, offset: 0,
        })
      ),
      http.get(`${BASE}/cvs/cv-1/analysis`, () => HttpResponse.json({}, { status: 404 })),
      http.post(`${BASE}/cvs/cv-1/analysis`, () =>
        HttpResponse.json({ jobId: "job-1", status: "queued" }, { status: 202 })
      ),
      http.get(`${BASE}/jobs/job-1`, () =>
        HttpResponse.json({ id: "job-1", jobType: "cv_analyze", status: "queued" })
      ),
      http.get(`${BASE}/job-posts`, emptyList),
      // Held open until the assertions below have run.
      http.get(`${BASE}/matches`, async () => {
        await matchesGate
        return HttpResponse.json({
          items: [
            {
              id: "match-1",
              jobPostId: "jp-1",
              jobTitle: "Senior Engineer",
              employer: "Acme",
              status: "completed",
              score: 82,
              createdAt: new Date().toISOString(),
              completedAt: new Date().toISOString(),
            },
          ],
          total: 1, limit: 20, offset: 0,
        })
      }),
      http.get(`${BASE}/job-post-collections`, () => HttpResponse.json([]))
    )

    renderPage()

    const loading = await screen.findByTestId("button-report-loading")
    expect(loading).toBeDisabled()
    expect(screen.queryByTestId("link-first-report")).toBeNull()

    // Once matches arrive, the real report button replaces it.
    releaseMatches()
    expect(await screen.findByTestId("button-view-full-report")).toBeInTheDocument()
    expect(screen.queryByTestId("button-report-loading")).toBeNull()
  })

  it("shows the first-run empty state when there are no CVs yet", async () => {
    useAuthStore.getState().setAuth("token-1", { id: "u1", email: "a@b.com" })
    server.use(
      http.get(`${BASE}/cvs`, emptyList),
      http.get(`${BASE}/job-posts`, emptyList),
      http.get(`${BASE}/matches`, emptyList),
      http.get(`${BASE}/job-post-collections`, () => HttpResponse.json([]))
    )

    renderPage()

    expect(await screen.findByText("NOTHING HERE YET. THAT'S THE POINT.")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /Start your first match/ })).toBeInTheDocument()
  })
})
