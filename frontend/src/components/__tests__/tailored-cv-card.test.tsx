import { beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { server } from "@/test/msw/server"
import { TailoredCvCard } from "@/components/tailored-cv-card"
import { useTailoredCvStore } from "@/store/tailored-cv-store"

vi.mock("sonner", () => ({ toast: { error: vi.fn() } }))

const BASE = "http://localhost:8000/api/v1"

describe("TailoredCvCard", () => {
  beforeEach(() => useTailoredCvStore.getState().clear())

  it("renders nothing when no tailored CV was carried over", () => {
    render(<TailoredCvCard />)
    expect(screen.queryByTestId("card-tailored-cv")).toBeNull()
  })

  it("posts the carried Markdown to the PDF endpoint on Download", async () => {
    useTailoredCvStore.getState().saveForSignup({
      markdown: "## Professional Summary\nDesigner.",
      targetTitle: "Senior Designer",
      suggestedName: "",
      suggestedEmail: "",
    })
    let posted: Record<string, unknown> | null = null
    server.use(
      http.post(`${BASE}/resume-rewrites/pdf`, async ({ request }) => {
        posted = (await request.json()) as Record<string, unknown>
        return new HttpResponse(new Uint8Array([37, 80, 68, 70]), {
          headers: { "Content-Type": "application/pdf" },
        })
      })
    )
    // jsdom has no object URLs.
    URL.createObjectURL = vi.fn(() => "blob:test")
    URL.revokeObjectURL = vi.fn()

    const user = userEvent.setup()
    render(<TailoredCvCard />)
    expect(screen.getByText("Your tailored CV · Senior Designer")).toBeInTheDocument()
    await user.click(screen.getByTestId("button-download-tailored-cv"))

    await waitFor(() =>
      expect(posted).toEqual({
        tailoredResumeMarkdown: "## Professional Summary\nDesigner.",
        fileName: "Tailored CV - Senior Designer",
      })
    )
  })

  it("Dismiss removes the carried CV", async () => {
    useTailoredCvStore.getState().saveForSignup({
      markdown: "x", targetTitle: "", suggestedName: "", suggestedEmail: "",
    })
    const user = userEvent.setup()
    render(<TailoredCvCard />)
    await user.click(screen.getByTestId("button-dismiss-tailored-cv"))
    expect(screen.queryByTestId("card-tailored-cv")).toBeNull()
    expect(useTailoredCvStore.getState().markdown).toBeNull()
  })
})
