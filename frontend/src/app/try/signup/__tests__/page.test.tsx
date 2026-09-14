import { beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { server } from "@/test/msw/server"
import TrialSignupPage from "@/app/try/signup/page"
import { useAuthStore } from "@/store/auth-store"
import { useTrialStore } from "@/store/trial-store"
import { useTailoredCvStore } from "@/store/tailored-cv-store"

const push = vi.fn()
const replace = vi.fn()
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace }),
}))

const toastError = vi.fn()
vi.mock("sonner", () => ({
  toast: { error: (...args: unknown[]) => toastError(...args) },
}))

const BASE = "http://localhost:8000/api/v1"
const VALID_PASSWORD = "password1234" // backend minimum is 12

function carryTailoredCv() {
  useTailoredCvStore.getState().saveForSignup({
    markdown: "# Jane Doe\n\n## Professional Summary\nDesigner.",
    targetTitle: "Senior Designer",
    suggestedName: "Jane Doe",
    suggestedEmail: "jane@example.com",
  })
}

describe("TrialSignupPage (/try/signup)", () => {
  beforeEach(() => {
    push.mockReset()
    replace.mockReset()
    toastError.mockReset()
    useAuthStore.getState().clearAuth()
    useTrialStore.getState().clearTrialSession()
    useTailoredCvStore.getState().clear()
  })

  it("pre-fills name and email from the CV and asks only for a password", async () => {
    carryTailoredCv()
    render(<TrialSignupPage />)

    await waitFor(() => expect(screen.getByLabelText("Full name")).toHaveValue("Jane Doe"))
    expect(screen.getByLabelText("Email")).toHaveValue("jane@example.com")
    expect(screen.getByLabelText("Password")).toHaveValue("")
    expect(screen.queryByLabelText("Confirm password")).toBeNull()
  })

  it("sends a visitor with no tailored CV back to the trial", async () => {
    render(<TrialSignupPage />)
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/try/upload"))
  })

  it("toggles the password between hidden and shown", async () => {
    carryTailoredCv()
    const user = userEvent.setup()
    render(<TrialSignupPage />)

    const password = screen.getByLabelText("Password")
    expect(password).toHaveAttribute("type", "password")
    await user.click(screen.getByRole("button", { name: "Show" }))
    expect(password).toHaveAttribute("type", "text")
    await user.click(screen.getByRole("button", { name: "Hide" }))
    expect(password).toHaveAttribute("type", "password")
  })

  it("rejects a password shorter than 12 characters", async () => {
    carryTailoredCv()
    const user = userEvent.setup()
    render(<TrialSignupPage />)

    await waitFor(() => expect(screen.getByLabelText("Full name")).toHaveValue("Jane Doe"))
    await user.type(screen.getByLabelText("Password"), "short")
    await user.click(screen.getByRole("button", { name: "Create account and continue" }))

    expect(await screen.findByText("Password must be at least 12 characters.")).toBeInTheDocument()
    expect(push).not.toHaveBeenCalled()
  })

  it("registers with the name, claims the trial, and goes straight to the dashboard", async () => {
    carryTailoredCv()
    useTrialStore.setState({ trialSessionId: "trial-1", expiresAt: new Date().toISOString() })
    let registerBody: Record<string, unknown> | null = null
    server.use(
      http.post(`${BASE}/auth/register`, async ({ request }) => {
        registerBody = (await request.json()) as Record<string, unknown>
        return HttpResponse.json(
          { id: "user-1", email: "jane@example.com", fullName: "Jane Doe", accountStatus: "active", createdAt: new Date().toISOString() },
          { status: 201 }
        )
      }),
      http.post(`${BASE}/auth/claim-trial`, () =>
        HttpResponse.json({ claimed: true, cvFilesReassigned: 1, jobPostsReassigned: 0, matchRunsReassigned: 0 })
      )
    )

    const user = userEvent.setup()
    render(<TrialSignupPage />)
    await waitFor(() => expect(screen.getByLabelText("Full name")).toHaveValue("Jane Doe"))
    await user.type(screen.getByLabelText("Password"), VALID_PASSWORD)
    await user.click(screen.getByRole("button", { name: "Create account and continue" }))

    await waitFor(() => expect(push).toHaveBeenCalledWith("/dashboard"))
    expect(push).not.toHaveBeenCalledWith("/dashboard/continue")
    expect(registerBody).toEqual({ email: "jane@example.com", password: VALID_PASSWORD, fullName: "Jane Doe" })
    expect(useAuthStore.getState().accessToken).toBe("test-access-token")
    expect(useTrialStore.getState().trialSessionId).toBeNull()
    // The CV must survive sign-up — the dashboard is where it's downloaded.
    expect(useTailoredCvStore.getState().markdown).toContain("Professional Summary")
  })

  it("still reaches the dashboard when attaching the trial fails", async () => {
    carryTailoredCv()
    useTrialStore.setState({ trialSessionId: "trial-1", expiresAt: new Date().toISOString() })
    server.use(
      http.post(`${BASE}/auth/claim-trial`, () =>
        HttpResponse.json({ detail: "Trial session already claimed." }, { status: 409 })
      )
    )

    const user = userEvent.setup()
    render(<TrialSignupPage />)
    await waitFor(() => expect(screen.getByLabelText("Full name")).toHaveValue("Jane Doe"))
    await user.type(screen.getByLabelText("Password"), VALID_PASSWORD)
    await user.click(screen.getByRole("button", { name: "Create account and continue" }))

    await waitFor(() => expect(push).toHaveBeenCalledWith("/dashboard"))
    expect(toastError).toHaveBeenCalledWith("Trial session already claimed.")
  })

  it("offers to log in instead when the email already has an account", async () => {
    carryTailoredCv()
    server.use(
      http.post(`${BASE}/auth/register`, () =>
        HttpResponse.json({ detail: "An account with this email already exists." }, { status: 409 })
      )
    )

    const user = userEvent.setup()
    render(<TrialSignupPage />)
    await waitFor(() => expect(screen.getByLabelText("Full name")).toHaveValue("Jane Doe"))
    await user.type(screen.getByLabelText("Password"), VALID_PASSWORD)
    await user.click(screen.getByRole("button", { name: "Create account and continue" }))

    expect(await screen.findByTestId("status-email-taken")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Log in instead" })).toHaveAttribute("href", "/login")
    expect(push).not.toHaveBeenCalled()
  })
})
