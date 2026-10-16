import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { Building2, Loader2, MapPin, ThumbsUp, Users } from "lucide-react"
import { toast } from "sonner"
import { api, ApiError } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import type { NearbyItem } from "@/lib/types"
import { useDepartments } from "@/lib/departments"
import { formatAge } from "@/lib/format"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { StatusBadge, UrgencyBadge } from "@/components/Badges"

/** Open complaints near the chosen location: support one instead of filing a duplicate. */
export function NearbyCard({ lat, lng }: { lat: number; lng: number }) {
  const { t } = useTranslation()
  const { user } = useAuth()
  const { name } = useDepartments()
  const [items, setItems] = useState<NearbyItem[] | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  // Only citizens can support, and only from near the complaint: the API checks this same point.
  const canSupport = user?.role === "complainant"
  const here = { lat: Number(lat.toFixed(5)), lng: Number(lng.toFixed(5)) }

  useEffect(() => {
    let cancelled = false
    setItems(null)
    api<NearbyItem[]>(`/complaints/nearby?lat=${lat.toFixed(5)}&lng=${lng.toFixed(5)}`)
      .then((list) => {
        if (!cancelled) setItems(Array.isArray(list) ? list : [])
      })
      .catch(() => {
        if (!cancelled) setItems([])
      })
    return () => {
      cancelled = true
    }
  }, [lat, lng])

  if (!items || items.length === 0) return null

  const support = async (item: NearbyItem) => {
    setBusy(item.id)
    try {
      const r = await api<{ supporters: number; urgency: string | null }>(`/complaints/${item.id}/support`, { body: here })
      setItems((prev) => (prev ?? []).map((i) => (i.id === item.id ? { ...i, supported: true, supporters: r.supporters, urgency: (r.urgency as NearbyItem["urgency"]) ?? i.urgency } : i)))
      toast.success(t("nearby.supported", { id: item.tracking_id, count: r.supporters }))
    } catch (err) {
      toast.error(err instanceof ApiError && err.message !== "network_error" ? err.message : t("errors.network"))
    } finally {
      setBusy(null)
    }
  }

  return (
    <Card className="border-sky-400/60">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Users className="size-4" />
          {t("nearby.title", { count: items.length })}
        </CardTitle>
        <CardDescription>{t("nearby.hint")}</CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="space-y-2">
          {items.map((item) => (
            <li key={item.id} className="flex items-start gap-3 rounded-lg border p-3">
              <div className="min-w-0 flex-1 space-y-1">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span className="font-mono text-sm font-semibold">{item.tracking_id}</span>
                  <StatusBadge status={item.status} />
                  <UrgencyBadge urgency={item.urgency} />
                </div>
                {item.summary_en ? <p className="line-clamp-2 text-sm text-muted-foreground">{item.summary_en}</p> : null}
                <p className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
                  {item.department ? (
                    <span className="inline-flex items-center gap-1">
                      <Building2 className="size-3.5" />
                      {name(item.department)}
                    </span>
                  ) : null}
                  <span className="inline-flex items-center gap-1">
                    <MapPin className="size-3.5" />
                    {t("nearby.distance", { km: item.distance_km })}
                  </span>
                  <span>{formatAge(item.created_at, t)}</span>
                  <span className="inline-flex items-center gap-1">
                    <Users className="size-3.5" />
                    {t("nearby.supporters", { count: item.supporters })}
                  </span>
                </p>
              </div>
              {canSupport ? (
                <Button
                  type="button"
                  size="sm"
                  variant={item.supported ? "secondary" : "default"}
                  disabled={item.supported || busy === item.id}
                  onClick={() => void support(item)}
                >
                  {busy === item.id ? <Loader2 className="animate-spin" /> : <ThumbsUp />}
                  {item.supported ? t("nearby.supportedShort") : t("nearby.support")}
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}
