import { useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import { ImagePlus, Loader2 } from "lucide-react"
import { toast } from "sonner"
import { api } from "@/lib/api"
import { errorText } from "@/lib/errors"
import type { Complaint } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { MAX_PHOTO_MB, MAX_VIDEO_MB } from "@/components/CameraDialog"

const ALLOWED = new Set(["under_review", "routed", "in_progress", "awaiting_info", "resolved"])

/** The office attaches proof of the completed work; the citizen sees it on the tracking page. */
export function ResolutionUpload({ complaint, onDone }: { complaint: Complaint; onDone: () => void }) {
  const { t } = useTranslation()
  const input = useRef<HTMLInputElement | null>(null)
  const [busy, setBusy] = useState(false)
  if (!ALLOWED.has(complaint.status)) return null
  const proofs = complaint.media.filter((m) => m.role === "resolution").length

  const upload = async (files: File[]) => {
    const ok = files.filter((f) => {
      const max = f.type.startsWith("video/") ? MAX_VIDEO_MB : MAX_PHOTO_MB
      if (f.size > max * 1024 * 1024) {
        toast.error(t("new.tooLarge", { name: f.name, max }))
        return false
      }
      return f.type.startsWith("image/") || f.type.startsWith("video/")
    })
    if (ok.length === 0) return
    setBusy(true)
    try {
      const fd = new FormData()
      ok.forEach((f) => fd.append("files", f, f.name))
      await api(`/review/${complaint.id}/attachments`, { body: fd })
      toast.success(t("officer.proofAdded", { count: ok.length }))
      onDone()
    } catch (err) {
      toast.error(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card size="sm">
      <CardContent className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-medium">{t("officer.proofTitle")}</p>
          <p className="text-xs text-muted-foreground">
            {proofs > 0 ? t("officer.proofCount", { count: proofs }) : t("officer.proofHint")}
          </p>
        </div>
        <Button type="button" variant="outline" onClick={() => input.current?.click()} disabled={busy}>
          {busy ? <Loader2 className="animate-spin" /> : <ImagePlus />}
          {t("officer.addProof")}
        </Button>
        <input
          ref={input}
          type="file"
          accept="image/*,video/*"
          multiple
          className="sr-only"
          onChange={(e) => {
            void upload(Array.from(e.target.files ?? []))
            e.target.value = ""
          }}
        />
      </CardContent>
    </Card>
  )
}
