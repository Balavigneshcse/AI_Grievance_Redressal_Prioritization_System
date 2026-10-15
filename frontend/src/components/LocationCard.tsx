import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { MapContainer, Marker, TileLayer, useMap, useMapEvents } from "react-leaflet"
import L from "leaflet"
import "leaflet/dist/leaflet.css"
import markerIcon2x from "leaflet/dist/images/marker-icon-2x.png"
import markerIcon from "leaflet/dist/images/marker-icon.png"
import markerShadow from "leaflet/dist/images/marker-shadow.png"
import { Loader2, LocateFixed, MapPin } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { api } from "@/lib/api"
import { DEFAULT_CENTER, getPosition } from "@/lib/geo"
import type { GeoReverse, LocationSource } from "@/lib/types"

const pinIcon = L.icon({
  iconUrl: markerIcon,
  iconRetinaUrl: markerIcon2x,
  shadowUrl: markerShadow,
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
  shadowSize: [41, 41],
})

export interface LocationState {
  lat: number | null
  lng: number | null
  source: LocationSource
  manualAddress: string
  resolved: GeoReverse | null
}

export const EMPTY_LOCATION: LocationState = {
  lat: null,
  lng: null,
  source: "none",
  manualAddress: "",
  resolved: null,
}

interface Props {
  value: LocationState
  onChange: (patch: Partial<LocationState>) => void
}

function Recenter({ center }: { center: [number, number] | null }) {
  const map = useMap()
  useEffect(() => {
    if (center) map.flyTo(center, Math.max(map.getZoom(), 15), { duration: 0.6 })
  }, [center?.[0], center?.[1]]) // eslint-disable-line react-hooks/exhaustive-deps
  return null
}

function ClickToPlace({ onPlace }: { onPlace: (lat: number, lng: number) => void }) {
  useMapEvents({
    click: (e) => onPlace(e.latlng.lat, e.latlng.lng),
  })
  return null
}

export function LocationCard({ value, onChange }: Props) {
  const { t } = useTranslation()
  const [locating, setLocating] = useState(false)
  const [manualOpen, setManualOpen] = useState(value.manualAddress.length > 0)
  const hasPin = value.lat != null && value.lng != null
  const center: [number, number] = hasPin ? [value.lat as number, value.lng as number] : DEFAULT_CENTER

  const reverse = async (lat: number, lng: number) => {
    try {
      const place = await api<GeoReverse>("/geo/reverse", { body: { lat, lng } })
      onChange({ resolved: place })
    } catch {
      onChange({ resolved: null })
    }
  }

  const place = (lat: number, lng: number, source: LocationSource) => {
    onChange({ lat, lng, source })
    void reverse(lat, lng)
  }

  const locateMe = async () => {
    setLocating(true)
    const pos = await getPosition()
    setLocating(false)
    if (!pos) {
      toast.error(t("location.unavailable"))
      return
    }
    place(pos.lat, pos.lng, "browser")
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <MapPin className="size-4" />
          {t("location.title")}
        </CardTitle>
        <CardDescription>{t("location.hint")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="isolate z-0 overflow-hidden rounded-lg ring-1 ring-foreground/10">
          <MapContainer
            center={center}
            zoom={hasPin ? 15 : 12}
            scrollWheelZoom={false}
            style={{ height: 200, width: "100%" }}
            className="z-0"
          >
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            <ClickToPlace onPlace={(lat, lng) => place(lat, lng, "manual")} />
            <Recenter center={hasPin ? center : null} />
            {hasPin ? (
              <Marker
                position={center}
                icon={pinIcon}
                draggable
                eventHandlers={{
                  dragend: (e) => {
                    const ll = (e.target as L.Marker).getLatLng()
                    place(ll.lat, ll.lng, "manual")
                  },
                }}
              />
            ) : null}
          </MapContainer>
        </div>

        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <Button type="button" variant="outline" onClick={() => void locateMe()} disabled={locating}>
            {locating ? <Loader2 className="animate-spin" /> : <LocateFixed />}
            {t("location.useCurrent")}
          </Button>
          <Button
            type="button"
            variant="outline"
            aria-expanded={manualOpen}
            onClick={() => setManualOpen((v) => !v)}
          >
            <MapPin />
            {t("location.enterManually")}
          </Button>
        </div>

        {manualOpen ? (
          <div className="space-y-1.5">
            <Label htmlFor="manual-address">{t("location.addressLabel")}</Label>
            <Input
              id="manual-address"
              placeholder={t("location.addressPlaceholder")}
              value={value.manualAddress}
              onChange={(e) =>
                onChange({
                  manualAddress: e.target.value,
                  source: e.target.value ? "manual" : hasPin ? value.source : "none",
                })
              }
            />
          </div>
        ) : null}

        {value.resolved ? (
          <Alert>
            <MapPin />
            <AlertTitle>{value.resolved.name}</AlertTitle>
            <AlertDescription>
              {value.resolved.area}
              {typeof value.resolved.distance_km === "number"
                ? ` · ${t("location.distance", { km: value.resolved.distance_km.toFixed(1) })}`
                : ""}
            </AlertDescription>
          </Alert>
        ) : null}

        {hasPin ? (
          <p className="text-xs text-muted-foreground">
            {t("location.coords", {
              lat: (value.lat as number).toFixed(5),
              lng: (value.lng as number).toFixed(5),
            })}{" "}
            · {t(`locationSource.${value.source}`)}
          </p>
        ) : (
          <p className="text-xs text-muted-foreground">{t("location.none")}</p>
        )}
      </CardContent>
    </Card>
  )
}
