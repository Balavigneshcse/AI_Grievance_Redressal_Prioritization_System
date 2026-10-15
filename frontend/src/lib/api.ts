export const API_URL: string =
  (import.meta.env.VITE_API_URL as string | undefined) || "http://localhost:8000"

export const TOKEN_KEY = "synapse_token"

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.name = "ApiError"
    this.status = status
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

async function parseError(res: Response): Promise<string> {
  try {
    const data = (await res.json()) as { detail?: unknown }
    if (typeof data.detail === "string") return data.detail
    if (Array.isArray(data.detail)) {
      // FastAPI validation errors
      return data.detail
        .map((d: { msg?: string; loc?: unknown[] }) =>
          d.loc ? `${d.loc.slice(-1)[0]}: ${d.msg ?? ""}` : d.msg ?? "",
        )
        .join("; ")
    }
    return res.statusText || `HTTP ${res.status}`
  } catch {
    return res.statusText || `HTTP ${res.status}`
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
    const detail = await parseError(res)
    if (res.status === 401) window.dispatchEvent(new CustomEvent("synapse:unauthorized"))
    throw new ApiError(detail, res.status)
  }
  if (res.status === 204) return undefined as T
  const text = await res.text()
  if (!text) return undefined as T
  return JSON.parse(text) as T
}

/** Fetch a protected media file as a blob and return an object URL (caller revokes). */
export async function fetchMediaObjectUrl(url: string, signal?: AbortSignal): Promise<string> {
  const headers: Record<string, string> = {}
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  const res = await fetch(resolveApiUrl(url), { headers, signal })
  if (!res.ok) throw new ApiError(await parseError(res), res.status)
  const blob = await res.blob()
  return URL.createObjectURL(blob)
}
