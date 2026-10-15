import type { TFunction } from "i18next"

const LOCALES: Record<string, string> = { en: "en-IN", ta: "ta-IN", hi: "hi-IN" }

export function formatDateTime(iso: string | null | undefined, lang: string): string {
  if (!iso) return ""
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  try {
    return new Intl.DateTimeFormat(LOCALES[lang] ?? "en-IN", {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(d)
  } catch {
    return d.toLocaleString()
  }
}

/** Short relative age with i18n suffixes. */
export function formatAge(iso: string | null | undefined, t: TFunction): string {
  if (!iso) return ""
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ""
  const diff = Math.max(0, Date.now() - then)
  const m = Math.floor(diff / 60000)
  if (m < 1) return t("age.now")
  if (m < 60) return t("age.minutes", { count: m })
  const h = Math.floor(m / 60)
  if (h < 24) return t("age.hours", { count: h })
  const d = Math.floor(h / 24)
  return t("age.days", { count: d })
}
