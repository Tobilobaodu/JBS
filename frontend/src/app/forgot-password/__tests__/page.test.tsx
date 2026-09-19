import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { server } from "@/test/msw/server"
import ForgotPasswordPage from "@/app/forgot-password/page"

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

const toastError = vi.fn()
vi.mock("sonner", () => ({
  toast: { error: (...args: unknown[]) => toastError(...args) },
}))

const BASE = "http://localhost:8000/api/v1"
const GENERIC = "If an account exists for that email, we've sent a link to reset its password."

describe("ForgotPasswordPage", () => {
  it("rejects an invalid email without calling the API", async () => {
    let called = false
    server.use(
      http.post(`${BASE}/auth/password-reset/request`, () => {
        called = true
        return HttpResponse.json({ detail: GENERIC }, { status: 202 })
      })
    )
    const user = userEvent.setup()
    render(<ForgotPasswordPage />)

    await user.type(screen.getByLabelText(/Email address/), "not-an-email")
    await user.click(screen.getByRole("button", { name: "Reset password" }))

    expect(await screen.findByText("Invalid email address")).toBeInTheDocument()
    expect(called).toBe(false)
  })

  it("shows the confirmation without claiming the account exists, and keeps the form to resend", async () => {
    let sentBody: unknown = null
    server.use(
      http.post(`${BASE}/auth/password-reset/request`, async ({ request }) => {
        sentBody = await request.json()
        return HttpResponse.json({ detail: GENERIC }, { status: 202 })
      })
    )
    const user = userEvent.setup()
    render(<ForgotPasswordPage />)

    await user.type(screen.getByLabelText(/Email address/), "jo@example.com")
    await user.click(screen.getByRole("button", { name: "Reset password" }))

    const status = await screen.findByRole("status")
    expect(status).toHaveTextContent("If there’s an account for jo@example.com")
    expect(status).toHaveTextContent("check your spam folder")
    expect(sentBody).toEqual({ email: "jo@example.com" })
    // Resend is still possible.
    expect(screen.getByRole("button", { name: "Reset password" })).toBeEnabled()
    expect(screen.getByRole("link", { name: "Click here" })).toHaveAttribute("href", "/login")
  })

  it("says so honestly when the server can't send email (503)", async () => {
    server.use(
      http.post(`${BASE}/auth/password-reset/request`, () =>
        HttpResponse.json(
          { detail: "Password reset by email isn't available right now." },
          { status: 503 }
        )
      )
    )
    const user = userEvent.setup()
    render(<ForgotPasswordPage />)

    await user.type(screen.getByLabelText(/Email address/), "jo@example.com")
    await user.click(screen.getByRole("button", { name: "Reset password" }))

    expect(
      await screen.findByText("Password reset by email isn't available right now.")
    ).toBeInTheDocument()
    expect(screen.queryByRole("status")).toBeNull()
  })

  it("toasts the rate-limit message on 429", async () => {
    server.use(
      http.post(`${BASE}/auth/password-reset/request`, () =>
        HttpResponse.json({ detail: "Too many reset requests. Please wait and try again." }, { status: 429 })
      )
    )
    const user = userEvent.setup()
    render(<ForgotPasswordPage />)

    await user.type(screen.getByLabelText(/Email address/), "jo@example.com")
    await user.click(screen.getByRole("button", { name: "Reset password" }))

    await vi.waitFor(() =>
      expect(toastError).toHaveBeenCalledWith("Too many reset requests. Please wait and try again.")
    )
    expect(screen.queryByRole("status")).toBeNull()
  })
})
