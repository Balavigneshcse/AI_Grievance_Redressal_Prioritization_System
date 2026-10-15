import { useTranslation } from "react-i18next"
import { Badge } from "@/components/ui/badge"
import { statusSpec, urgencySpec } from "@/lib/labels"
import { cn } from "@/lib/utils"

export function StatusBadge({ status, className }: { status: string | null | undefined; className?: string }) {
  const { t } = useTranslation()
  const spec = statusSpec(status)
  const Icon = spec.icon
  return (
    <Badge variant="outline" className={cn(spec.className, className)}>
      <Icon className={spec.iconClassName} />
      {t(spec.label)}
    </Badge>
  )
}

export function UrgencyBadge({ urgency, className }: { urgency: string | null | undefined; className?: string }) {
  const { t } = useTranslation()
  const spec = urgencySpec(urgency)
  if (!spec) return null
  const Icon = spec.icon
  return (
    <Badge variant="outline" className={cn(spec.className, className)}>
      <Icon />
      {t(spec.label)}
    </Badge>
  )
}

export function FlagBadge({ flag }: { flag: string }) {
  const { t } = useTranslation()
  const key = `flag.${flag}`
  const label = t(key, { defaultValue: flag.replace(/_/g, " ") })
  return (
    <Badge variant="secondary" className="h-auto max-w-full whitespace-normal py-0.5 text-[11px]">
      {label}
    </Badge>
  )
}
