import { afterEach, describe, expect, it, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { server } from "@/test/msw/server"
import ResetPasswordPage from "@/app/reset-password/page"
import { useAuthStore } from "@/store/auth-store"

const push = vi.fn()
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}))

vi.mock("sonner", () => ({
  toast: { error: vi.fn() },
}))

const BASE = "http://localhost:8000/api/v1"

function openLink(hash: string) {
  window.history.replaceState(null, "", `/reset-password${hash}`)
}

afterEach(() => {
  window.history.replaceState(null, "", "/")
})

describe("ResetPasswordPage", () => {
  it("sends the token from the link's fragment and goes to login with a notice", async () => {
    openLink("#token=tok-abc")
    let sentBody: unknown = null
    server.use(
      http.post(`${BASE}/auth/password-reset/confirm`, async ({ request }) => {
        sentBody = await request.json()
        return new HttpResponse(null, { status: 204 })
      })
    )
    useAuthStore.getState().setAuth("stale-token", { id: "u1", email: "a@b.com" })
    const user = userEvent.setup()
    render(<ResetPasswordPage />)

    await user.type(screen.getByLabelText(/New password/), "BrandNewPassword1")
    await user.click(screen.getByRole("button", { name: "Save password" }))

    await waitFor(() => expect(push).toHaveBeenCalledWith("/login?reset=done"))
    expect(sentBody).toEqual({ token: "tok-abc", password: "BrandNewPassword1" })
    // Every session was revoked server-side; the local one goes too.
    expect(useAuthStore.getState().accessToken).toBeNull()
  })

  it("enforces the 12-character minimum before calling the API", async () => {
    openLink("#token=tok-abc")
    const user = userEvent.setup()
    render(<ResetPasswordPage />)

    await user.type(screen.getByLabelText(/New password/), "short")
    await user.click(screen.getByRole("button", { name: "Save password" }))

    expect(await screen.findByText("Password must be at least 12 characters.")).toBeInTheDocument()
    expect(push).not.toHaveBeenCalled()
  })

  it("explains an expired or used link and offers a new one", async () => {
    openLink("#token=used-token")
    server.use(
      http.post(`${BASE}/auth/password-reset/confirm`, () =>
        HttpResponse.json({ detail: "This reset link is invalid or has expired." }, { status: 400 })
      )
    )
    const user = userEvent.setup()
    render(<ResetPasswordPage />)

    await user.type(screen.getByLabelText(/New password/), "BrandNewPassword1")
    await user.click(screen.getByRole("button", { name: "Save password" }))

    expect(await screen.findByText(/invalid or has expired/)).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "request a new link" })).toHaveAttribute(
      "href",
      "/forgot-password"
    )
    expect(push).not.toHaveBeenCalled()
  })

  it("shows a way forward instead of a form when the link has no token", () => {
    openLink("")
    render(<ResetPasswordPage />)

    expect(screen.getByText(/This reset link is incomplete/)).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Save password" })).toBeNull()
  })
})
