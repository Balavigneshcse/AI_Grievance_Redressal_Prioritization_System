import { useCallback, useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { useTranslation } from "react-i18next"
import { ArrowLeft, FlaskConical, Loader2, RefreshCw, Save, ShieldCheck } from "lucide-react"
import { toast } from "sonner"
import { api } from "@/lib/api"
import { errorText } from "@/lib/errors"
import { useAuth } from "@/lib/auth"
import { useDepartments } from "@/lib/departments"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"

interface Rule {
  id: string
  name?: string
  enabled?: boolean
  match?: { keywords?: string[] }
  action?: { department?: string | null; urgency_floor?: string | null; force_review?: boolean }
}

interface RulesOut {
  yaml: string
  rules: Rule[]
}

interface TestOut {
  matched: string[]
  department: string | null
  urgency_floor: string | null
  force_review: boolean
  notes: string[]
}

export default function AdminRules() {
  const { t } = useTranslation()
  const { user } = useAuth()
  const { name } = useDepartments()
  const superAdmin = user?.role === "super_admin"
  const [data, setData] = useState<RulesOut | null>(null)
  const [yaml, setYaml] = useState("")
  const [note, setNote] = useState("")
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [reloading, setReloading] = useState(false)
  const [sample, setSample] = useState("")
  const [testing, setTesting] = useState(false)
  const [result, setResult] = useState<TestOut | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const r = await api<RulesOut>("/admin/rules")
      setData(r)
      setYaml(r.yaml)
    } catch (err) {
      toast.error(errorText(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const save = async () => {
    setSaving(true)
    try {
      await api("/admin/rules", { method: "PUT", body: { yaml, note: note || undefined } })
      toast.success(t("admin.saved"))
      setNote("")
      void load()
    } catch (err) {
      toast.error(errorText(err))
    } finally {
      setSaving(false)
    }
  }

  const runTest = async () => {
    if (!sample.trim()) return
    setTesting(true)
    try {
      setResult(await api<TestOut>("/admin/rules/test", { body: { text: sample } }))
    } catch (err) {
      toast.error(errorText(err))
    } finally {
      setTesting(false)
    }
  }

  const reloadModels = async () => {
    setReloading(true)
    try {
      await api("/admin/models/reload", { method: "POST" })
      toast.success(t("admin.reloaded"))
    } catch (err) {
      toast.error(errorText(err))
    } finally {
      setReloading(false)
    }
  }

  const dirty = data !== null && yaml !== data.yaml

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="icon" nativeButton={false} render={<Link to="/admin" aria-label={t("common.back")} />}>
          <ArrowLeft />
        </Button>
        <div className="min-w-0">
          <h1 className="font-heading text-xl font-semibold">{t("admin.rulesTitle")}</h1>
          <p className="text-xs text-muted-foreground">{t("admin.rulesHint")}</p>
        </div>
        <Button variant="ghost" size="icon" className="ml-auto" aria-label={t("common.refresh")} onClick={() => void load()} disabled={loading}>
          <RefreshCw className={loading ? "animate-spin" : undefined} />
        </Button>
      </div>

      {!superAdmin ? (
        <Alert>
          <ShieldCheck />
          <AlertDescription>{t("admin.readOnly")}</AlertDescription>
        </Alert>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FlaskConical className="size-4" />
            {t("admin.tester")}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Textarea value={sample} onChange={(e) => setSample(e.target.value)} placeholder={t("admin.testPlaceholder")} rows={3} />
          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" onClick={() => void runTest()} disabled={testing || !sample.trim()}>
              {testing ? <Loader2 className="animate-spin" /> : <FlaskConical />}
              {t("admin.test")}
            </Button>
            {result ? (
              result.matched.length === 0 ? (
                <span className="text-sm text-muted-foreground">{t("admin.noMatch")}</span>
              ) : (
                <div className="flex flex-wrap items-center gap-1.5 text-sm">
                  <span className="text-muted-foreground">{t("admin.matched")}:</span>
                  {result.matched.map((id) => (
                    <Badge key={id}>{id}</Badge>
                  ))}
                  {result.department ? <Badge variant="outline">{name(result.department, result.department)}</Badge> : null}
                  {result.urgency_floor ? (
                    <Badge variant="outline">
                      {t("admin.urgencyFloor")}: {t(`urgency.${result.urgency_floor}`)}
                    </Badge>
                  ) : null}
                  {result.force_review ? <Badge variant="destructive">{t("admin.forceReview")}</Badge> : null}
                </div>
              )
            ) : null}
          </div>
        </CardContent>
      </Card>

      <Card className="py-0">
        <CardHeader className="pt-4">
          <CardTitle>{t("admin.rulesList")}</CardTitle>
        </CardHeader>
        {loading && !data ? (
          <CardContent>
            <Skeleton className="h-32 w-full" />
          </CardContent>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>ID</TableHead>
                <TableHead>{t("admin.name")}</TableHead>
                <TableHead>{t("admin.department")}</TableHead>
                <TableHead>{t("admin.urgencyFloor")}</TableHead>
                <TableHead>{t("admin.forceReview")}</TableHead>
                <TableHead className="text-right">{t("admin.enabled")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(data?.rules ?? []).map((r) => (
                <TableRow key={r.id}>
                  <TableCell className="font-mono font-medium">{r.id}</TableCell>
                  <TableCell>
                    <span className="block">{r.name ?? ""}</span>
                    <span className="block max-w-80 truncate text-xs text-muted-foreground">{(r.match?.keywords ?? []).slice(0, 6).join(", ")}</span>
                  </TableCell>
                  <TableCell>{r.action?.department ? name(r.action.department, r.action.department) : "—"}</TableCell>
                  <TableCell>{r.action?.urgency_floor ? t(`urgency.${r.action.urgency_floor}`) : "—"}</TableCell>
                  <TableCell>{r.action?.force_review ? t("common.confirm") : "—"}</TableCell>
                  <TableCell className="text-right">
                    <Badge variant={r.enabled === false ? "secondary" : "default"}>
                      {r.enabled === false ? t("admin.disabled") : t("admin.enabled")}
                    </Badge>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>YAML</CardTitle>
          <CardDescription>config/rules.yaml</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {loading && !data ? (
            <Skeleton className="h-64 w-full" />
          ) : (
            <Textarea
              value={yaml}
              onChange={(e) => setYaml(e.target.value)}
              readOnly={!superAdmin}
              spellCheck={false}
              className="min-h-96 font-mono text-xs leading-relaxed"
            />
          )}
          {superAdmin ? (
            <div className="flex flex-wrap items-center gap-2">
              <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder={t("admin.saveNote")} className="max-w-sm" />
              <Button type="button" onClick={() => void save()} disabled={saving || !dirty}>
                {saving ? <Loader2 className="animate-spin" /> : <Save />}
                {t("admin.save")}
              </Button>
              <Button type="button" variant="outline" className="ml-auto" onClick={() => void reloadModels()} disabled={reloading}>
                {reloading ? <Loader2 className="animate-spin" /> : <RefreshCw />}
                {t("admin.reloadModels")}
              </Button>
            </div>
          ) : null}
        </CardContent>
      </Card>
    </div>
  )
}
