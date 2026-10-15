import { useEffect, useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { useTranslation } from "react-i18next"
import { Building2, ChevronRight, Inbox, Plus, RefreshCw } from "lucide-react"
import { toast } from "sonner"
import { api, ApiError } from "@/lib/api"
import type { ComplaintSummary } from "@/lib/types"
import { useDepartments } from "@/lib/departments"
import { formatAge } from "@/lib/format"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { StatusBadge, UrgencyBadge } from "@/components/Badges"

export default function MyComplaints() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { name } = useDepartments()
  const [items, setItems] = useState<ComplaintSummary[] | null>(null)
  const [loading, setLoading] = useState(true)

  const load = async () => {
    setLoading(true)
    try {
      const list = await api<ComplaintSummary[]>("/complaints/mine")
      setItems(Array.isArray(list) ? list : [])
    } catch (err) {
      setItems((prev) => prev ?? [])
      toast.error(err instanceof ApiError && err.message !== "network_error" ? err.message : t("errors.network"))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2">
        <h1 className="font-heading text-xl font-semibold">{t("home.title")}</h1>
        <Button variant="ghost" size="icon" aria-label={t("common.refresh")} onClick={() => void load()} disabled={loading}>
          <RefreshCw className={loading ? "animate-spin" : undefined} />
        </Button>
      </div>

      {loading && !items ? (
        <div className="space-y-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-24 w-full rounded-xl" />
          ))}
        </div>
      ) : items && items.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-8 text-center">
            <span className="flex size-12 items-center justify-center rounded-full bg-muted">
              <Inbox className="size-6 text-muted-foreground" />
            </span>
            <div>
              <p className="font-medium">{t("home.emptyTitle")}</p>
              <p className="text-sm text-muted-foreground">{t("home.emptyHint")}</p>
            </div>
            <Button onClick={() => navigate("/new")}>
              <Plus />
              {t("home.new")}
            </Button>
          </CardContent>
        </Card>
      ) : (
        <ul className="space-y-3">
          {(items ?? []).map((c) => {
            const dept = name(c.department)
            return (
              <li key={c.id}>
                <Link to={`/c/${c.id}`} className="block rounded-xl focus-visible:outline-2 focus-visible:outline-ring">
                  <Card size="sm" className="transition-colors hover:bg-muted/40">
                    <CardContent className="flex items-start gap-3">
                      <div className="min-w-0 flex-1 space-y-1.5">
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                          <span className="font-mono text-sm font-semibold tracking-wide">{c.tracking_id}</span>
                          <span className="text-xs text-muted-foreground">{formatAge(c.created_at, t)}</span>
                        </div>
                        <div className="flex flex-wrap items-center gap-1.5">
                          <StatusBadge status={c.status} />
                          <UrgencyBadge urgency={c.urgency} />
                        </div>
                        {dept ? (
                          <p className="flex items-center gap-1 text-xs text-muted-foreground">
                            <Building2 className="size-3.5" />
                            {dept}
                          </p>
                        ) : null}
                        {c.summary_en ? (
                          <p className="line-clamp-2 text-sm text-muted-foreground">{c.summary_en}</p>
                        ) : null}
                      </div>
                      <ChevronRight className="mt-1 size-4 shrink-0 text-muted-foreground" />
                    </CardContent>
                  </Card>
                </Link>
              </li>
            )
          })}
        </ul>
      )}

      <Button
        size="lg"
        className="fixed right-4 bottom-4 z-30 h-12 rounded-full px-5 shadow-lg"
        onClick={() => navigate("/new")}
      >
        <Plus />
        {t("home.new")}
      </Button>
    </div>
  )
}
