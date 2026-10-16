import i18n from "@/lib/i18n"
import { ApiError } from "@/lib/api"

const camel = (id: string) => id.replace(/_([a-z])/g, (_, c: string) => c.toUpperCase())

/** Parameters the API sends as ids (a status, a decision, the rules a password misses), in the app's language. */
function localParams(params: Record<string, unknown>): Record<string, unknown> {
  const out = { ...params }
  if (typeof out.status === "string") out.status = i18n.t(`status.${out.status}`, { defaultValue: out.status })
  if (typeof out.action === "string") out.action = i18n.t(`decision.${camel(out.action)}`, { defaultValue: out.action })
  if (Array.isArray(out.missing))
    out.missing = out.missing.map((rule) => i18n.t(`password.missing.${rule}`, { defaultValue: String(rule) }))
  return out
}

/**
 * The message to show for a failed request, in the app's language. The API sends every refusal with a
 * stable code and its parameters (backend/app/errors.py), shown here as apiErrors.<code>. A code the app
 * does not know shows the API's English message; FastAPI's own 422 field list follows a translated lead-in;
 * a server failure shows errors.generic and a failed connection errors.network.
 */
export function errorText(err: unknown): string {
  if (!(err instanceof ApiError) || err.message === "network_error") return i18n.t("errors.network")
  if (err.code && i18n.exists(`apiErrors.${err.code}`)) return i18n.t(`apiErrors.${err.code}`, localParams(err.params ?? {}))
  if (err.status === 422) return i18n.t("errors.invalid", { details: err.message })
  if (err.status >= 500 || !err.message) return i18n.t("errors.generic")
  return err.message
}
