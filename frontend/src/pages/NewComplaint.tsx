import { useCallback, useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { useTranslation } from "react-i18next"
import { Camera, CheckCircle2, Loader2, Plus, Send, Upload, Video, X } from "lucide-react"
import { toast } from "sonner"
import { api, ApiError } from "@/lib/api"
import { currentLang } from "@/lib/i18n"
import { detectScript, languageHint } from "@/lib/script"
import { reverseGeocode } from "@/lib/geo"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { CameraDialog, type CapturedPhoto } from "@/components/CameraDialog"
import { EMPTY_LOCATION, LocationCard, type LocationState } from "@/components/LocationCard"
import { StatusBadge } from "@/components/Badges"

interface Attachment {
  id: string
  file: File
  url: string
  kind: "image" | "video"
}

const MAX_FILES = 6
const MIN_TEXT = 10

export default function NewComplaint() {
  const { t, i18n } = useTranslation()
  const navigate = useNavigate()
  const fileInput = useRef<HTMLInputElement | null>(null)
  const textarea = useRef<HTMLTextAreaElement | null>(null)
  const [text, setText] = useState("")
  const [files, setFiles] = useState<Attachment[]>([])
  const [location, setLocation] = useState<LocationState>(EMPTY_LOCATION)
  const [cameraOpen, setCameraOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<{ id: string; tracking_id: string; status: string } | null>(null)

  const script = detectScript(text)

  // Auto-grow fallback for browsers without CSS field-sizing.
  const grow = useCallback(() => {
    const el = textarea.current
    if (!el) return
    el.style.height = "auto"
    el.style.height = `${el.scrollHeight}px`
  }, [])
  useEffect(grow, [text, grow])

  // Revoke preview URLs when the page unmounts.
  const filesRef = useRef(files)
  filesRef.current = files
  useEffect(() => () => filesRef.current.forEach((f) => URL.revokeObjectURL(f.url)), [])

  const patchLocation = useCallback((patch: Partial<LocationState>) => {
    setLocation((prev) => ({ ...prev, ...patch }))
  }, [])

  const addFiles = (list: File[]) => {
    const accepted = list.filter((f) => f.type.startsWith("image/") || f.type.startsWith("video/"))
    if (accepted.length === 0) return
    setFiles((prev) => {
      const room = MAX_FILES - prev.length
      if (room <= 0) {
        toast.error(t("new.tooMany", { max: MAX_FILES }))
        return prev
      }
      if (accepted.length > room) toast.warning(t("new.tooMany", { max: MAX_FILES }))
      const next = accepted.slice(0, room).map((file) => ({
        id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        file,
        url: URL.createObjectURL(file),
        kind: file.type.startsWith("video/") ? ("video" as const) : ("image" as const),
      }))
      return [...prev, ...next]
    })
  }

  const removeFile = (id: string) => {
    setFiles((prev) => {
      const gone = prev.find((f) => f.id === id)
      if (gone) URL.revokeObjectURL(gone.url)
      return prev.filter((f) => f.id !== id)
    })
  }

  const onCapture = ({ blob, gps }: CapturedPhoto) => {
    const file = new File([blob], `photo-${Date.now()}.jpg`, { type: "image/jpeg" })
    addFiles([file])
    if (gps) {
      patchLocation({ lat: gps.lat, lng: gps.lng, source: "camera_gps" })
      void reverseGeocode(gps.lat, gps.lng).then((place) => patchLocation({ resolved: place }))
    }
  }

  const reset = () => {
    setText("")
    files.forEach((f) => URL.revokeObjectURL(f.url))
    setFiles([])
    setLocation(EMPTY_LOCATION)
    setResult(null)
  }

  const submit = async () => {
    const body = text.trim()
    if (body.length < MIN_TEXT) {
      toast.error(t("new.tooShort", { min: MIN_TEXT }))
      textarea.current?.focus()
      return
    }
    setSubmitting(true)
    try {
      const fd = new FormData()
      fd.append("text", body)
      const hint = languageHint(body, currentLang())
      if (hint) fd.append("language_hint", hint)
      if (location.lat != null && location.lng != null) {
        fd.append("lat", String(location.lat))
        fd.append("lng", String(location.lng))
      }
      fd.append("location_source", location.source)
      if (location.manualAddress.trim()) fd.append("manual_address", location.manualAddress.trim())
      files.forEach((f) => fd.append("files", f.file, f.file.name))
      const res = await api<{ id: string; tracking_id: string; status: string }>("/complaints", { body: fd })
      setResult(res)
    } catch (err) {
      toast.error(err instanceof ApiError && err.message !== "network_error" ? err.message : t("errors.network"))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="space-y-4">
      <h1 className="font-heading text-xl font-semibold">{t("new.title")}</h1>

      <Card>
        <CardHeader>
          <CardTitle>{t("new.textLabel")}</CardTitle>
          <CardDescription>{t("new.hint")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <Textarea
            ref={textarea}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={t("new.placeholder")}
            className="min-h-32 resize-none text-base leading-relaxed"
            lang={i18n.language}
            rows={4}
          />
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Badge variant={script === "latin" ? "outline" : "secondary"}>{t(`new.script.${script}`)}</Badge>
            <span className="text-xs text-muted-foreground">{text.trim().length}</span>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("new.attachments")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid grid-cols-2 gap-2">
            <Button type="button" variant="outline" onClick={() => setCameraOpen(true)}>
              <Camera />
              {t("new.camera")}
            </Button>
            <Button type="button" variant="outline" onClick={() => fileInput.current?.click()}>
              <Upload />
              {t("new.upload")}
            </Button>
            <input
              ref={fileInput}
              type="file"
              accept="image/*,video/*"
              multiple
              capture="environment"
              className="sr-only"
              onChange={(e) => {
                addFiles(Array.from(e.target.files ?? []))
                e.target.value = ""
              }}
            />
          </div>

          {files.length > 0 ? (
            <ul className="grid grid-cols-4 gap-2">
              {files.map((f) => (
                <li key={f.id} className="relative aspect-square overflow-hidden rounded-lg bg-muted ring-1 ring-foreground/10">
                  {f.kind === "video" ? (
                    <>
                      <video src={f.url} muted playsInline preload="metadata" className="size-full object-cover" />
                      <Video className="pointer-events-none absolute bottom-1 left-1 size-4 text-white drop-shadow" />
                    </>
                  ) : (
                    <img src={f.url} alt="" className="size-full object-cover" />
                  )}
                  <Button
                    type="button"
                    variant="secondary"
                    size="icon-xs"
                    className="absolute top-1 right-1 rounded-full shadow"
                    aria-label={t("new.remove")}
                    onClick={() => removeFile(f.id)}
                  >
                    <X />
                  </Button>
                </li>
              ))}
            </ul>
          ) : null}
        </CardContent>
      </Card>

      <LocationCard value={location} onChange={patchLocation} />

      <div className="space-y-1.5">
        <Button type="button" className="h-11 w-full text-base" onClick={() => void submit()} disabled={submitting}>
          {submitting ? <Loader2 className="animate-spin" /> : <Send />}
          {t("new.submit")}
        </Button>
        <Label className="justify-center text-xs font-normal text-muted-foreground">
          {t("new.submitHint")}
        </Label>
      </div>

      <CameraDialog open={cameraOpen} onOpenChange={setCameraOpen} onCapture={onCapture} />

      <Sheet open={result !== null} onOpenChange={(o) => !o && setResult(null)}>
        <SheetContent side="bottom" className="rounded-t-2xl">
          <SheetHeader className="items-center text-center">
            <CheckCircle2 className="size-12 text-emerald-600" />
            <SheetTitle className="text-lg">{t("new.successTitle")}</SheetTitle>
            <SheetDescription>{t("new.successHint")}</SheetDescription>
          </SheetHeader>
          <div className="flex flex-col items-center gap-2 px-4">
            <span className="font-mono text-2xl font-semibold tracking-wider">{result?.tracking_id}</span>
            {result?.status ? <StatusBadge status={result.status} /> : null}
          </div>
          <SheetFooter className="sm:flex-row">
            <Button className="w-full sm:flex-1" onClick={() => result && navigate(`/c/${result.id}`)}>
              {t("new.trackIt")}
            </Button>
            <Button variant="outline" className="w-full sm:flex-1" onClick={reset}>
              <Plus />
              {t("new.fileAnother")}
            </Button>
          </SheetFooter>
        </SheetContent>
      </Sheet>
    </div>
  )
}
