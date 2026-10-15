import { useCallback, useEffect, useRef, useState } from "react"
import { api, ApiError } from "@/lib/api"
import type { Complaint } from "@/lib/types"
import { isLiveStatus } from "@/lib/labels"

/** Loads a complaint and polls every 3 s while it is still received/analysing. */
export function useComplaint(id: string | undefined, intervalMs = 3000) {
  const [complaint, setComplaint] = useState<Complaint | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const timer = useRef<number | null>(null)

  const load = useCallback(async () => {
    if (!id) return
    try {
      const data = await api<Complaint>(`/complaints/${encodeURIComponent(id)}`)
      setComplaint(data)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "network_error")
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    setLoading(true)
    setComplaint(null)
    void load()
  }, [load])

  useEffect(() => {
    if (timer.current) window.clearTimeout(timer.current)
    if (!complaint || !isLiveStatus(complaint.status)) return
    timer.current = window.setTimeout(() => void load(), intervalMs)
    return () => {
      if (timer.current) window.clearTimeout(timer.current)
    }
  }, [complaint, load, intervalMs])

  return { complaint, error, loading, reload: load }
}
