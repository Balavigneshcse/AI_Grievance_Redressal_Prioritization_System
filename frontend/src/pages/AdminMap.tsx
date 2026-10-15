import { useCallback, useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { useTranslation } from "react-i18next"
import { CircleMarker, MapContainer, Popup, TileLayer, useMap } from "react-leaflet"
import L from "leaflet"
import "leaflet/dist/leaflet.css"
import { ArrowLeft, MapPinned, RefreshCw } from "lucide-react"
import { toast } from "sonner"
import { api, ApiError } from "@/lib/api"
import { useDepartments } from "@/lib/departments"
import { DEFAULT_CENTER } from "@/lib/geo"
import type { MapPoint, Urgency } from "@/lib/types"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { StatusBadge, UrgencyBadge } from "@/components/Badges"

const COLORS: Record<Urgency, string> = { critical: "#dc2626", high: "#ea580c", medium: "#d97706", low: "#16a34a" }
const REFRESH_MS = 15000

function FitBounds({ points }: { points: MapPoint[] }) {
  const map = useMap()
  useEffect(() => {
    if (points.length === 0) return
    const bounds = L.latLngBounds(points.map((p) => [p.lat, p.lng] as [number, number]))
    map.fitBounds(bounds.pad(0.2), { maxZoom: 14 })
  }, [points, map])
  return null
}

export default function AdminMap() {
  const { t } = useTranslation()
  const { name } = useDepartments()
  const [view, setView] = useState<"open" | "all">("open")
  const [points, setPoints] = useState<MapPoint[] | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(
    async (silent = false) => {
      if (!silent) setLoading(true)
      try {
        const rows = await api<MapPoint[]>(`/admin/map?view=${view}`)
        setPoints(Array.isArray(rows) ? rows : [])
      } catch (err) {
        if (!silent) toast.error(err instanceof ApiError && err.message !== "network_error" ? err.message : t("errors.network"))
        setPoints((prev) => prev ?? [])
      } finally {
        setLoading(false)
      }
    },
    [view, t],
  )

  useEffect(() => {
    void load()
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") void load(true)
    }, REFRESH_MS)
    return () => window.clearInterval(id)
  }, [load])

  const counts = useMemo(() => {
    const c: Record<string, number> = { critical: 0, high: 0, medium: 0, low: 0, overdue: 0 }
    for (const p of points ?? []) {
      if (p.urgency) c[p.urgency] = (c[p.urgency] ?? 0) + 1
      if (p.overdue) c.overdue += 1
    }
    return c
  }, [points])

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="icon" nativeButton={false} render={<Link to="/officer/queue" aria-label={t("common.back")} />}>
          <ArrowLeft />
        </Button>
        <div className="min-w-0">
          <h1 className="flex items-center gap-2 font-heading text-xl font-semibold">
            <MapPinned className="size-5" />
            {t("map.title")}
          </h1>
          <p className="text-xs text-muted-foreground">{t("map.hint")}</p>
        </div>
        <Button variant="ghost" size="icon" className="ml-auto" aria-label={t("common.refresh")} onClick={() => void load()} disabled={loading}>
          <RefreshCw className={loading ? "animate-spin" : undefined} />
        </Button>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Tabs value={view} onValueChange={(v) => setView(v as "open" | "all")}>
          <TabsList>
            <TabsTrigger value="open">{t("map.open")}</TabsTrigger>
            <TabsTrigger value="all">{t("map.all")}</TabsTrigger>
          </TabsList>
        </Tabs>
        <div className="ml-auto flex flex-wrap items-center gap-1.5 text-xs">
          {(["critical", "high", "medium", "low"] as Urgency[]).map((u) => (
            <span key={u} className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5">
              <span className="size-2.5 rounded-full" style={{ background: COLORS[u] }} />
              {t(`urgency.${u}`)} {counts[u]}
            </span>
          ))}
          <span className="inline-flex items-center gap-1 rounded-full border border-red-300 px-2 py-0.5 text-red-700">
            <span className="size-2.5 rounded-full border-2 border-red-600" />
            {t("flag.overdue")} {counts.overdue}
          </span>
        </div>
      </div>

      {loading && !points ? (
        <Skeleton className="h-[60vh] w-full rounded-xl" />
      ) : (
        <Card className="overflow-hidden py-0">
          <CardContent className="p-0">
            <div className="h-[60vh] min-h-80 w-full">
              <MapContainer center={DEFAULT_CENTER} zoom={11} scrollWheelZoom className="size-full">
                <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" />
                <FitBounds points={points ?? []} />
                {(points ?? []).map((p) => {
                  const color = p.urgency ? COLORS[p.urgency] : "#64748b"
                  return (
                    <CircleMarker
                      key={p.id}
                      center={[p.lat, p.lng]}
                      radius={7 + Math.min(6, p.supporters)}
                      pathOptions={{ color: p.overdue ? "#dc2626" : color, weight: p.overdue ? 3 : 1.5, fillColor: color, fillOpacity: 0.75 }}
                    >
                      <Popup>
                        <div className="space-y-1 text-sm">
                          <div className="flex flex-wrap items-center gap-1">
                            <span className="font-mono font-semibold">{p.tracking_id}</span>
                            <StatusBadge status={p.status} />
                            <UrgencyBadge urgency={p.urgency} />
                            {p.overdue ? <Badge variant="destructive">{t("flag.overdue")}</Badge> : null}
                          </div>
                          <p className="text-xs text-muted-foreground">
                            {name(p.department, "—")} · {p.district ?? "—"} · {t("nearby.supporters", { count: p.supporters })}
                          </p>
                          {p.summary_en ? <p className="line-clamp-3">{p.summary_en}</p> : null}
                          <Link to={`/officer/c/${p.id}`} className="text-primary underline">
                            {t("map.openCase")}
                          </Link>
                        </div>
                      </Popup>
                    </CircleMarker>
                  )
                })}
              </MapContainer>
            </div>
          </CardContent>
        </Card>
      )}
      <p className="text-xs text-muted-foreground">{t("map.count", { count: points?.length ?? 0 })}</p>
    </div>
  )
}
