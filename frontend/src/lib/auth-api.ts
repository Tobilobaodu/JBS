import { apiFetch } from "@/lib/api"

export type AuthUserResponse = {
  id: string
  email: string
  accountStatus: string
  createdAt: string
}

export type LoginResponse = {
  accessToken: string
  refreshToken: string
  user: AuthUserResponse
}

export function registerAccount(email: string, password: string) {
  return apiFetch<AuthUserResponse>("/auth/register", {
    method: "POST",
    body: { email, password },
  })
}

export function loginAccount(email: string, password: string) {
  return apiFetch<LoginResponse>("/auth/login", {
    method: "POST",
    body: { email, password },
  })
}
