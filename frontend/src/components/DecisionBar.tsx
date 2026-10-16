import { useState } from "react"
import { useTranslation } from "react-i18next"
import {
  Check,
  CheckCircle2,
  GitMerge,
  Loader2,
  MessageCircleQuestionMark,
  MoreHorizontal,
  RotateCcw,
  Shuffle,
  Wrench,
  XCircle,
} from "lucide-react"
import { toast } from "sonner"
import { api, ApiError } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import type { Complaint, DecisionAction, DecisionPayload, Urgency } from "@/lib/types"
import { useDepartments } from "@/lib/departments"
import { URGENCY_ORDER } from "@/lib/labels"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"

type DialogAction = Exclude<DecisionAction, "accept">

interface Props {
  complaint: Complaint
  onDecided: () => void
}

const ACTION_KEY: Record<DecisionAction, string> = {
  accept: "decision.accept",
  reassign: "decision.reassign",
  merge: "decision.merge",
  request_info: "decision.requestInfo",
  resolve: "decision.resolve",
  close: "decision.close",
  reopen: "decision.reopen",
}

const OPEN = new Set(["under_review", "routed", "in_progress", "awaiting_info"])

/** Which decisions the API accepts in each status (mirrors review.py), so the bar never offers a 409.
 *  Accept on a routed case is only the department admin's Start work: for a reviewer it is routed already. */
function allowedActions(status: string, startsWork: boolean): Set<DecisionAction> {
  const open = OPEN.has(status)
  const a = new Set<DecisionAction>()
  if (status === "under_review" || (status === "routed" && startsWork)) a.add("accept")
  if (open) {
    a.add("reassign")
    a.add("merge")
    a.add("resolve")
    if (status !== "awaiting_info") a.add("request_info")
  }
  if (status === "resolved") a.add("close")
  if (status === "resolved" || status === "closed") a.add("reopen")
  return a
}

