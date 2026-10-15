import { useCallback, useEffect, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import { Camera, Circle, Loader2, Square, SwitchCamera, Video } from "lucide-react"
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
import { cn } from "@/lib/utils"

/** Evidence limits, mirrored by the API (MAX_PHOTO_MB, MAX_VIDEO_MB, MAX_VIDEO_SECONDS). */
export const MAX_PHOTO_MB = 25
export const MAX_VIDEO_MB = 100
export const MAX_VIDEO_SECONDS = 300

export interface CapturedMedia {
  blob: Blob
  gps: Gps | null
  kind: "photo" | "video"
  durationS?: number
}
/** Older name kept for callers that only knew photos. */
export type CapturedPhoto = CapturedMedia

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCapture: (media: CapturedMedia) => void
}

type Facing = "environment" | "user"
type Mode = "photo" | "video"

function pickMime(): string | undefined {
  if (typeof MediaRecorder === "undefined") return undefined
  return ["video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm", "video/mp4"].find((m) =>
    MediaRecorder.isTypeSupported(m),
  )
}

function clock(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
}

export function CameraDialog({ open, onOpenChange, onCapture }: Props) {
  const { t } = useTranslation()
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const timerRef = useRef<number | null>(null)
  const elapsedRef = useRef(0)
  const gpsRef = useRef<Promise<Gps | null> | null>(null)
  const [facing, setFacing] = useState<Facing>("environment")
  const [mode, setMode] = useState<Mode>("photo")
  const [starting, setStarting] = useState(false)
  const [capturing, setCapturing] = useState(false)
  const [recording, setRecording] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [noAudio, setNoAudio] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const clearTimer = () => {
    if (timerRef.current != null) window.clearInterval(timerRef.current)
    timerRef.current = null
  }

  const stop = useCallback(() => {
    clearTimer()
    const rec = recorderRef.current
    if (rec && rec.state !== "inactive") {
      rec.onstop = null // closing the dialog discards a half recording
      rec.stop()
    }
    recorderRef.current = null
    setRecording(false)
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
      setMode("photo")
      setError(null)
      return
    }
    let cancelled = false
    const start = async () => {
      setStarting(true)
      setError(null)
      setNoAudio(false)
      if (!navigator.mediaDevices?.getUserMedia) {
        setError("camera.unsupported")
        setStarting(false)
        return
      }
      const video = { facingMode: { ideal: facing }, width: { ideal: 1280 }, height: { ideal: 720 } }
      try {
        let stream: MediaStream
        try {
          stream = await navigator.mediaDevices.getUserMedia({ video, audio: mode === "video" })
        } catch (err) {
          // No microphone or mic permission denied: record video without sound.
          if (mode !== "video") throw err
          stream = await navigator.mediaDevices.getUserMedia({ video, audio: false })
          setNoAudio(true)
        }
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
  }, [open, facing, mode, stop])

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
      onCapture({ blob, gps, kind: "photo" })
      onOpenChange(false)
    } catch {
      setError("camera.failed")
    } finally {
      setCapturing(false)
    }
  }

  const finishRecording = async (blob: Blob, seconds: number) => {
    if (blob.size > MAX_VIDEO_MB * 1024 * 1024) {
      setError("camera.tooLarge")
      return
    }
    const gps = await (gpsRef.current ?? Promise.resolve(null))
    onCapture({ blob, gps, kind: "video", durationS: seconds })
    onOpenChange(false)
  }

  const stopRecording = useCallback(() => {
    clearTimer()
    const rec = recorderRef.current
    if (rec && rec.state !== "inactive") rec.stop()
    setRecording(false)
  }, [])

  const startRecording = () => {
    const stream = streamRef.current
    if (!stream) return
    const mime = pickMime()
    if (!mime) {
      setError("camera.recordUnsupported")
      return
    }
    chunksRef.current = []
    const rec = new MediaRecorder(stream, { mimeType: mime, videoBitsPerSecond: 1_500_000 })
    rec.ondataavailable = (e) => {
      if (e.data.size > 0) chunksRef.current.push(e.data)
    }
    rec.onstop = () => {
      const blob = new Blob(chunksRef.current, { type: mime.split(";")[0] })
      void finishRecording(blob, elapsedRef.current)
    }
    gpsRef.current = getPosition()
    elapsedRef.current = 0
    setElapsed(0)
    rec.start(1000)
    recorderRef.current = rec
    setRecording(true)
    timerRef.current = window.setInterval(() => {
      elapsedRef.current += 1
      setElapsed(elapsedRef.current)
      if (elapsedRef.current >= MAX_VIDEO_SECONDS) stopRecording()
    }, 1000)
  }

  const busy = starting || capturing

  return (
    <Dialog open={open} onOpenChange={(o) => (!o && recording ? undefined : onOpenChange(o))}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{mode === "video" ? t("camera.videoTitle") : t("camera.title")}</DialogTitle>
          <DialogDescription>
            {mode === "video"
              ? t("camera.videoDescription", { minutes: MAX_VIDEO_SECONDS / 60, mb: MAX_VIDEO_MB })
              : t("camera.description")}
          </DialogDescription>
        </DialogHeader>

        <div className="grid grid-cols-2 gap-2" role="radiogroup" aria-label={t("camera.mode")}>
          <Button
            type="button"
            size="sm"
            variant={mode === "photo" ? "default" : "outline"}
            aria-pressed={mode === "photo"}
            disabled={recording}
            onClick={() => setMode("photo")}
          >
            <Camera />
            {t("camera.photoMode")}
          </Button>
          <Button
            type="button"
            size="sm"
            variant={mode === "video" ? "default" : "outline"}
            aria-pressed={mode === "video"}
            disabled={recording}
            onClick={() => setMode("video")}
          >
            <Video />
            {t("camera.videoMode")}
          </Button>
        </div>

        <div className="relative aspect-[4/3] w-full overflow-hidden rounded-lg bg-black">
          <video ref={setVideo} autoPlay playsInline muted className="size-full object-cover" />
          {starting ? (
            <div className="absolute inset-0 flex items-center justify-center text-white">
              <Loader2 className="size-6 animate-spin" />
            </div>
          ) : null}
          {recording ? (
            <div className="absolute top-2 left-2 flex items-center gap-1.5 rounded-full bg-black/60 px-2 py-1 font-mono text-xs text-white">
              <Circle className="size-2.5 animate-pulse fill-red-500 text-red-500" />
              {clock(elapsed)} / {clock(MAX_VIDEO_SECONDS)}
            </div>
          ) : null}
          <Button
            type="button"
            variant="secondary"
            size="icon-sm"
            className="absolute top-2 right-2"
            aria-label={t("camera.switch")}
            disabled={recording}
            onClick={() => setFacing((f) => (f === "environment" ? "user" : "environment"))}
          >
            <SwitchCamera />
          </Button>
        </div>

        {noAudio && mode === "video" ? (
          <p className="text-xs text-muted-foreground">{t("camera.noAudio")}</p>
        ) : null}

        {error ? (
          <Alert variant="destructive">
            <AlertDescription>{t(error, { mb: MAX_VIDEO_MB })}</AlertDescription>
          </Alert>
        ) : null}

        <DialogFooter>
          <Button type="button" variant="outline" disabled={recording} onClick={() => onOpenChange(false)}>
            {t("common.cancel")}
          </Button>
          {mode === "photo" ? (
            <Button type="button" onClick={() => void capture()} disabled={busy || !!error}>
              {capturing ? <Loader2 className="animate-spin" /> : <Camera />}
              {t("camera.capture")}
            </Button>
          ) : recording ? (
            <Button type="button" variant="destructive" onClick={stopRecording}>
              <Square className={cn("fill-current")} />
              {t("camera.stop")}
            </Button>
          ) : (
            <Button type="button" onClick={startRecording} disabled={busy || !!error}>
              <Circle className="fill-red-500 text-red-500" />
              {t("camera.record")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
