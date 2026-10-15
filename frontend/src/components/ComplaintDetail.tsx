import { Fragment, type ReactNode } from "react"
import { Link } from "react-router-dom"
import { useTranslation } from "react-i18next"
import { AlarmClock, Building2, Check, Copy, Image as ImageIcon, Loader2, MapPin, Sparkles, X } from "lucide-react"
import { toast } from "sonner"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion"
import { Separator } from "@/components/ui/separator"
import { StatusBadge, UrgencyBadge } from "@/components/Badges"
import { Timeline } from "@/components/Timeline"
import { MediaThumb } from "@/components/MediaThumb"
import { useDepartments } from "@/lib/departments"
import { formatDateTime } from "@/lib/format"
import { isLiveStatus, LANGUAGE_NAMES } from "@/lib/labels"
import type { Complaint } from "@/lib/types"

const DASH = "—"

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
}

/** Wrap every evidence span found in the text with <mark>. */
export function highlight(text: string, spans: string[]): ReactNode {
  const clean = spans.map((s) => s.trim()).filter((s) => s.length > 0)
  if (clean.length === 0) return text
  const pattern = clean
    .sort((a, b) => b.length - a.length)
    .map(escapeRegExp)
    .join("|")
  const re = new RegExp(pattern, "gi")
  const out: ReactNode[] = []
  let last = 0
  let i = 0
  for (const m of text.matchAll(re)) {
    const start = m.index ?? 0
    if (start > last) out.push(<Fragment key={i++}>{text.slice(last, start)}</Fragment>)
    out.push(<mark key={i++}>{m[0]}</mark>)
    last = start + m[0].length
  }
  if (last < text.length) out.push(<Fragment key={i++}>{text.slice(last)}</Fragment>)
  return out
}

interface Props {
  complaint: Complaint
  /** Link base for duplicate candidates (officer vs citizen view). */
  linkBase?: string
  children?: ReactNode
}

