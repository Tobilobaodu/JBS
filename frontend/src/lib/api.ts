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

/** Like apiFetch, but for binary responses (e.g. file downloads) — returns a Blob instead of parsing JSON. */
export async function apiFetchBlob(
  path: string,
  options: Omit<ApiFetchOptions, "body"> = {}
): Promise<Blob> {
  const { headers, ...rest } = options

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...rest,
    headers: {
      ...buildIdentityHeaders(),
      ...headers,
    },
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

/** Extracts a human-readable message from the backend's HTTPException body shape ({"detail": "..."}). */
export function errorMessage(error: unknown, fallback: string): string {
  if (
    error instanceof ApiError &&
    error.body &&
    typeof error.body === "object" &&
    "detail" in error.body &&
    typeof (error.body as { detail?: unknown }).detail === "string"
  ) {
    return (error.body as { detail: string }).detail
  }
  return fallback
}
