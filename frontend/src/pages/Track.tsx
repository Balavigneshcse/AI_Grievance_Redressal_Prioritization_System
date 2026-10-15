import { useEffect } from "react"
import { Link, useParams } from "react-router-dom"
import { useTranslation } from "react-i18next"
import { ArrowLeft, RefreshCw } from "lucide-react"
import { toast } from "sonner"
import { useComplaint } from "@/lib/useComplaint"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { ComplaintDetail } from "@/components/ComplaintDetail"
import { ReplyCard } from "@/components/ReplyCard"
import { FeedbackCard } from "@/components/FeedbackCard"

export default function Track() {
  const { id } = useParams<{ id: string }>()
  const { t } = useTranslation()
  const { complaint, loading, error, reload } = useComplaint(id)

  useEffect(() => {
    if (error) toast.error(error === "network_error" ? t("errors.network") : error)
  }, [error, t])

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="icon" nativeButton={false} render={<Link to="/" aria-label={t("common.back")} />}>
          <ArrowLeft />
        </Button>
        <h1 className="font-heading text-xl font-semibold">{t("track.title")}</h1>
        <Button variant="ghost" size="icon" className="ml-auto" aria-label={t("common.refresh")} onClick={() => void reload()}>
          <RefreshCw className={loading ? "animate-spin" : undefined} />
        </Button>
      </div>

      {loading && !complaint ? (
        <div className="space-y-3">
          <Skeleton className="h-36 w-full rounded-xl" />
          <Skeleton className="h-48 w-full rounded-xl" />
        </div>
      ) : complaint ? (
        <ComplaintDetail complaint={complaint}>
          <FeedbackCard complaint={complaint} onSent={() => void reload()} />
          <ReplyCard complaint={complaint} onSent={() => void reload()} />
        </ComplaintDetail>
      ) : (
        <Alert variant="destructive">
          <AlertTitle>{t("track.notFound")}</AlertTitle>
          <AlertDescription>{error === "network_error" ? t("errors.network") : error}</AlertDescription>
        </Alert>
      )}
    </div>
  )
}
