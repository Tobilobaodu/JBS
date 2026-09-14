import { apiFetch } from "@/lib/api"
import { useAuthStore } from "@/store/auth-store"
import { useTailoredCvStore } from "@/store/tailored-cv-store"

export type AuthUserResponse = {
  id: string
  email: string
  fullName?: string | null
  accountStatus: string
  createdAt: string
}

export type LoginResponse = {
  accessToken: string
  refreshToken: string
  user: AuthUserResponse
}

export function registerAccount(email: string, password: string, fullName?: string) {
  return apiFetch<AuthUserResponse>("/auth/register", {
    method: "POST",
    body: fullName ? { email, password, fullName } : { email, password },
  })
}

export function loginAccount(email: string, password: string) {
  return apiFetch<LoginResponse>("/auth/login", {
    method: "POST",
    body: { email, password },
  })
}

export function logoutAccount() {
  return apiFetch<void>("/auth/logout", { method: "POST" })
}

/** Revokes the session server-side, then clears local auth state — in that
 *  order. apiFetch reads the bearer token from the store synchronously at
 *  call time, so clearing first would send the revoke request with no
 *  Authorization header and the backend would reject it, leaving the old
 *  session live until its own expiry despite the user "logging out".
 *  Best-effort: a failed revoke shouldn't trap the user in a session they
 *  clicked out of. */
export function performLogout() {
  void logoutAccount().catch(() => {})
  useAuthStore.getState().clearAuth()
  // A carried-over tailored CV is personal data; don't leave it for the
  // next person on this tab.
  useTailoredCvStore.getState().clear()
}
