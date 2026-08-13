import { http, HttpResponse } from "msw"

const API_BASE_URL = "http://localhost:8000/api/v1"

export const registerHandler = http.post(`${API_BASE_URL}/auth/register`, async () => {
  return HttpResponse.json(
    {
      id: "user-1",
      email: "test@example.com",
      accountStatus: "active",
      createdAt: new Date().toISOString(),
    },
    { status: 201 }
  )
})

export const loginHandler = http.post(`${API_BASE_URL}/auth/login`, async () => {
  return HttpResponse.json({
    accessToken: "test-access-token",
    refreshToken: "test-refresh-token",
    user: {
      id: "user-1",
      email: "test@example.com",
      accountStatus: "active",
      createdAt: new Date().toISOString(),
    },
  })
})

export const loginInvalidHandler = http.post(`${API_BASE_URL}/auth/login`, async () => {
  return HttpResponse.json({ detail: "Invalid email or password." }, { status: 401 })
})

export const registerConflictHandler = http.post(`${API_BASE_URL}/auth/register`, async () => {
  return HttpResponse.json(
    { detail: "An account with this email already exists." },
    { status: 409 }
  )
})

export const handlers = [registerHandler, loginHandler]
