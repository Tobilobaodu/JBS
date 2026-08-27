import { describe, expect, it } from "vitest"
import { http, HttpResponse } from "msw"
import { server } from "@/test/msw/server"
import { apiFetch, ApiError, errorMessage } from "@/lib/api"
import { useAuthStore } from "@/store/auth-store"
import { useTrialStore } from "@/store/trial-store"

const BASE = "http://localhost:8000/api/v1"

describe("apiFetch identity headers", () => {
  it("attaches Authorization when logged in", async () => {
    useAuthStore.setState({
      accessToken: "abc123",
      user: { id: "u1", email: "a@b.com" },
    })

    let receivedAuth: string | null = null
    let receivedTrial: string | null = null
    server.use(
      http.get(`${BASE}/echo`, ({ request }) => {
        receivedAuth = request.headers.get("Authorization")
        receivedTrial = request.headers.get("X-Trial-Session-Id")
        return HttpResponse.json({ ok: true })
      })
    )

    await apiFetch("/echo")
    expect(receivedAuth).toBe("Bearer abc123")
    expect(receivedTrial).toBeNull()
  })

  it("falls back to X-Trial-Session-Id when logged out", async () => {
    useTrialStore.setState({
      trialSessionId: "trial-1",
      expiresAt: new Date().toISOString(),
    })

    let receivedAuth: string | null = null
    let receivedTrial: string | null = null
    server.use(
      http.get(`${BASE}/echo`, ({ request }) => {
        receivedAuth = request.headers.get("Authorization")
        receivedTrial = request.headers.get("X-Trial-Session-Id")
        return HttpResponse.json({ ok: true })
      })
    )

    await apiFetch("/echo")
    expect(receivedAuth).toBeNull()
    expect(receivedTrial).toBe("trial-1")
  })

  it("prefers the bearer token over a trial session when both are present", async () => {
    useAuthStore.setState({
      accessToken: "abc123",
      user: { id: "u1", email: "a@b.com" },
    })
    useTrialStore.setState({
      trialSessionId: "trial-1",
      expiresAt: new Date().toISOString(),
    })

    let receivedAuth: string | null = null
    let receivedTrial: string | null = null
    server.use(
      http.get(`${BASE}/echo`, ({ request }) => {
        receivedAuth = request.headers.get("Authorization")
        receivedTrial = request.headers.get("X-Trial-Session-Id")
        return HttpResponse.json({ ok: true })
      })
    )

    await apiFetch("/echo")
    expect(receivedAuth).toBe("Bearer abc123")
    expect(receivedTrial).toBeNull()
  })

  it("sends neither header with no identity", async () => {
    let receivedAuth: string | null = null
    let receivedTrial: string | null = null
    server.use(
      http.get(`${BASE}/echo`, ({ request }) => {
        receivedAuth = request.headers.get("Authorization")
        receivedTrial = request.headers.get("X-Trial-Session-Id")
        return HttpResponse.json({ ok: true })
      })
    )

    await apiFetch("/echo")
    expect(receivedAuth).toBeNull()
    expect(receivedTrial).toBeNull()
  })

  it("clears the auth store on a 401 response", async () => {
    useAuthStore.setState({
      accessToken: "abc123",
      user: { id: "u1", email: "a@b.com" },
    })
    server.use(
      http.get(`${BASE}/echo`, () =>
        HttpResponse.json({ detail: "Unauthorized" }, { status: 401 })
      )
    )

    await expect(apiFetch("/echo")).rejects.toThrow(ApiError)
    expect(useAuthStore.getState().accessToken).toBeNull()
  })

  it("throws ApiError with status and parsed body on a non-ok response", async () => {
    server.use(
      http.get(`${BASE}/echo`, () =>
        HttpResponse.json({ detail: "boom" }, { status: 409 })
      )
    )

    try {
      await apiFetch("/echo")
      expect.unreachable("apiFetch should have thrown")
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError)
      expect((error as ApiError).status).toBe(409)
      expect((error as ApiError).body).toEqual({ detail: "boom" })
    }
  })

  it("sends FormData bodies without a Content-Type header (browser sets the boundary)", async () => {
    let receivedContentType: string | null = null
    server.use(
      http.post(`${BASE}/upload`, ({ request }) => {
        receivedContentType = request.headers.get("Content-Type")
        return HttpResponse.json({ ok: true })
      })
    )

    const formData = new FormData()
    formData.append("file", new Blob(["x"]), "test.pdf")
    await apiFetch("/upload", { method: "POST", body: formData })

    expect(receivedContentType).not.toBe("application/json")
  })
})

describe("errorMessage", () => {
  function apiError(status: number, body: unknown) {
    return new ApiError(status, body)
  }

  it("returns a string detail unchanged", () => {
    expect(
      errorMessage(apiError(409, { detail: "Already exists." }), "fallback")
    ).toBe("Already exists.")
  })

  it("extracts msg and field from a FastAPI 422 detail array", () => {
    const body = {
      detail: [
        {
          type: "string_too_short",
          loc: ["body", "password"],
          msg: "String should have at least 12 characters",
          ctx: { min_length: 12 },
        },
      ],
    }
    expect(errorMessage(apiError(422, body), "fallback")).toBe(
      "password: String should have at least 12 characters"
    )
  })

  it("joins multiple validation issues", () => {
    const body = {
      detail: [
        { loc: ["body", "email"], msg: "value is not a valid email address" },
        { loc: ["body", "password"], msg: "String should have at least 12 characters" },
      ],
    }
    expect(errorMessage(apiError(422, body), "fallback")).toBe(
      "email: value is not a valid email address " +
        "password: String should have at least 12 characters"
    )
  })

  it("omits the field prefix when loc carries no usable field name", () => {
    const body = { detail: [{ loc: ["body"], msg: "Invalid payload" }] }
    expect(errorMessage(apiError(422, body), "fallback")).toBe("Invalid payload")
  })

  it("falls back when detail is an empty array or has no usable msg", () => {
    expect(errorMessage(apiError(422, { detail: [] }), "fallback")).toBe("fallback")
    expect(
      errorMessage(apiError(422, { detail: [{ loc: ["body"] }] }), "fallback")
    ).toBe("fallback")
  })

  it("falls back for a non-ApiError or a body without detail", () => {
    expect(errorMessage(new Error("boom"), "fallback")).toBe("fallback")
    expect(errorMessage(apiError(500, { message: "nope" }), "fallback")).toBe(
      "fallback"
    )
  })
})