export function ComplaintDetail({ complaint, linkBase = "/c", children }: Props) {
  const { t, i18n } = useTranslation()
  const { name } = useDepartments()
  const a = complaint.analysis
  const live = isLiveStatus(complaint.status)
  const dept = name(complaint.department ?? a?.department ?? null)
  const placeText = complaint.resolved_place || complaint.manual_address
  const hasCoords = complaint.lat != null && complaint.lng != null

  const copyId = async () => {
    try {
      await navigator.clipboard.writeText(complaint.tracking_id)
      toast.success(t("track.copied"))
    } catch {
      toast.error(t("errors.generic"))
    }
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-lg tracking-wide">{complaint.tracking_id}</span>
            <Button variant="ghost" size="icon-xs" aria-label={t("track.copy")} onClick={() => void copyId()}>
              <Copy />
            </Button>
          </CardTitle>
          <div className="flex flex-wrap items-center gap-1.5">
            <StatusBadge status={complaint.status} />
            <UrgencyBadge urgency={complaint.urgency ?? a?.urgency} />
            {dept ? (
              <Badge variant="outline">
                <Building2 />
                {dept}
              </Badge>
            ) : null}
            {a?.language_primary ? (
              <Badge variant="secondary">{LANGUAGE_NAMES[a.language_primary] ?? a.language_primary}</Badge>
            ) : null}
          </div>
          <p className="text-xs text-muted-foreground">
            {t("track.filedOn", { date: formatDateTime(complaint.created_at, i18n.language) })}
          </p>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm leading-relaxed whitespace-pre-wrap">{complaint.raw_text}</p>
          {complaint.complainant_name ? (
            <p className="text-xs text-muted-foreground">
              {t("track.complainant")}: <span className="font-medium text-foreground">{complaint.complainant_name}</span>
              {complaint.aadhaar_last4 ? (
                <>
                  {" · "}
                  {t("track.aadhaar")}: <span className="font-mono text-foreground">XXXX XXXX {complaint.aadhaar_last4}</span>
                </>
              ) : null}
            </p>
          ) : null}
          {a?.summary_en ? (
            <>
              <Separator />
              <p className="text-sm text-muted-foreground">
                <span className="font-medium text-foreground">{t("track.summary")}: </span>
                {a.summary_en}
              </p>
            </>
          ) : null}
          {complaint.escalated_at && !["resolved", "closed", "merged"].includes(complaint.status) ? (
            <Alert variant="destructive">
              <AlarmClock />
              <AlertTitle>{t("track.escalatedTitle")}</AlertTitle>
              <AlertDescription>{t("track.escalatedHint", { date: formatDateTime(complaint.escalated_at, i18n.language) })}</AlertDescription>
            </Alert>
          ) : null}
          {live ? (
            <Alert>
              <Loader2 className="animate-spin" />
              <AlertTitle>{t("track.analysingTitle")}</AlertTitle>
              <AlertDescription>{t("track.analysingHint")}</AlertDescription>
            </Alert>
          ) : null}
        </CardContent>
      </Card>

      {children}

      <Card>
        <CardHeader>
          <CardTitle>{t("track.timeline")}</CardTitle>
        </CardHeader>
        <CardContent>
          <Timeline entries={complaint.timeline ?? []} currentStatus={complaint.status} />
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <Accordion>
            <AccordionItem value="why" className="border-b-0">
              <AccordionTrigger>
                <span className="flex items-center gap-2">
                  <Sparkles className="size-4 text-muted-foreground" />
                  {t("track.why")}
                </span>
              </AccordionTrigger>
              <AccordionContent className="space-y-3">
                {a ? (
                  <>
                    <p className="rounded-lg bg-muted/60 p-3 text-sm leading-relaxed whitespace-pre-wrap">
                      {highlight(complaint.raw_text, a.evidence_spans ?? [])}
                    </p>
                    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-sm">
                      <dt className="text-muted-foreground">{t("track.department")}</dt>
                      <dd>{name(a.department, DASH)}</dd>
                      <dt className="text-muted-foreground">{t("track.urgency")}</dt>
                      <dd>{a.urgency ? <UrgencyBadge urgency={a.urgency} /> : DASH}</dd>
                      <dt className="text-muted-foreground">{t("track.confidence")}</dt>
                      <dd>{typeof a.confidence === "number" ? `${Math.round(a.confidence * 100)}%` : DASH}</dd>
                      <dt className="text-muted-foreground">{t("track.language")}</dt>
                      <dd>
                        {[a.language_primary, a.language_secondary]
                          .filter((l): l is string => !!l)
                          .map((l) => LANGUAGE_NAMES[l] ?? l)
                          .join(" + ") || DASH}
                      </dd>
                      {a.matched_rule_ids?.length ? (
                        <>
                          <dt className="text-muted-foreground">{t("track.rules")}</dt>
                          <dd className="flex flex-wrap gap-1">
                            {a.matched_rule_ids.map((r) => (
                              <Badge key={r} variant="outline" className="font-mono text-[11px]">
                                {r}
                              </Badge>
                            ))}
                          </dd>
                        </>
                      ) : null}
                    </dl>

                    <div className="flex items-start gap-2 text-sm">
                      <ImageIcon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                      <span>
                        {a.image_findings ? a.image_findings : t("track.noImageFindings")}
                        {typeof a.image_matches_text === "boolean" ? (
                          <span className="ml-1.5 inline-flex items-center gap-0.5 text-xs text-muted-foreground">
                            {a.image_matches_text ? (
                              <Check className="size-3.5 text-emerald-600" />
                            ) : (
                              <X className="size-3.5 text-red-600" />
                            )}
                            {a.image_matches_text ? t("track.imageMatches") : t("track.imageMismatch")}
                          </span>
                        ) : null}
                      </span>
                    </div>

                    {complaint.decision?.reasons?.length ? (
                      <div className="text-sm">
                        <p className="mb-1 font-medium">
                          {t("track.decision")}
                          <Badge variant="secondary" className="ml-1.5">
                            {complaint.decision.queue}
                          </Badge>
                        </p>
                        <ul className="list-disc space-y-0.5 pl-5 text-muted-foreground">
                          {complaint.decision.reasons.map((r, i) => (
                            <li key={i}>{r}</li>
                          ))}
                        </ul>
                      </div>
                    ) : null}

                    {a.duplicate_candidates?.length ? (
                      <div className="text-sm">
                        <p className="mb-1 font-medium">{t("track.duplicates")}</p>
                        <ul className="space-y-0.5">
                          {a.duplicate_candidates.map((d) => (
                            <li key={d.complaint_id} className="flex items-center gap-2">
                              <Link
                                to={`${linkBase}/${d.complaint_id}`}
                                className="font-mono underline underline-offset-2"
                              >
                                {d.tracking_id}
                              </Link>
                              <span className="text-xs text-muted-foreground">{Math.round(d.score * 100)}%</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    ) : null}
                  </>
                ) : (
                  <p className="text-sm text-muted-foreground">{t("track.noAnalysis")}</p>
                )}
              </AccordionContent>
            </AccordionItem>
          </Accordion>
        </CardContent>
      </Card>

      {complaint.media?.length ? (
        <Card>
          <CardHeader>
            <CardTitle>{t("track.media")}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-3 gap-2">
              {complaint.media.map((m) => (
                <MediaThumb key={m.id} media={m} />
              ))}
            </div>
          </CardContent>
        </Card>
      ) : null}

      {placeText || hasCoords ? (
        <Alert>
          <MapPin />
          <AlertTitle>{placeText || t("location.title")}</AlertTitle>
          <AlertDescription>
            {hasCoords
              ? t("location.coords", {
                  lat: (complaint.lat as number).toFixed(5),
                  lng: (complaint.lng as number).toFixed(5),
                })
              : null}
            {complaint.location_source ? ` · ${t(`locationSource.${complaint.location_source}`)}` : null}
          </AlertDescription>
        </Alert>
      ) : null}
    </div>
  )
}
