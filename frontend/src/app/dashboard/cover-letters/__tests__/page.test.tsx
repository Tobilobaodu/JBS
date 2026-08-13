import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { server } from "@/test/msw/server"
import { createQueryWrapper } from "@/test/query-wrapper"
import CoverLettersPage from "@/app/dashboard/cover-letters/page"

const BASE = "http://localhost:8000/api/v1"

function renderPage() {
  const Wrapper = createQueryWrapper()
  return render(
    <Wrapper>
      <CoverLettersPage />
    </Wrapper>
  )
}

describe("CoverLettersPage", () => {
  it("renders the list of cover-letter workflows returned by the API", async () => {
    server.use(
      http.get(`${BASE}/cover-letters`, () =>
        HttpResponse.json({
          items: [
            {
              id: "wf-1",
              jobPostId: "jp-1",
              jobTitle: "Senior Engineer",
              employer: "Acme",
              status: "awaiting_answers",
              currentStep: 1,
              createdAt: new Date().toISOString(),
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
    expect(screen.getByText("awaiting_answers")).toBeInTheDocument()
  })

  it("shows an empty state when there are no workflows", async () => {
    server.use(
      http.get(`${BASE}/cover-letters`, () =>
        HttpResponse.json({ items: [], total: 0, limit: 20, offset: 0 })
      )
    )

    renderPage()

    expect(
      await screen.findByText(
        "No cover letters yet — cover-letter generation is a premium feature, coming soon."
      )
    ).toBeInTheDocument()
  })

  it("shows an error message when the request fails", async () => {
    server.use(http.get(`${BASE}/cover-letters`, () => HttpResponse.json({}, { status: 500 })))

    renderPage()

    expect(
      await screen.findByText("Couldn't load this list. Please try again.")
    ).toBeInTheDocument()
  })
})
