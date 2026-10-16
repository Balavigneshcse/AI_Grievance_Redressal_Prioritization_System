import { useCallback, useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { useTranslation } from "react-i18next"
import { Activity, ArrowLeft, BarChart3, RefreshCw } from "lucide-react"
import { toast } from "sonner"
import { api } from "@/lib/api"
import { errorText } from "@/lib/errors"
import { useDepartments } from "@/lib/departments"
import { LANGUAGE_NAMES } from "@/lib/labels"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

interface Metrics {
  totals: { complaints: number; critical_open: number; review_rate: number | null; auto_closed: number; mean_latency_ms: number | null }
  by_status: Record<string, number>
  by_department: Record<string, number>
  live_accuracy_by_language: Record<string, { n: number; accuracy: number }>
  eval_runs: Record<string, Record<string, unknown>>
  second_opinion: {
    department?: { held_out_accuracy?: number; per_language?: Record<string, { n: number; accuracy: number }>; recall_per_class?: Record<string, number>; n?: number }
    urgency?: { held_out_accuracy?: number; per_language?: Record<string, { n: number; accuracy: number }>; recall_per_class?: Record<string, number>; n?: number }
  } | null
}

interface Health {
  db: string
  ollama: string
  queue_depth: number
  outbox_pending?: number
  overdue_open?: number
  model_latency_ms?: { last: number | null; mean_last_10: number | null }
}

const REFRESH_MS = 10000

function pct(v: number | null | undefined): string {
  return typeof v === "number" ? `${Math.round(v * 100)}%` : "—"
}

function Bars({ rows, label }: { rows: [string, number][]; label: (k: string) => string }) {
  const max = Math.max(1, ...rows.map(([, n]) => n))
  if (rows.length === 0) return <p className="text-sm text-muted-foreground">—</p>
  return (
    <ul className="space-y-1.5">
      {rows.map(([k, n]) => (
        <li key={k} className="grid grid-cols-[8rem_1fr_2.5rem] items-center gap-2 text-sm">
          <span className="truncate">{label(k)}</span>
          <span className="h-2.5 overflow-hidden rounded-full bg-muted">
            <span className="block h-full rounded-full bg-primary" style={{ width: `${Math.max(2, (n / max) * 100)}%` }} />
          </span>
          <span className="text-right font-mono text-xs">{n}</span>
        </li>
      ))}
    </ul>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="font-heading text-2xl font-semibold">{value}</p>
    </div>
  )
}

export default function AdminMetrics() {
  const { t } = useTranslation()
  const { name } = useDepartments()
  const [m, setM] = useState<Metrics | null>(null)
  const [h, setH] = useState<Health | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const [mm, hh] = await Promise.all([api<Metrics>("/admin/metrics"), api<Health>("/health")])
      setM(mm)
      setH(hh)
    } catch (err) {
      if (!silent) toast.error(errorText(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") void load(true)
    }, REFRESH_MS)
    return () => window.clearInterval(id)
  }, [load])

  const statusRows = Object.entries(m?.by_status ?? {}).sort((a, b) => b[1] - a[1]) as [string, number][]
  const deptRows = Object.entries(m?.by_department ?? {}).sort((a, b) => b[1] - a[1]) as [string, number][]
  const live = Object.entries(m?.live_accuracy_by_language ?? {})
  const so = m?.second_opinion
  const evals = Object.entries(m?.eval_runs ?? {})

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="icon" nativeButton={false} render={<Link to="/admin" aria-label={t("common.back")} />}>
          <ArrowLeft />
        </Button>
        <div className="min-w-0">
          <h1 className="font-heading text-xl font-semibold">{t("admin.metricsTitle")}</h1>
          <p className="text-xs text-muted-foreground">{t("admin.metricsHint")}</p>
        </div>
        <Button variant="ghost" size="icon" className="ml-auto" aria-label={t("common.refresh")} onClick={() => void load()} disabled={loading}>
          <RefreshCw className={loading ? "animate-spin" : undefined} />
        </Button>
      </div>

      {loading && !m ? (
        <Skeleton className="h-40 w-full rounded-xl" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
            <Stat label={t("admin.totalComplaints")} value={String(m?.totals.complaints ?? 0)} />
            <Stat label={t("admin.criticalOpen")} value={String(m?.totals.critical_open ?? 0)} />
            <Stat label={t("admin.reviewRate")} value={pct(m?.totals.review_rate)} />
            <Stat label={t("admin.autoClosed")} value={String(m?.totals.auto_closed ?? 0)} />
            <Stat label={t("admin.meanLatency")} value={m?.totals.mean_latency_ms ? `${(m.totals.mean_latency_ms / 1000).toFixed(1)} s` : "—"} />
          </div>

          <Card size="sm">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Activity className="size-4" />
                {t("admin.health")}
              </CardTitle>
            </CardHeader>
            <CardContent className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
              <div>
                <p className="text-xs text-muted-foreground">DB / Ollama</p>
                <p className="font-medium">
                  {h?.db ?? "—"} / {h?.ollama ?? "—"}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">{t("admin.lastLatency")}</p>
                <p className="font-medium">{h?.model_latency_ms?.last ? `${(h.model_latency_ms.last / 1000).toFixed(1)} s` : "—"}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">{t("admin.outbox")}</p>
                <p className="font-medium">{h?.outbox_pending ?? 0}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">{t("admin.overdueOpen")}</p>
                <p className="font-medium">{h?.overdue_open ?? 0}</p>
              </div>
            </CardContent>
          </Card>

          <div className="grid gap-4 md:grid-cols-2">
            <Card size="sm">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <BarChart3 className="size-4" />
                  {t("admin.byStatus")}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <Bars rows={statusRows} label={(k) => t(`status.${k}`, { defaultValue: k })} />
              </CardContent>
            </Card>
            <Card size="sm">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <BarChart3 className="size-4" />
                  {t("admin.byDepartment")}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <Bars rows={deptRows} label={(k) => (k === "None" || k === "null" ? "—" : name(k, k))} />
              </CardContent>
            </Card>
          </div>

          <Card size="sm">
            <CardHeader>
              <CardTitle>{t("admin.liveAccuracy")}</CardTitle>
            </CardHeader>
            <CardContent>
              {live.length === 0 ? (
                <p className="text-sm text-muted-foreground">{t("admin.noCorrections")}</p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t("queue.language")}</TableHead>
                      <TableHead className="text-right">n</TableHead>
                      <TableHead className="text-right">{t("admin.deptAccuracy")}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {live.map(([lang, v]) => (
                      <TableRow key={lang}>
                        <TableCell>{LANGUAGE_NAMES[lang] ?? lang}</TableCell>
                        <TableCell className="text-right">{v.n}</TableCell>
                        <TableCell className="text-right">{pct(v.accuracy)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>

          {so ? (
            <Card size="sm">
              <CardHeader>
                <CardTitle>{t("admin.secondOpinion")}</CardTitle>
                <CardDescription>
                  {t("admin.deptAccuracy")} {pct(so.department?.held_out_accuracy)} (n={so.department?.n ?? "—"}) · {t("queue.urgency")}{" "}
                  {pct(so.urgency?.held_out_accuracy)} (n={so.urgency?.n ?? "—"})
                </CardDescription>
              </CardHeader>
              <CardContent className="grid gap-4 md:grid-cols-2">
                <div>
                  <p className="mb-1 text-xs text-muted-foreground">{t("admin.deptAccuracy")} · {t("queue.language")}</p>
                  <Bars
                    rows={Object.entries(so.department?.per_language ?? {}).map(([k, v]) => [k, Math.round(v.accuracy * 100)] as [string, number])}
                    label={(k) => LANGUAGE_NAMES[k] ?? k}
                  />
                </div>
                <div>
                  <p className="mb-1 text-xs text-muted-foreground">{t("admin.recallPerDepartment")}</p>
                  <Bars
                    rows={Object.entries(so.department?.recall_per_class ?? {}).map(([k, v]) => [k, Math.round(v * 100)] as [string, number])}
                    label={(k) => name(k, k)}
                  />
                </div>
              </CardContent>
            </Card>
          ) : null}

          {evals.length > 0 ? (
            <Card className="py-0">
              <CardHeader className="pt-4">
                <CardTitle>{t("admin.evalRuns")}</CardTitle>
              </CardHeader>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("admin.model")}</TableHead>
                    <TableHead className="text-right">n</TableHead>
                    <TableHead className="text-right">{t("admin.deptAccuracy")}</TableHead>
                    <TableHead className="text-right">{t("admin.systemDeptAccuracy")}</TableHead>
                    <TableHead className="text-right">{t("admin.criticalRecall")}</TableHead>
                    <TableHead className="text-right">{t("admin.systemCriticalRecall")}</TableHead>
                    <TableHead className="text-right">{t("admin.langId")}</TableHead>
                    <TableHead className="text-right">{t("admin.seconds")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {evals.map(([k, v]) => (
                    <TableRow key={k}>
                      <TableCell className="font-mono text-xs">{String(v.model ?? k)}</TableCell>
                      <TableCell className="text-right">{String(v.n ?? "—")}</TableCell>
                      <TableCell className="text-right">{pct(v.department_accuracy as number | undefined)}</TableCell>
                      <TableCell className="text-right">{pct(v.system_department_accuracy as number | undefined)}</TableCell>
                      <TableCell className="text-right">{pct(v.critical_recall as number | undefined)}</TableCell>
                      <TableCell className="text-right">{pct(v.system_critical_recall as number | undefined)}</TableCell>
                      <TableCell className="text-right">{pct(v.language_id_accuracy as number | undefined)}</TableCell>
                      <TableCell className="text-right">{typeof v.mean_seconds === "number" ? v.mean_seconds.toFixed(1) : "—"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Card>
          ) : null}
        </>
      )}
    </div>
  )
}
