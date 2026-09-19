import { describe, expect, it, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { server } from "@/test/msw/server"
import LoginPage from "@/app/login/page"
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

describe("LoginPage", () => {
  it("shows validation errors and does not submit when fields are empty", async () => {
    const user = userEvent.setup()
    render(<LoginPage />)

    await user.click(screen.getByRole("button", { name: "Login" }))

    expect(await screen.findByText("Invalid email address")).toBeInTheDocument()
    expect(screen.getByLabelText(/Email address/)).toHaveAttribute("aria-invalid", "true")
    expect(push).not.toHaveBeenCalled()
  })

  it("logs in successfully and redirects to /dashboard", async () => {
    const user = userEvent.setup()
    render(<LoginPage />)

    await user.type(screen.getByLabelText(/Email address/), "a@b.com")
    await user.type(screen.getByLabelText(/^Password/), "password123")
    await user.click(screen.getByRole("button", { name: "Login" }))

    await waitFor(() => expect(push).toHaveBeenCalledWith("/dashboard"))
    expect(useAuthStore.getState().accessToken).toBe("test-access-token")
  })

  it("marks both fields and shows the design's message on wrong credentials (401)", async () => {
    server.use(
      http.post(`${BASE}/auth/login`, () =>
        HttpResponse.json({ detail: "Invalid email or password." }, { status: 401 })
      )
    )
    const user = userEvent.setup()
    render(<LoginPage />)

    await user.type(screen.getByLabelText(/Email address/), "a@b.com")
    await user.type(screen.getByLabelText(/^Password/), "wrongpass")
    await user.click(screen.getByRole("button", { name: "Login" }))

    expect(
      await screen.findByText("Wrong email address and password combination")
    ).toBeInTheDocument()
    expect(screen.getByLabelText(/Email address/)).toHaveAttribute("aria-invalid", "true")
    expect(screen.getByLabelText(/^Password/)).toHaveAttribute("aria-invalid", "true")
    expect(toastError).not.toHaveBeenCalled()
    expect(push).not.toHaveBeenCalled()

    // Editing a field clears the stale error.
    await user.type(screen.getByLabelText(/^Password/), "x")
    expect(screen.queryByText("Wrong email address and password combination")).toBeNull()
  })

  it("links to the forgot-password page", () => {
    render(<LoginPage />)
    expect(screen.getByRole("link", { name: "Reset password" })).toHaveAttribute(
      "href",
      "/forgot-password"
    )
  })

  it("confirms a completed password reset when arriving from /reset-password", () => {
    window.history.replaceState(null, "", "/login?reset=done")
    try {
      render(<LoginPage />)
      expect(screen.getByRole("status")).toHaveTextContent("Your password has been changed")
    } finally {
      window.history.replaceState(null, "", "/")
    }
  })

  it("toggles password visibility with the eye button", async () => {
    const user = userEvent.setup()
    render(<LoginPage />)

    const password = screen.getByLabelText(/^Password/)
    expect(password).toHaveAttribute("type", "password")
    await user.click(screen.getByRole("button", { name: "Show password" }))
    expect(password).toHaveAttribute("type", "text")
    await user.click(screen.getByRole("button", { name: "Hide password" }))
    expect(password).toHaveAttribute("type", "password")
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
    render(<LoginPage />)

    await user.type(screen.getByLabelText(/Email address/), "a@b.com")
    await user.type(screen.getByLabelText(/^Password/), "password123")
    await user.click(screen.getByRole("button", { name: "Login" }))

    await waitFor(() => expect(push).toHaveBeenCalledWith("/dashboard/continue"))
    expect(useTrialStore.getState().trialSessionId).toBeNull()
  })

  it("shows a rate-limit toast on 429", async () => {
    server.use(
      http.post(`${BASE}/auth/login`, () =>
        HttpResponse.json(
          { detail: "Too many login attempts. Please wait and try again." },
          { status: 429 }
        )
      )
    )
    const user = userEvent.setup()
    render(<LoginPage />)

    await user.type(screen.getByLabelText(/Email address/), "a@b.com")
    await user.type(screen.getByLabelText(/^Password/), "password123")
    await user.click(screen.getByRole("button", { name: "Login" }))

    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith(
        "Too many login attempts. Please wait and try again."
      )
    )
  })
})
