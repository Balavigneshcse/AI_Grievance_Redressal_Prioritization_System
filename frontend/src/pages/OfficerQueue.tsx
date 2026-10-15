import { useCallback, useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { useTranslation } from "react-i18next"
import { Filter, Inbox, RefreshCw } from "lucide-react"
import { toast } from "sonner"
import { api, ApiError } from "@/lib/api"
import type { QueueItem, QueueView } from "@/lib/types"
import { useAuth } from "@/lib/auth"
import { useDepartments } from "@/lib/departments"
import { LANGUAGE_NAMES, URGENCY_ORDER } from "@/lib/labels"
import { formatAge, formatDue } from "@/lib/format"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { FlagBadge, StatusBadge, UrgencyBadge } from "@/components/Badges"

const ALL = "all"
const LANG_FILTERS = ["en", "ta", "hi"]
const DASH = "—"
const VIEWS: QueueView[] = ["review", "active", "resolved", "all"]
/** The queue refreshes itself so new complaints show up without a reload. */
const REFRESH_MS = 5000

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
  const { user } = useAuth()
  const { departments, name } = useDepartments()
  const deptScoped = user?.role === "dept_admin"
  const superAdmin = user?.role === "super_admin"
  const [view, setView] = useState<QueueView>(deptScoped ? "active" : "review")
  const [department, setDepartment] = useState(ALL)
  const [urgency, setUrgency] = useState(ALL)
  const [language, setLanguage] = useState(ALL)
  const [district, setDistrict] = useState(ALL)
  const [districts, setDistricts] = useState<Option[]>([])
  const [items, setItems] = useState<QueueItem[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const inFlight = useRef(false)

  const load = useCallback(
    async (silent = false) => {
      if (inFlight.current) return
      inFlight.current = true
      if (silent) setRefreshing(true)
      else setLoading(true)
      const qs = new URLSearchParams({ view })
      if (department !== ALL) qs.set("department", department)
      if (urgency !== ALL) qs.set("urgency", urgency)
      if (language !== ALL) qs.set("language", language)
      if (district !== ALL) qs.set("district", district)
      try {
        const list = await api<QueueItem[]>(`/review/queue?${qs.toString()}`)
        setItems(Array.isArray(list) ? list : [])
      } catch (err) {
        setItems((prev) => prev ?? [])
        if (!silent) toast.error(err instanceof ApiError && err.message !== "network_error" ? err.message : t("errors.network"))
      } finally {
        inFlight.current = false
        setLoading(false)
        setRefreshing(false)
      }
    },
    [view, department, urgency, language, district, t],
  )

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") void load(true)
    }, REFRESH_MS)
    return () => window.clearInterval(id)
  }, [load])

  useEffect(() => {
    if (!superAdmin) return
    api<{ id: string; name: string; staff: number }[]>("/admin/districts")
      .then((rows) => setDistricts(rows.map((d) => ({ value: d.name, label: d.name }))))
      .catch(() => setDistricts([]))
  }, [superAdmin])

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
  const districtItems: Option[] = [{ value: ALL, label: t("queue.allDistricts") }, ...districts]

  const go = (id: string) => navigate(`/officer/c/${id}`)
  const scopeLabel = deptScoped
    ? `${name(user?.department_id ?? null, DASH)}${user?.district ? ` · ${user.district}` : ""}`
    : user?.role === "district_admin"
      ? user.district
      : null

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <h1 className="font-heading text-xl font-semibold">{t(`queue.view.${view}`)}</h1>
          {scopeLabel ? <p className="truncate text-xs text-muted-foreground">{scopeLabel}</p> : null}
        </div>
        <Button
          variant="ghost"
          size="icon"
          aria-label={t("common.refresh")}
          onClick={() => void load()}
          disabled={loading}
        >
          <RefreshCw className={loading || refreshing ? "animate-spin" : undefined} />
        </Button>
      </div>

      <Tabs value={view} onValueChange={(v) => setView(v as QueueView)}>
        <TabsList className="w-full">
          {VIEWS.map((v) => (
            <TabsTrigger key={v} value={v} className="flex-1">
              {t(`queue.view.${v}`)}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      <Card size="sm">
        <CardContent className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          <div className="flex items-center gap-2 sm:col-span-3">
            <Filter className="size-4 text-muted-foreground" />
            <span className="text-sm font-medium">{t("queue.filters")}</span>
            <span className="ml-auto text-xs text-muted-foreground">{t("queue.autoRefresh")}</span>
          </div>
          {!deptScoped ? (
            <FilterSelect value={department} onChange={setDepartment} items={deptItems} label={t("queue.department")} />
          ) : null}
          <FilterSelect value={urgency} onChange={setUrgency} items={urgencyItems} label={t("queue.urgency")} />
          <FilterSelect value={language} onChange={setLanguage} items={langItems} label={t("queue.language")} />
          {superAdmin ? (
            <FilterSelect value={district} onChange={setDistrict} items={districtItems} label={t("queue.district")} />
          ) : null}
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
                <TableHead>{t("queue.status")}</TableHead>
                {!deptScoped ? <TableHead>{t("queue.department")}</TableHead> : null}
                {superAdmin ? <TableHead>{t("queue.district")}</TableHead> : null}
                <TableHead>{t("queue.language")}</TableHead>
                <TableHead>{t("queue.flags")}</TableHead>
                <TableHead className="text-right">{t("queue.age")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(items ?? []).map((q) => {
                const due = formatDue(q.due_at, t)
                return (
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
                  <TableCell className="font-mono font-medium">
                    {q.tracking_id}
                    {q.complainant_name ? (
                      <span className="block max-w-32 truncate font-sans text-xs font-normal text-muted-foreground">
                        {q.complainant_name}
                      </span>
                    ) : null}
                  </TableCell>
                  <TableCell className="max-w-72 whitespace-normal">
                    <span className="line-clamp-2 text-sm">{q.summary_en ?? DASH}</span>
                    {typeof q.confidence === "number" ? (
                      <span className="text-xs text-muted-foreground">
                        {t("queue.confidence", { pct: Math.round(q.confidence * 100) })}
                      </span>
                    ) : null}
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={q.status} />
                  </TableCell>
                  {!deptScoped ? <TableCell>{name(q.department, DASH)}</TableCell> : null}
                  {superAdmin ? <TableCell>{q.district ?? DASH}</TableCell> : null}
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
                  <TableCell className="text-right text-muted-foreground">
                    {formatAge(q.created_at, t)}
                    {due ? (
                      <span className={cn("block text-xs", due.overdue ? "font-medium text-red-600" : "")}>{due.label}</span>
                    ) : null}
                  </TableCell>
                </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </Card>
      )}
    </div>
  )
}
