export const API_URL: string =
  (import.meta.env.VITE_API_URL as string | undefined) || "http://localhost:8000"

export const TOKEN_KEY = "synapse_token"

/**
 * The login lives in sessionStorage, so every browser tab keeps its own user: the demo runs
 * the citizen, the department admin, the district admin and the super admin in four tabs of
 * one browser, and a login in one tab must not replace the token the other tabs send.
 * localStorage only remembers the last login, so a new tab or a restarted browser starts as
 * that user; the first read pins it to the tab.
 */
export function getToken(): string | null {
  try {
    const own = sessionStorage.getItem(TOKEN_KEY)
    if (own) return own
    const last = localStorage.getItem(TOKEN_KEY)
    if (last) sessionStorage.setItem(TOKEN_KEY, last)
    return last
  } catch {
    return null
  }
}

export class ApiError extends Error {
  status: number
  /** The stable code of an API refusal and its parameters (backend/app/errors.py); errorText() in
   *  lib/errors.ts shows them in the app's language. The message stays the API's English text. */
  code?: string
  params?: Record<string, unknown>
  constructor(message: string, status: number, code?: string, params?: Record<string, unknown>) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.code = code
    this.params = params
  }
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE"
  body?: unknown
  signal?: AbortSignal
  headers?: Record<string, string>
}

/** Resolve a possibly-relative URL returned by the API against the API base. */
export function resolveApiUrl(url: string): string {
  if (/^https?:\/\//i.test(url) || url.startsWith("blob:") || url.startsWith("data:")) return url
  return `${API_URL.replace(/\/$/, "")}/${url.replace(/^\//, "")}`
}

async function parseError(res: Response): Promise<ApiError> {
  try {
    const data = (await res.json()) as { detail?: unknown; code?: unknown; params?: unknown }
    const code = typeof data.code === "string" ? data.code : undefined
    const params = data.params && typeof data.params === "object" ? (data.params as Record<string, unknown>) : undefined
    if (typeof data.detail === "string") return new ApiError(data.detail, res.status, code, params)
    if (Array.isArray(data.detail)) {
      // FastAPI validation errors
      const message = data.detail
        .map((d: { msg?: string; loc?: unknown[] }) =>
          d.loc ? `${d.loc.slice(-1)[0]}: ${d.msg ?? ""}` : d.msg ?? "",
        )
        .join("; ")
      return new ApiError(message, res.status)
    }
    return new ApiError(res.statusText || `HTTP ${res.status}`, res.status, code, params)
  } catch {
    return new ApiError(res.statusText || `HTTP ${res.status}`, res.status)
  }
}

/**
 * Tiny fetch wrapper: adds the bearer token, serialises JSON bodies (FormData is
 * passed through untouched), parses JSON and throws ApiError(detail) on non-2xx.
 */
export async function api<T = unknown>(path: string, opts: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json", ...(opts.headers ?? {}) }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`

  let body: BodyInit | undefined
  if (opts.body instanceof FormData) {
    body = opts.body
  } else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json"
    body = JSON.stringify(opts.body)
  }

  let res: Response
  try {
    res = await fetch(resolveApiUrl(path), {
      method: opts.method ?? (body ? "POST" : "GET"),
      headers,
      body,
      signal: opts.signal,
    })
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err
    throw new ApiError("network_error", 0)
  }

  if (!res.ok) {
    const error = await parseError(res)
    if (res.status === 401) window.dispatchEvent(new CustomEvent("synapse:unauthorized"))
    throw error
  }
  if (res.status === 204) return undefined as T
  const text = await res.text()
  if (!text) return undefined as T
  return JSON.parse(text) as T
}

/** The only media types the app renders. A blob URL is same-origin, so a file that can carry script
 *  (SVG, HTML) opened from one could read the login; anything off this list is refused here. */
export const SAFE_MEDIA_TYPES = new Set(["image/jpeg", "image/png", "image/webp", "video/webm", "video/mp4", "video/quicktime"])

/** Fetch a protected media file as a blob and return an object URL (caller revokes).
 *  Throws ApiError("unsupported_media", 415) for any type outside SAFE_MEDIA_TYPES. */
export async function fetchMediaObjectUrl(url: string, signal?: AbortSignal): Promise<string> {
  const headers: Record<string, string> = {}
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  const res = await fetch(resolveApiUrl(url), { headers, signal })
  if (!res.ok) throw await parseError(res)
  const type = (res.headers.get("content-type") || "").split(";")[0].trim().toLowerCase()
  if (!SAFE_MEDIA_TYPES.has(type)) throw new ApiError("unsupported_media", 415)
  return URL.createObjectURL(new Blob([await res.arrayBuffer()], { type }))
}