export function DecisionBar({ complaint, onDecided }: Props) {
  const { t } = useTranslation()
  const { user } = useAuth()
  const { departments, name } = useDepartments()
  const [action, setAction] = useState<DialogAction | null>(null)
  const [busy, setBusy] = useState(false)
  const [department, setDepartment] = useState<string>(complaint.department?.id ?? "general")
  const [urgency, setUrgency] = useState<string>(complaint.urgency ?? complaint.analysis?.urgency ?? "medium")
  const [mergedInto, setMergedInto] = useState("")
  const [reason, setReason] = useState("")

  const submit = async (payload: DecisionPayload) => {
    setBusy(true)
    try {
      const res = await api<{ ok: boolean; status: string }>(
        `/review/${encodeURIComponent(complaint.id)}/decision`,
        { body: payload },
      )
      const status = res?.status ?? complaint.status
      toast.success(t("decision.done", { status: t(`status.${status}`, { defaultValue: status }) }))
      setAction(null)
      setReason("")
      setMergedInto("")
      onDecided()
    } catch (err) {
      toast.error(err instanceof ApiError && err.message !== "network_error" ? err.message : t("errors.network"))
    } finally {
      setBusy(false)
    }
  }

  const open = (a: DialogAction) => {
    setReason("")
    setAction(a)
  }

  const reasonOk = reason.trim().length > 0
  const mergeOk = action !== "merge" || mergedInto.trim().length > 0

  const onConfirm = () => {
    if (!action) return
    const payload: DecisionPayload = { action, reason: reason.trim() }
    if (action === "reassign") {
      payload.department = department
      payload.urgency = urgency as Urgency
    }
    if (action === "merge") payload.merged_into = mergedInto.trim()
    void submit(payload)
  }

  const deptItems = departments.map((d) => ({ value: d.id, label: name(d.id) }))
  const urgencyItems = URGENCY_ORDER.map((u) => ({ value: u, label: t(`urgency.${u}`) }))

  // A department admin's accept starts the work; a reviewer's accept confirms the routing.
  const startsWork = user?.role === "dept_admin"
  const can = allowedActions(complaint.status, startsWork)
  // The main button: accept while the case waits for one, then resolve, then close or reopen.
  const primary: DecisionAction | null = can.has("accept")
    ? "accept"
    : can.has("resolve")
      ? "resolve"
      : can.has("close")
        ? "close"
        : can.has("reopen")
          ? "reopen"
          : null
  const more = (["resolve", "close", "reopen"] as DecisionAction[]).filter((a) => can.has(a) && a !== primary)
  const PRIMARY_ICON = { accept: startsWork ? <Wrench /> : <Check />, resolve: <CheckCircle2 />, close: <XCircle />, reopen: <RotateCcw /> }
  const MORE_ICON = { resolve: <CheckCircle2 />, close: <XCircle />, reopen: <RotateCcw /> }

  return (
    <>
      <div className="sticky bottom-0 z-30 -mx-4 border-t bg-background/95 px-4 py-3 backdrop-blur supports-backdrop-filter:bg-background/80">
        {primary === null ? (
          <p className="text-center text-sm text-muted-foreground">{t("decision.none", { status: t(`status.${complaint.status}`) })}</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            <Button
              className="min-w-36 flex-1"
              onClick={() => (primary === "accept" ? void submit({ action: "accept", reason: "accept" }) : open(primary))}
              disabled={busy}
            >
              {busy ? <Loader2 className="animate-spin" /> : PRIMARY_ICON[primary as keyof typeof PRIMARY_ICON]}
              {primary === "accept" && startsWork ? t("decision.startWork") : t(ACTION_KEY[primary])}
            </Button>
            {can.has("reassign") ? (
              <Button variant="outline" className="min-w-36 flex-1" onClick={() => open("reassign")} disabled={busy}>
                <Shuffle />
                {t("decision.reassign")}
              </Button>
            ) : null}
            {can.has("merge") ? (
              <Button variant="outline" className="min-w-36 flex-1" onClick={() => open("merge")} disabled={busy}>
                <GitMerge />
                {t("decision.merge")}
              </Button>
            ) : null}
            {can.has("request_info") ? (
              <Button variant="outline" className="min-w-36 flex-1" onClick={() => open("request_info")} disabled={busy}>
                <MessageCircleQuestionMark />
                {t("decision.requestInfo")}
              </Button>
            ) : null}
            {more.length > 0 ? (
              <DropdownMenu>
                <DropdownMenuTrigger render={<Button variant="ghost" className="min-w-36 flex-1" disabled={busy} />}>
                  <MoreHorizontal />
                  {t("decision.more")}
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  {more.map((a) => (
                    <DropdownMenuItem key={a} onClick={() => open(a as DialogAction)}>
                      {MORE_ICON[a as keyof typeof MORE_ICON]}
                      {t(ACTION_KEY[a])}
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
            ) : null}
          </div>
        )}
      </div>

      <Dialog open={action !== null} onOpenChange={(o) => !o && setAction(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{action ? t(ACTION_KEY[action]) : ""}</DialogTitle>
            <DialogDescription>{t("decision.dialogHint", { id: complaint.tracking_id })}</DialogDescription>
          </DialogHeader>

          <div className="space-y-3">
            {action === "reassign" ? (
              <>
                <div className="space-y-1.5">
                  <Label>{t("decision.department")}</Label>
                  <Select value={department} onValueChange={(v) => v && setDepartment(v)} items={deptItems}>
                    <SelectTrigger className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {deptItems.map((d) => (
                        <SelectItem key={d.value} value={d.value}>
                          {d.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label>{t("decision.urgency")}</Label>
                  <Select value={urgency} onValueChange={(v) => v && setUrgency(v)} items={urgencyItems}>
                    <SelectTrigger className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {urgencyItems.map((u) => (
                        <SelectItem key={u.value} value={u.value}>
                          {u.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </>
            ) : null}

            {action === "merge" ? (
              <div className="space-y-1.5">
                <Label htmlFor="merge-into">{t("decision.mergeInto")}</Label>
                <Input
                  id="merge-into"
                  placeholder="SYN-XXXXXX"
                  className="font-mono"
                  value={mergedInto}
                  onChange={(e) => setMergedInto(e.target.value)}
                />
              </div>
            ) : null}

            <div className="space-y-1.5">
              <Label htmlFor="decision-reason">{t("decision.reason")}</Label>
              <Textarea
                id="decision-reason"
                required
                placeholder={t("decision.reasonPlaceholder")}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setAction(null)} disabled={busy}>
              {t("common.cancel")}
            </Button>
            <Button onClick={onConfirm} disabled={busy || !reasonOk || !mergeOk}>
              {busy ? <Loader2 className="animate-spin" /> : <Check />}
              {t("common.confirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
