import { useAuthStore } from "@/store/auth-store"
import { useTrialStore } from "@/store/trial-store"

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1"

export class ApiError extends Error {
  status: number
  body: unknown

  constructor(status: number, body: unknown, message?: string) {
    super(message ?? `Request failed with status ${status}`)
    this.name = "ApiError"
    this.status = status
    this.body = body
  }
}

type ApiFetchOptions = Omit<RequestInit, "body"> & {
  body?: unknown
}

/**
 * Sends the account's bearer token when logged in, otherwise falls back to
 * the anonymous trial session header — never both (mirrors the backend's
 * own precedence in get_current_user_or_trial_session).
 */
function buildIdentityHeaders(): Record<string, string> {
  const accessToken = useAuthStore.getState().accessToken
  if (accessToken) {
    return { Authorization: `Bearer ${accessToken}` }
  }

  const trialSessionId = useTrialStore.getState().trialSessionId
  if (trialSessionId) {
    return { "X-Trial-Session-Id": trialSessionId }
  }

  return {}
}

export async function apiFetch<T>(
  path: string,
  options: ApiFetchOptions = {}
): Promise<T> {
  const { body, headers, ...rest } = options
  const isFormData = body instanceof FormData

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...rest,
    headers: {
      ...(isFormData ? {} : { "Content-Type": "application/json" }),
      ...buildIdentityHeaders(),
      ...headers,
    },
    body: isFormData ? body : body !== undefined ? JSON.stringify(body) : undefined,
  })

  if (response.status === 401) {
    useAuthStore.getState().clearAuth()
  }

  if (!response.ok) {
    let parsedBody: unknown = null
    try {
      parsedBody = await response.json()
    } catch {
      // response had no JSON body
    }
    throw new ApiError(response.status, parsedBody)
  }

  if (response.status === 204) {
    return undefined as T
  }

  return (await response.json()) as T
}

/** Like apiFetch, but for binary responses (e.g. file downloads) — returns a Blob instead of parsing JSON.
 *  Accepts a body so a download can be produced by a POST, which the PDF
 *  export needs: the rewrite is stateless, so the Markdown to render is
 *  sent with the request rather than referenced by id. */
export async function apiFetchBlob(
  path: string,
  options: ApiFetchOptions = {}
): Promise<Blob> {
  const { body, headers, ...rest } = options
  const isFormData = body instanceof FormData

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...rest,
    headers: {
      ...(isFormData || body === undefined
        ? {}
        : { "Content-Type": "application/json" }),
      ...buildIdentityHeaders(),
      ...headers,
    },
    body: isFormData ? body : body !== undefined ? JSON.stringify(body) : undefined,
  })

  if (response.status === 401) {
    useAuthStore.getState().clearAuth()
  }

  if (!response.ok) {
    let parsedBody: unknown = null
    try {
      parsedBody = await response.json()
    } catch {
      // response had no JSON body
    }
    throw new ApiError(response.status, parsedBody)
  }

  return await response.blob()
}

/** Like apiFetch, but for a streamed (text/event-stream) response — yields
 *  each SSE `data:` frame's raw text as it arrives, parsed as JSON by the
 *  caller (this function doesn't know the event shape, only the SSE
 *  framing: `data: <text>` lines separated by a blank line).
 *
 *  A generator rather than a callback list — `for await` at the call site
 *  reads naturally and composes with try/catch for the error path, where
 *  a callback-based API would need its own onError plumbing. */
export async function* apiFetchStream(
  path: string,
  options: ApiFetchOptions = {}
): AsyncGenerator<string> {
  const { body, headers, ...rest } = options

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...rest,
    headers: {
      "Content-Type": "application/json",
      ...buildIdentityHeaders(),
      ...headers,
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

  if (response.status === 401) {
    useAuthStore.getState().clearAuth()
  }

  if (!response.ok || !response.body) {
    let parsedBody: unknown = null
    try {
      parsedBody = await response.json()
    } catch {
      // response had no JSON body
    }
    throw new ApiError(response.status, parsedBody)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let frameEnd: number
      // eslint-disable-next-line no-cond-assign
      while ((frameEnd = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, frameEnd)
        buffer = buffer.slice(frameEnd + 2)
        const line = frame.split("\n").find((l) => l.startsWith("data: "))
        if (line) yield line.slice("data: ".length)
      }
    }
  } finally {
    reader.releaseLock()
  }
}

/** FastAPI puts an *array* of issue objects in `detail` for a 422 validation
 *  error, not a string:
 *    { detail: [{ loc: ["body","password"], msg: "String should have at
 *                 least 12 characters", type: "string_too_short" }] }
 *  Without this branch every 422 fell through to the caller's generic
 *  fallback. That is how the frontend/backend password-length mismatch
 *  stayed invisible: the real reason was in the response body and the user
 *  only ever saw "Could not create your account."
 *
 *  The field name is taken from the tail of `loc` ("body" dropped), because
 *  a bare "String should have at least 12 characters" does not say which
 *  input is wrong. */
function validationDetailMessage(detail: unknown): string | null {
  if (!Array.isArray(detail) || detail.length === 0) {
    return null
  }

  const messages: string[] = []
  for (const issue of detail) {
    if (!issue || typeof issue !== "object") continue
    const { msg, loc } = issue as { msg?: unknown; loc?: unknown }
    if (typeof msg !== "string") continue

    let field: string | undefined
    if (Array.isArray(loc)) {
      const parts = loc.filter(
        (part): part is string => typeof part === "string" && part !== "body"
      )
      field = parts.length > 0 ? parts[parts.length - 1] : undefined
    }

    messages.push(field ? `${field}: ${msg}` : msg)
  }

  return messages.length > 0 ? messages.join(" ") : null
}

/** Extracts a human-readable message from the backend's HTTPException body shape ({"detail": "..."}). */
export function errorMessage(error: unknown, fallback: string): string {
  if (
    error instanceof ApiError &&
    error.body &&
    typeof error.body === "object" &&
    "detail" in error.body
  ) {
    const { detail } = error.body as { detail?: unknown }
    if (typeof detail === "string") {
      return detail
    }
    const validationMessage = validationDetailMessage(detail)
    if (validationMessage !== null) {
      return validationMessage
    }
  }
  return fallback
}
