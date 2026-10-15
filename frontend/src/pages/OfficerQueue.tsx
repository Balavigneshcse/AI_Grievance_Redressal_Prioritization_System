import { useCallback, useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { useTranslation } from "react-i18next"
import { Filter, Inbox, RefreshCw } from "lucide-react"
import { toast } from "sonner"
import { api, ApiError } from "@/lib/api"
import type { QueueItem } from "@/lib/types"
import { useDepartments } from "@/lib/departments"
import { LANGUAGE_NAMES, URGENCY_ORDER } from "@/lib/labels"
import { formatAge } from "@/lib/format"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { FlagBadge, UrgencyBadge } from "@/components/Badges"

const ALL = "all"
const LANG_FILTERS = ["en", "ta", "hi"]
const DASH = "—"

interface Option {
  value: string
  label: string
}

function FilterSelect({
  value,
  onChange,
  items,
  label,
}: {
  value: string
  onChange: (v: string) => void
  items: Option[]
  label: string
}) {
  return (
    <Select value={value} onValueChange={(v) => onChange(v ?? ALL)} items={items}>
      <SelectTrigger className="w-full" aria-label={label}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {items.map((o) => (
          <SelectItem key={o.value} value={o.value}>
            {o.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

export default function OfficerQueue() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { departments, name } = useDepartments()
  const [department, setDepartment] = useState(ALL)
  const [urgency, setUrgency] = useState(ALL)
  const [language, setLanguage] = useState(ALL)
  const [items, setItems] = useState<QueueItem[] | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    const qs = new URLSearchParams()
    if (department !== ALL) qs.set("department", department)
    if (urgency !== ALL) qs.set("urgency", urgency)
    if (language !== ALL) qs.set("language", language)
    const suffix = qs.toString() ? `?${qs.toString()}` : ""
    try {
      const list = await api<QueueItem[]>(`/review/queue${suffix}`)
      setItems(Array.isArray(list) ? list : [])
    } catch (err) {
      setItems((prev) => prev ?? [])
      toast.error(err instanceof ApiError && err.message !== "network_error" ? err.message : t("errors.network"))
    } finally {
      setLoading(false)
    }
  }, [department, urgency, language, t])

  useEffect(() => {
    void load()
  }, [load])

  const deptItems: Option[] = [
    { value: ALL, label: t("queue.allDepartments") },
    ...departments.map((d) => ({ value: d.id, label: name(d.id) })),
  ]
  const urgencyItems: Option[] = [
    { value: ALL, label: t("queue.allUrgencies") },
    ...URGENCY_ORDER.map((u) => ({ value: u, label: t(`urgency.${u}`) })),
  ]
  const langItems: Option[] = [
    { value: ALL, label: t("queue.allLanguages") },
    ...LANG_FILTERS.map((l) => ({ value: l, label: LANGUAGE_NAMES[l] ?? l })),
  ]

  const go = (id: string) => navigate(`/officer/c/${id}`)

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2">
        <h1 className="font-heading text-xl font-semibold">{t("queue.title")}</h1>
        <Button
          variant="ghost"
          size="icon"
          aria-label={t("common.refresh")}
          onClick={() => void load()}
          disabled={loading}
        >
          <RefreshCw className={loading ? "animate-spin" : undefined} />
        </Button>
      </div>

      <Card size="sm">
        <CardContent className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          <div className="flex items-center gap-2 sm:col-span-3">
            <Filter className="size-4 text-muted-foreground" />
            <span className="text-sm font-medium">{t("queue.filters")}</span>
          </div>
          <FilterSelect value={department} onChange={setDepartment} items={deptItems} label={t("queue.department")} />
          <FilterSelect value={urgency} onChange={setUrgency} items={urgencyItems} label={t("queue.urgency")} />
          <FilterSelect value={language} onChange={setLanguage} items={langItems} label={t("queue.language")} />
        </CardContent>
      </Card>

      {loading && !items ? (
        <Skeleton className="h-48 w-full rounded-xl" />
      ) : items && items.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-2 py-8 text-center">
            <Inbox className="size-6 text-muted-foreground" />
            <p className="font-medium">{t("queue.empty")}</p>
          </CardContent>
        </Card>
      ) : (
        <Card className="py-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("queue.urgency")}</TableHead>
                <TableHead>{t("queue.trackingId")}</TableHead>
                <TableHead className="min-w-56">{t("queue.summary")}</TableHead>
                <TableHead>{t("queue.department")}</TableHead>
                <TableHead>{t("queue.language")}</TableHead>
                <TableHead>{t("queue.flags")}</TableHead>
                <TableHead className="text-right">{t("queue.age")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(items ?? []).map((q) => (
                <TableRow
                  key={q.id}
                  role="link"
                  tabIndex={0}
                  className="cursor-pointer"
                  onClick={() => go(q.id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault()
                      go(q.id)
                    }
                  }}
                >
                  <TableCell>
                    <UrgencyBadge urgency={q.urgency} />
                  </TableCell>
                  <TableCell className="font-mono font-medium">{q.tracking_id}</TableCell>
                  <TableCell className="max-w-72 whitespace-normal">
                    <span className="line-clamp-2 text-sm">{q.summary_en ?? DASH}</span>
                    {typeof q.confidence === "number" ? (
                      <span className="text-xs text-muted-foreground">
                        {t("queue.confidence", { pct: Math.round(q.confidence * 100) })}
                      </span>
                    ) : null}
                  </TableCell>
                  <TableCell>{name(q.department, DASH)}</TableCell>
                  <TableCell>
                    {q.language_primary ? (LANGUAGE_NAMES[q.language_primary] ?? q.language_primary) : DASH}
                  </TableCell>
                  <TableCell className="whitespace-normal">
                    <div className="flex max-w-48 flex-wrap gap-1">
                      {(q.flags ?? []).map((f) => (
                        <FlagBadge key={f} flag={f} />
                      ))}
                    </div>
                  </TableCell>
                  <TableCell className="text-right text-muted-foreground">{formatAge(q.created_at, t)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}
    </div>
  )
}
