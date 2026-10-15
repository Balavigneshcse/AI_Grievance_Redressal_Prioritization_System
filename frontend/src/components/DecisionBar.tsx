import { useState } from "react"
import { useTranslation } from "react-i18next"
import {
  Check,
  CheckCircle2,
  GitMerge,
  Loader2,
  MessageCircleQuestionMark,
  MoreHorizontal,
  Shuffle,
  XCircle,
} from "lucide-react"
import { toast } from "sonner"
import { api, ApiError } from "@/lib/api"
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
}

export function DecisionBar({ complaint, onDecided }: Props) {
  const { t } = useTranslation()
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

  return (
    <>
      <div className="sticky bottom-0 z-30 -mx-4 border-t bg-background/95 px-4 py-3 backdrop-blur supports-backdrop-filter:bg-background/80">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
          <Button onClick={() => void submit({ action: "accept", reason: "accept" })} disabled={busy}>
            {busy ? <Loader2 className="animate-spin" /> : <Check />}
            {t("decision.accept")}
          </Button>
          <Button variant="outline" onClick={() => open("reassign")} disabled={busy}>
            <Shuffle />
            {t("decision.reassign")}
          </Button>
          <Button variant="outline" onClick={() => open("merge")} disabled={busy}>
            <GitMerge />
            {t("decision.merge")}
          </Button>
          <Button variant="outline" onClick={() => open("request_info")} disabled={busy}>
            <MessageCircleQuestionMark />
            {t("decision.requestInfo")}
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger
              render={<Button variant="ghost" className="col-span-2 sm:col-span-1" disabled={busy} />}
            >
              <MoreHorizontal />
              {t("decision.more")}
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={() => open("resolve")}>
                <CheckCircle2 />
                {t("decision.resolve")}
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => open("close")}>
                <XCircle />
                {t("decision.close")}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
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
