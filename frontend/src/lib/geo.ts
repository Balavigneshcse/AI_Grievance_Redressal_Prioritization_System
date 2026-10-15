import { api } from "@/lib/api"
import type { GeoReverse } from "@/lib/types"

export interface Gps {
  lat: number
  lng: number
  accuracy: number
}

/** Resolve the current position, or null when unavailable/denied/timeout. */
export function getPosition(timeoutMs = 8000): Promise<Gps | null> {
  return new Promise((resolve) => {
    if (!("geolocation" in navigator)) {
      resolve(null)
      return
    }
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ lat: p.coords.latitude, lng: p.coords.longitude, accuracy: p.coords.accuracy }),
      () => resolve(null),
      { enableHighAccuracy: true, timeout: timeoutMs, maximumAge: 30000 },
    )
  })
}

/** POST /geo/reverse; null when the API is unreachable (non-fatal for the UI). */
export async function reverseGeocode(lat: number, lng: number): Promise<GeoReverse | null> {
  try {
    return await api<GeoReverse>("/geo/reverse", { body: { lat, lng } })
  } catch {
    return null
  }
}

/** Chennai, used as the map centre before any location is known. */
export const DEFAULT_CENTER: [number, number] = [13.0827, 80.2707]
