import { useState } from "react"
import { useTranslation } from "react-i18next"
import { CheckCircle2, Loader2, RotateCcw, Star } from "lucide-react"
import { toast } from "sonner"
import { api, ApiError } from "@/lib/api"
import type { Complaint } from "@/lib/types"
import { formatDateTime } from "@/lib/format"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"

/** After a resolution: confirm with a rating, or say it is not fixed and reopen. */
export function FeedbackCard({ complaint, onSent }: { complaint: Complaint; onSent: () => void }) {
  const { t, i18n } = useTranslation()
  const [rating, setRating] = useState(0)
  const [hover, setHover] = useState(0)
  const [note, setNote] = useState("")
  const [reopening, setReopening] = useState(false)
  const [busy, setBusy] = useState(false)

  if (!["resolved", "closed"].includes(complaint.status)) return null
  const deadline = complaint.can_reopen_until ? new Date(complaint.can_reopen_until) : null
  const open = !!deadline && deadline.getTime() > Date.now()
  const rated = complaint.rating != null

  const send = async (reopen: boolean) => {
    if (!reopen && rating === 0) {
      toast.error(t("track.pickRating"))
      return
    }
    setBusy(true)
    try {
      await api(`/complaints/${complaint.id}/feedback`, {
        body: { rating: reopen ? undefined : rating, note: note.trim() || undefined, reopen },
      })
      toast.success(reopen ? t("track.reopened") : t("track.thanksRating"))
      setNote("")
      setReopening(false)
      onSent()
    } catch (err) {
      toast.error(err instanceof ApiError && err.message !== "network_error" ? err.message : t("errors.network"))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card className="border-emerald-400/60">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <CheckCircle2 className="size-4 text-emerald-600" />
          {rated ? t("track.ratedTitle") : t("track.feedbackTitle")}
        </CardTitle>
        <CardDescription>
          {rated
            ? t("track.ratedHint", { rating: complaint.rating })
            : open
              ? t("track.feedbackHint", { date: deadline ? formatDateTime(deadline.toISOString(), i18n.language) : "" })
              : t("track.feedbackClosed")}
        </CardDescription>
      </CardHeader>
      {open ? (
        <CardContent className="space-y-3">
          {!rated ? (
            <div className="flex items-center gap-1" role="radiogroup" aria-label={t("track.rating")}>
              {[1, 2, 3, 4, 5].map((n) => (
                <button
                  key={n}
                  type="button"
                  role="radio"
                  aria-checked={rating === n}
                  aria-label={`${n}`}
                  className="rounded-md p-1 outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
                  onMouseEnter={() => setHover(n)}
                  onMouseLeave={() => setHover(0)}
                  onClick={() => setRating(n)}
                >
                  <Star className={cn("size-7 text-amber-500", (hover || rating) >= n ? "fill-amber-400" : "fill-transparent")} />
                </button>
              ))}
              <span className="ml-2 text-sm text-muted-foreground">{rating ? t(`track.stars.${rating}`) : ""}</span>
            </div>
          ) : null}
          {reopening || !rated ? (
            <Textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder={reopening ? t("track.reopenPlaceholder") : t("track.notePlaceholder")}
              rows={2}
            />
          ) : null}
          <div className="flex flex-wrap gap-2">
            {!rated ? (
              <Button type="button" onClick={() => void send(false)} disabled={busy || rating === 0}>
                {busy ? <Loader2 className="animate-spin" /> : <CheckCircle2 />}
                {t("track.confirmFixed")}
              </Button>
            ) : null}
            {reopening ? (
              <>
                <Button type="button" variant="destructive" onClick={() => void send(true)} disabled={busy}>
                  {busy ? <Loader2 className="animate-spin" /> : <RotateCcw />}
                  {t("track.reopenNow")}
                </Button>
                <Button type="button" variant="ghost" onClick={() => setReopening(false)} disabled={busy}>
                  {t("common.cancel")}
                </Button>
              </>
            ) : (
              <Button type="button" variant="outline" onClick={() => setReopening(true)} disabled={busy}>
                <RotateCcw />
                {t("track.notFixed")}
              </Button>
            )}
          </div>
        </CardContent>
      ) : null}
    </Card>
  )
}
