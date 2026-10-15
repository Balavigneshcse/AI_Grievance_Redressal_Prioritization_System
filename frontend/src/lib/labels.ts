import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  GitMerge,
  HelpCircle,
  Inbox,
  Info,
  Loader2,
  Route,
  Search,
  ShieldAlert,
  Wrench,
  XCircle,
  type LucideIcon,
} from "lucide-react"
import type { Department, DepartmentRef, Status, Urgency } from "@/lib/types"
import type { Lang } from "@/lib/i18n"

export interface BadgeSpec {
  icon: LucideIcon
  /** i18n key */
  label: string
  /** Tailwind classes for the badge */
  className: string
  /** extra classes for the icon (e.g. spin) */
  iconClassName?: string
}

export const STATUS_ORDER: Status[] = [
  "received",
  "analysing",
  "under_review",
  "routed",
  "in_progress",
  "resolved",
  "closed",
  "merged",
  "awaiting_info",
]

export const STATUS: Record<Status, BadgeSpec> = {
  received: {
    icon: Inbox,
    label: "status.received",
    className: "border-sky-200 bg-sky-50 text-sky-800",
  },
  analysing: {
    icon: Loader2,
    label: "status.analysing",
    className: "border-violet-200 bg-violet-50 text-violet-800",
    iconClassName: "animate-spin",
  },
  under_review: {
    icon: Search,
    label: "status.under_review",
    className: "border-indigo-200 bg-indigo-50 text-indigo-800",
  },
  routed: {
    icon: Route,
    label: "status.routed",
    className: "border-blue-200 bg-blue-50 text-blue-800",
  },
  in_progress: {
    icon: Wrench,
    label: "status.in_progress",
    className: "border-amber-200 bg-amber-50 text-amber-800",
  },
  resolved: {
    icon: CheckCircle2,
    label: "status.resolved",
    className: "border-emerald-200 bg-emerald-50 text-emerald-800",
  },
  closed: {
    icon: XCircle,
    label: "status.closed",
    className: "border-slate-200 bg-slate-100 text-slate-700",
  },
  merged: {
    icon: GitMerge,
    label: "status.merged",
    className: "border-fuchsia-200 bg-fuchsia-50 text-fuchsia-800",
  },
  awaiting_info: {
    icon: HelpCircle,
    label: "status.awaiting_info",
    className: "border-orange-200 bg-orange-50 text-orange-800",
  },
}

export const URGENCY_ORDER: Urgency[] = ["critical", "high", "medium", "low"]

export const URGENCY: Record<Urgency, BadgeSpec> = {
  critical: {
    icon: ShieldAlert,
    label: "urgency.critical",
    className: "border-red-600 bg-red-600 text-white",
  },
  high: {
    icon: AlertTriangle,
    label: "urgency.high",
    className: "border-orange-500 bg-orange-500 text-white",
  },
  medium: {
    icon: AlertCircle,
    label: "urgency.medium",
    className: "border-amber-400 bg-amber-400 text-amber-950",
  },
  low: {
    icon: Info,
    label: "urgency.low",
    className: "border-slate-300 bg-slate-200 text-slate-800",
  },
}

export function statusSpec(status: string | null | undefined): BadgeSpec {
  return (
    (status && STATUS[status as Status]) || {
      icon: Info,
      label: "status.unknown",
      className: STATUS.closed.className,
    }
  )
}

export function urgencySpec(urgency: string | null | undefined): BadgeSpec | null {
  if (!urgency) return null
  return URGENCY[urgency as Urgency] ?? null
}

/** "Live" statuses: the track page keeps polling while in one of these. */
export function isLiveStatus(status: string | null | undefined): boolean {
  return status === "received" || status === "analysing"
}

export const DEPARTMENT_IDS = [
  "water",
  "electricity",
  "roads",
  "sanitation",
  "health",
  "safety",
  "revenue",
  "general",
] as const

/** Resolve a department (id string or object) to its name in the given language. */
export function departmentName(
  dep: DepartmentRef,
  lang: Lang,
  departments: Department[] = [],
  fallback = "",
): string {
  if (!dep) return fallback
  const obj: Department | undefined =
    typeof dep === "string" ? departments.find((d) => d.id === dep) : dep
  if (!obj) return typeof dep === "string" ? dep : fallback
  const key = ("name_" + lang) as "name_en" | "name_ta" | "name_hi"
  return obj[key] || obj.name_en || obj.id
}

export const LANGUAGE_NAMES: Record<string, string> = {
  en: "English",
  ta: "தமிழ்",
  hi: "हिन्दी",
  "ta-en": "Tanglish",
  "hi-en": "Hinglish",
}
