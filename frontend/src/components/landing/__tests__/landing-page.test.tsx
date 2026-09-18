import { describe, expect, it, vi } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { LandingPage } from "@/components/landing/landing-page"
import { useAuthStore } from "@/store/auth-store"

const push = vi.fn()
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  usePathname: () => "/",
}))

describe("LandingPage", () => {
  it("sends Upload CV into the trial flow and Find a job to the job feed", () => {
    render(<LandingPage />)

    expect(screen.getByRole("heading", { level: 1, name: /job search made easy/i })).toBeInTheDocument()
    // /try (not /try/upload): that page creates the trial session first.
    expect(screen.getByRole("link", { name: /upload cv/i })).toHaveAttribute("href", "/try")
    expect(screen.getByRole("link", { name: /find a job/i })).toHaveAttribute("href", "/dashboard/job-feed")
  })

  it("has the design's footer links and social icons", () => {
    render(<LandingPage />)
    const footer = screen.getByRole("contentinfo")

    for (const name of ["About us", "Privacy Policy", "Terms and condition", "FAQs", "LinkedIn", "X", "Facebook"]) {
      expect(within(footer).getByRole("link", { name })).toBeInTheDocument()
    }
  })

  it("shows Log in to visitors and Dashboard to signed-in users", () => {
    const { unmount } = render(<LandingPage />)
    const header = screen.getByRole("banner")
    expect(within(header).getByRole("link", { name: "Log in" })).toHaveAttribute("href", "/login")
    unmount()

    useAuthStore.getState().setAuth("token-1", { id: "u1", email: "a@b.com" })
    render(<LandingPage />)
    const signedIn = screen.getByRole("banner")
    expect(within(signedIn).getByRole("link", { name: "Dashboard" })).toHaveAttribute("href", "/dashboard")
    expect(within(signedIn).queryByRole("link", { name: "Log in" })).toBeNull()
  })

  it("switches every plan between monthly and discounted annual prices", async () => {
    const user = userEvent.setup()
    render(<LandingPage />)

    expect(screen.getByTestId("price-29")).toHaveTextContent("£29")
    expect(screen.getByTestId("price-90")).toHaveTextContent("£90")
    expect(screen.getAllByText("Billed monthly")).toHaveLength(3)

    await user.click(screen.getByRole("switch", { name: "Annual billing" }))

    // 12 months less 20%.
    expect(screen.getByTestId("price-29")).toHaveTextContent("£278")
    expect(screen.getByTestId("price-90")).toHaveTextContent("£864")
    expect(screen.getByTestId("price-0")).toHaveTextContent("£0")
    expect(screen.getAllByText("Billed annually")).toHaveLength(3)
  })

  it("only lets a valid email through, then hands it to sign-up prefilled", async () => {
    const user = userEvent.setup()
    render(<LandingPage />)

    const submit = screen.getByRole("button", { name: /send me jobs/i })
    const input = screen.getByLabelText("Email address")
    expect(submit).toBeDisabled()

    await user.type(input, "not-an-email")
    expect(submit).toBeDisabled()

    await user.clear(input)
    await user.type(input, "jo+test@example.com")
    expect(submit).toBeEnabled()
    await user.click(submit)

    // No mailing-list backend exists — it must not claim a subscription.
    expect(push).toHaveBeenCalledWith("/register?email=jo%2Btest%40example.com")
    expect(screen.queryByText(/subscribed/i)).toBeNull()
  })
})
