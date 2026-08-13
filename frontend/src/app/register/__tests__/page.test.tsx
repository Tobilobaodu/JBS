import { describe, expect, it, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { server } from "@/test/msw/server"
import RegisterPage from "@/app/register/page"
import { useAuthStore } from "@/store/auth-store"
import { useTrialStore } from "@/store/trial-store"

const push = vi.fn()
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}))

const toastError = vi.fn()
vi.mock("sonner", () => ({
  toast: { error: (...args: unknown[]) => toastError(...args) },
}))

const BASE = "http://localhost:8000/api/v1"

describe("RegisterPage", () => {
  it("rejects a password shorter than 8 characters", async () => {
    const user = userEvent.setup()
    render(<RegisterPage />)

    await user.type(screen.getByLabelText("Email"), "a@b.com")
    await user.type(screen.getByLabelText("Password"), "short")
    await user.type(screen.getByLabelText("Confirm password"), "short")
    await user.click(screen.getByRole("button", { name: "Create account" }))

    expect(
      await screen.findByText("Password must be at least 8 characters.")
    ).toBeInTheDocument()
    expect(push).not.toHaveBeenCalled()
  })

  it("rejects mismatched passwords", async () => {
    const user = userEvent.setup()
    render(<RegisterPage />)

    await user.type(screen.getByLabelText("Email"), "a@b.com")
    await user.type(screen.getByLabelText("Password"), "password123")
    await user.type(screen.getByLabelText("Confirm password"), "password124")
    await user.click(screen.getByRole("button", { name: "Create account" }))

    expect(await screen.findByText("Passwords do not match.")).toBeInTheDocument()
    expect(push).not.toHaveBeenCalled()
  })

  it("registers, logs in, and redirects to /dashboard", async () => {
    const user = userEvent.setup()
    render(<RegisterPage />)

    await user.type(screen.getByLabelText("Email"), "a@b.com")
    await user.type(screen.getByLabelText("Password"), "password123")
    await user.type(screen.getByLabelText("Confirm password"), "password123")
    await user.click(screen.getByRole("button", { name: "Create account" }))

    await waitFor(() => expect(push).toHaveBeenCalledWith("/dashboard"))
    expect(useAuthStore.getState().accessToken).toBe("test-access-token")
  })

  it("claims an active trial session and redirects to /dashboard/continue instead of /dashboard", async () => {
    useTrialStore.setState({
      trialSessionId: "trial-1",
      expiresAt: new Date().toISOString(),
    })
    server.use(
      http.post(`${BASE}/auth/claim-trial`, () =>
        HttpResponse.json({
          claimed: true,
          cvFilesReassigned: 1,
          jobPostsReassigned: 1,
          matchRunsReassigned: 1,
        })
      )
    )

    const user = userEvent.setup()
    render(<RegisterPage />)

    await user.type(screen.getByLabelText("Email"), "a@b.com")
    await user.type(screen.getByLabelText("Password"), "password123")
    await user.type(screen.getByLabelText("Confirm password"), "password123")
    await user.click(screen.getByRole("button", { name: "Create account" }))

    await waitFor(() => expect(push).toHaveBeenCalledWith("/dashboard/continue"))
    expect(useTrialStore.getState().trialSessionId).toBeNull()
  })

  it("shows an error toast when the email is already registered (409)", async () => {
    server.use(
      http.post(`${BASE}/auth/register`, () =>
        HttpResponse.json(
          { detail: "An account with this email already exists." },
          { status: 409 }
        )
      )
    )
    const user = userEvent.setup()
    render(<RegisterPage />)

    await user.type(screen.getByLabelText("Email"), "a@b.com")
    await user.type(screen.getByLabelText("Password"), "password123")
    await user.type(screen.getByLabelText("Confirm password"), "password123")
    await user.click(screen.getByRole("button", { name: "Create account" }))

    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith(
        "An account with this email already exists."
      )
    )
    expect(push).not.toHaveBeenCalled()
  })
})
