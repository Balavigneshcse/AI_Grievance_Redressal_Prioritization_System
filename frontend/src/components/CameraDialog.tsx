import { useCallback, useEffect, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import { Camera, Loader2, SwitchCamera } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { getPosition, type Gps } from "@/lib/geo"

export interface CapturedPhoto {
  blob: Blob
  gps: Gps | null
}

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCapture: (photo: CapturedPhoto) => void
}

type Facing = "environment" | "user"

export function CameraDialog({ open, onOpenChange, onCapture }: Props) {
  const { t } = useTranslation()
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const [facing, setFacing] = useState<Facing>("environment")
  const [starting, setStarting] = useState(false)
  const [capturing, setCapturing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const stop = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
    if (videoRef.current) videoRef.current.srcObject = null
  }, [])

  // Callback ref: attach the stream whichever mounts first, the video or the stream.
  const setVideo = useCallback((el: HTMLVideoElement | null) => {
    videoRef.current = el
    if (el && streamRef.current) {
      el.srcObject = streamRef.current
      void el.play().catch(() => undefined)
    }
  }, [])

  useEffect(() => {
    if (!open) {
      stop()
      return
    }
    let cancelled = false
    const start = async () => {
      setStarting(true)
      setError(null)
      if (!navigator.mediaDevices?.getUserMedia) {
        setError("camera.unsupported")
        setStarting(false)
        return
      }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: facing }, width: { ideal: 1280 }, height: { ideal: 960 } },
          audio: false,
        })
        if (cancelled) {
          stream.getTracks().forEach((track) => track.stop())
          return
        }
        streamRef.current = stream
        if (videoRef.current) {
          videoRef.current.srcObject = stream
          await videoRef.current.play().catch(() => undefined)
        }
      } catch (err) {
        const denied = err instanceof DOMException && (err.name === "NotAllowedError" || err.name === "SecurityError")
        setError(denied ? "camera.denied" : "camera.failed")
      } finally {
        if (!cancelled) setStarting(false)
      }
    }
    void start()
    return () => {
      cancelled = true
      stop()
    }
  }, [open, facing, stop])

  const capture = async () => {
    const video = videoRef.current
    if (!video || !video.videoWidth) return
    setCapturing(true)
    // Ask for the GPS fix at the moment the photo is taken.
    const gpsPromise = getPosition()
    try {
      const canvas = document.createElement("canvas")
      canvas.width = video.videoWidth
      canvas.height = video.videoHeight
      const ctx = canvas.getContext("2d")
      if (!ctx) throw new Error("no canvas context")
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
      const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.9))
      if (!blob) throw new Error("toBlob failed")
      const gps = await gpsPromise
      onCapture({ blob, gps })
      onOpenChange(false)
    } catch {
      setError("camera.failed")
    } finally {
      setCapturing(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("camera.title")}</DialogTitle>
          <DialogDescription>{t("camera.description")}</DialogDescription>
        </DialogHeader>

        <div className="relative aspect-[4/3] w-full overflow-hidden rounded-lg bg-black">
          <video ref={setVideo} autoPlay playsInline muted className="size-full object-cover" />
          {starting ? (
            <div className="absolute inset-0 flex items-center justify-center text-white">
              <Loader2 className="size-6 animate-spin" />
            </div>
          ) : null}
          <Button
            type="button"
            variant="secondary"
            size="icon-sm"
            className="absolute top-2 right-2"
            aria-label={t("camera.switch")}
            onClick={() => setFacing((f) => (f === "environment" ? "user" : "environment"))}
          >
            <SwitchCamera />
          </Button>
        </div>

        {error ? (
          <Alert variant="destructive">
            <AlertDescription>{t(error)}</AlertDescription>
          </Alert>
        ) : null}

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            {t("common.cancel")}
          </Button>
          <Button type="button" onClick={() => void capture()} disabled={starting || capturing || !!error}>
            {capturing ? <Loader2 className="animate-spin" /> : <Camera />}
            {t("camera.capture")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
