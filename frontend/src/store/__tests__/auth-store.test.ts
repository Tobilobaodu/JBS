import { describe, expect, it } from "vitest"
import { useAuthStore, isAuthenticated } from "@/store/auth-store"

describe("auth store", () => {
  it("starts logged out", () => {
    expect(useAuthStore.getState().accessToken).toBeNull()
    expect(useAuthStore.getState().user).toBeNull()
    expect(isAuthenticated()).toBe(false)
  })

  it("setAuth stores the token and user", () => {
    useAuthStore
      .getState()
      .setAuth("token-1", { id: "u1", email: "a@b.com" })

    expect(useAuthStore.getState().accessToken).toBe("token-1")
    expect(useAuthStore.getState().user).toEqual({ id: "u1", email: "a@b.com" })
    expect(isAuthenticated()).toBe(true)
  })

  it("clearAuth resets to logged out", () => {
    useAuthStore.getState().setAuth("token-1", { id: "u1", email: "a@b.com" })
    useAuthStore.getState().clearAuth()

    expect(useAuthStore.getState().accessToken).toBeNull()
    expect(useAuthStore.getState().user).toBeNull()
    expect(isAuthenticated()).toBe(false)
  })

  it("persists to localStorage under the auth-storage key", () => {
    useAuthStore.getState().setAuth("token-1", { id: "u1", email: "a@b.com" })

    const raw = window.localStorage.getItem("auth-storage")
    expect(raw).not.toBeNull()
    const parsed = JSON.parse(raw as string)
    expect(parsed.state.accessToken).toBe("token-1")
  })
})
