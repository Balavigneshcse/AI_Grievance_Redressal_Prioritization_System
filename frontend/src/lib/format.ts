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

/** Time left until (or elapsed since) a due time. */
export function formatDue(iso: string | null | undefined, t: TFunction): { label: string; overdue: boolean } | null {
  if (!iso) return null
  const due = new Date(iso).getTime()
  if (Number.isNaN(due)) return null
  const diff = due - Date.now()
  const overdue = diff < 0
  const m = Math.floor(Math.abs(diff) / 60000)
  const h = Math.floor(m / 60)
  const d = Math.floor(h / 24)
  const span = d >= 1 ? t("due.days", { count: d }) : h >= 1 ? t("due.hours", { count: h }) : t("due.minutes", { count: m })
  return { label: overdue ? t("due.overdueBy", { time: span }) : t("due.in", { time: span }), overdue }
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
