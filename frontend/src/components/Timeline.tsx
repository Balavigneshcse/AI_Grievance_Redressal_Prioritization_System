import { useTranslation } from "react-i18next"
import { CheckCircle2, Circle } from "lucide-react"
import type { TimelineEntry } from "@/lib/types"
import { statusSpec, isLiveStatus } from "@/lib/labels"
import { formatDateTime } from "@/lib/format"
import { cn } from "@/lib/utils"

export function Timeline({ entries, currentStatus }: { entries: TimelineEntry[]; currentStatus: string }) {
  const { t, i18n } = useTranslation()
  const sorted = [...entries].sort(
    (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
  )
  const live = isLiveStatus(currentStatus)

  if (sorted.length === 0) {
    return <p className="text-sm text-muted-foreground">{t("track.noTimeline")}</p>
  }

  return (
    <ol className="relative ml-2.5 border-l border-border pl-5">
      {sorted.map((e, i) => {
        const last = i === sorted.length - 1
        const Icon = last ? Circle : CheckCircle2
        const spec = statusSpec(e.to_status)
        return (
          <li key={`${e.created_at}-${i}`} className={cn("relative pb-5 last:pb-0")}>
            <span
              className={cn(
                "absolute -left-[31px] top-0.5 flex size-5 items-center justify-center rounded-full bg-background",
                last ? "text-primary" : "text-emerald-600",
              )}
            >
              <Icon className={cn("size-5", last && live && "animate-pulse")} />
            </span>
            <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
              <span className="text-sm font-medium">{t(spec.label)}</span>
              {e.actor_type ? (
                <span className="text-xs text-muted-foreground">
                  {t(`actor.${e.actor_type}`, { defaultValue: e.actor_type })}
                </span>
              ) : null}
            </div>
            {e.note ? <p className="mt-0.5 text-sm text-muted-foreground">{e.note}</p> : null}
            <time className="mt-0.5 block text-xs text-muted-foreground" dateTime={e.created_at}>
              {formatDateTime(e.created_at, i18n.language)}
            </time>
          </li>
        )
      })}
    </ol>
  )
}
