import { useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import { Loader2, MessageSquareReply, Paperclip, Send, X } from "lucide-react"
import { toast } from "sonner"
import { api, ApiError } from "@/lib/api"
import type { Complaint } from "@/lib/types"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Textarea } from "@/components/ui/textarea"
import { MAX_PHOTO_MB, MAX_VIDEO_MB } from "@/components/CameraDialog"

const OPEN = new Set(["received", "analysing", "under_review", "routed", "in_progress", "awaiting_info"])
const MAX_REPLY_FILES = 4

/** Lets the complainant answer a request for information or add details and evidence. */
export function ReplyCard({ complaint, onSent }: { complaint: Complaint; onSent: () => void }) {
  const { t } = useTranslation()
  const [text, setText] = useState("")
  const [files, setFiles] = useState<File[]>([])
  const [busy, setBusy] = useState(false)
  const input = useRef<HTMLInputElement | null>(null)

  if (!OPEN.has(complaint.status)) return null
  const waiting = complaint.status === "awaiting_info"
  const request = waiting ? [...complaint.timeline].reverse().find((e) => e.to_status === "awaiting_info")?.note : null
  const requestText = request ? request.replace(/^request_info by [^:]+:\s*/i, "") : null

  const addFiles = (list: File[]) => {
    const ok = list.filter((f) => {
      if (!(f.type.startsWith("image/") || f.type.startsWith("video/"))) return false
      const max = f.type.startsWith("video/") ? MAX_VIDEO_MB : MAX_PHOTO_MB
      if (f.size > max * 1024 * 1024) {
        toast.error(t("new.tooLarge", { name: f.name, max }))
        return false
      }
      return true
    })
    setFiles((prev) => [...prev, ...ok].slice(0, MAX_REPLY_FILES))
  }

  const send = async () => {
    if (text.trim().length < 2 && files.length === 0) {
      toast.error(t("track.replyEmpty"))
      return
    }
    setBusy(true)
    try {
      const fd = new FormData()
      fd.append("text", text.trim())
      files.forEach((f) => fd.append("files", f, f.name))
      await api(`/complaints/${complaint.id}/reply`, { body: fd })
      toast.success(t("track.replySent"))
      setText("")
      setFiles([])
      onSent()
    } catch (err) {
      toast.error(err instanceof ApiError && err.message !== "network_error" ? err.message : t("errors.network"))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card className={waiting ? "border-amber-400/70" : undefined}>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <MessageSquareReply className="size-4" />
          {waiting ? t("track.awaitingTitle") : t("track.replyTitle")}
        </CardTitle>
        <CardDescription>{waiting ? t("track.awaitingHint") : t("track.replyHint")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {requestText ? (
          <Alert>
            <AlertTitle>{t("track.officeAsked")}</AlertTitle>
            <AlertDescription>{requestText}</AlertDescription>
          </Alert>
        ) : null}
        <Textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={t("track.replyPlaceholder")}
          rows={3}
          className="min-h-20 text-base"
        />
        {files.length > 0 ? (
          <ul className="flex flex-wrap gap-2 text-xs">
            {files.map((f, i) => (
              <li key={`${f.name}-${i}`} className="inline-flex items-center gap-1 rounded-md bg-muted px-2 py-1">
                <span className="max-w-40 truncate">{f.name}</span>
                <button
                  type="button"
                  aria-label={t("new.remove")}
                  className="text-muted-foreground hover:text-foreground"
                  onClick={() => setFiles((prev) => prev.filter((_, j) => j !== i))}
                >
                  <X className="size-3" />
                </button>
              </li>
            ))}
          </ul>
        ) : null}
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="outline" onClick={() => input.current?.click()} disabled={busy}>
            <Paperclip />
            {t("track.attach")}
          </Button>
          <input
            ref={input}
            type="file"
            accept="image/*,video/*"
            multiple
            className="sr-only"
            onChange={(e) => {
              addFiles(Array.from(e.target.files ?? []))
              e.target.value = ""
            }}
          />
          <Button type="button" className="ml-auto" onClick={() => void send()} disabled={busy}>
            {busy ? <Loader2 className="animate-spin" /> : <Send />}
            {t("track.send")}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
