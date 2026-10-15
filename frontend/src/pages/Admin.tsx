import { useCallback, useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { useTranslation } from "react-i18next"
import { BarChart3, Building2, Copy, FileCog, KeyRound, Loader2, MailPlus, MapPinned, RefreshCw, UserPlus, Users } from "lucide-react"
import { toast } from "sonner"
import { api, ApiError } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { useDepartments } from "@/lib/departments"
import { formatDateTime } from "@/lib/format"
import type { DistrictInfo, StaffCreated, StaffUser } from "@/lib/types"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

const ALL = "all"
const LANGS = ["en", "ta", "hi"]
const DASH = "—"

type StaffRole = "district_admin" | "dept_admin"

interface Overview {
  generated_at: string
  districts: Record<string, { total: number; open: number; by_department: Record<string, number> }>
}

interface Option {
  value: string
  label: string
}

function PickSelect({
  value,
  onChange,
  items,
  label,
  disabled,
}: {
  value: string
  onChange: (v: string) => void
  items: Option[]
  label: string
  disabled?: boolean
}) {
  return (
    <Select value={value} onValueChange={(v) => onChange(v ?? "")} items={items} disabled={disabled}>
      <SelectTrigger className="w-full" aria-label={label}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {items.map((o) => (
          <SelectItem key={o.value} value={o.value}>
            {o.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

export default function Admin() {
  const { t, i18n } = useTranslation()
  const { user } = useAuth()
  const navigate = useNavigate()
  const { departments, name } = useDepartments()
  const superAdmin = user?.role === "super_admin"
  const [districts, setDistricts] = useState<DistrictInfo[]>([])
  const [staff, setStaff] = useState<StaffUser[] | null>(null)
  const [overview, setOverview] = useState<Overview | null>(null)
  const [districtFilter, setDistrictFilter] = useState(ALL)
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState(false)
  const [created, setCreated] = useState<StaffCreated | null>(null)
  const [busy, setBusy] = useState(false)
  const [emailTarget, setEmailTarget] = useState<StaffUser | null>(null)
  const [newEmail, setNewEmail] = useState("")
  const [emailBusy, setEmailBusy] = useState(false)

  const [role, setRole] = useState<StaffRole>(superAdmin ? "district_admin" : "dept_admin")
  const [district, setDistrict] = useState(user?.district ?? "")
  const [departmentId, setDepartmentId] = useState("")
  const [fullName, setFullName] = useState("")
  const [email, setEmail] = useState("")
  const [mobile, setMobile] = useState("")
  const [lang, setLang] = useState("en")
  const [password, setPassword] = useState("")

  const load = useCallback(async () => {
    setLoading(true)
    const qs = superAdmin && districtFilter !== ALL ? `?district=${encodeURIComponent(districtFilter)}` : ""
    try {
      const [rows, ov] = await Promise.all([api<StaffUser[]>(`/admin/users${qs}`), api<Overview>("/admin/overview")])
      setStaff(rows)
      setOverview(ov)
    } catch (err) {
      setStaff((prev) => prev ?? [])
      toast.error(err instanceof ApiError && err.message !== "network_error" ? err.message : t("errors.network"))
    } finally {
      setLoading(false)
    }
  }, [superAdmin, districtFilter, t])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    api<DistrictInfo[]>("/admin/districts")
      .then(setDistricts)
      .catch(() => setDistricts([]))
  }, [])

  const resetForm = () => {
    setRole(superAdmin ? "district_admin" : "dept_admin")
    setDistrict(user?.district ?? "")
    setDepartmentId("")
    setFullName("")
    setEmail("")
    setMobile("")
    setLang("en")
    setPassword("")
  }

  const submit = async () => {
    setBusy(true)
    try {
      const res = await api<StaffCreated>("/admin/users", {
        body: {
          role,
          district: superAdmin ? district || undefined : undefined,
          department_id: role === "dept_admin" ? departmentId || undefined : undefined,
          full_name: fullName,
          email,
          mobile,
          preferred_language: lang,
          password: password || undefined,
        },
      })
      setCreated(res)
      setOpen(false)
      resetForm()
      toast.success(t("admin.created"))
      void load()
    } catch (err) {
      toast.error(err instanceof ApiError && err.message !== "network_error" ? err.message : t("errors.network"))
    } finally {
      setBusy(false)
    }
  }

  const toggleActive = async (u: StaffUser, active: boolean) => {
    try {
      const updated = await api<StaffUser>(`/admin/users/${u.id}`, { method: "PATCH", body: { is_active: active } })
      setStaff((prev) => (prev ?? []).map((s) => (s.id === u.id ? updated : s)))
      toast.success(active ? t("admin.activated") : t("admin.deactivated"))
    } catch (err) {
      toast.error(err instanceof ApiError && err.message !== "network_error" ? err.message : t("errors.network"))
    }
  }

  const saveEmail = async () => {
    if (!emailTarget) return
    setEmailBusy(true)
    try {
      const updated = await api<StaffUser>(`/admin/users/${emailTarget.id}`, { method: "PATCH", body: { email: newEmail.trim() } })
      setStaff((prev) => (prev ?? []).map((s) => (s.id === updated.id ? updated : s)))
      toast.success(t("admin.emailUpdated"))
      setEmailTarget(null)
    } catch (err) {
      toast.error(err instanceof ApiError && err.message !== "network_error" ? err.message : t("errors.network"))
    } finally {
      setEmailBusy(false)
    }
  }

  const copyPassword = async () => {
    if (!created) return
    try {
      await navigator.clipboard.writeText(created.password)
      toast.success(t("admin.copied"))
    } catch {
      toast.error(t("errors.generic"))
    }
  }

  const districtItems: Option[] = districts.map((d) => ({ value: d.name, label: d.name }))
  const filterItems: Option[] = [{ value: ALL, label: t("admin.allDistricts") }, ...districtItems]
  const deptItems: Option[] = departments.map((d) => ({ value: d.id, label: name(d.id) }))
  const roleItems: Option[] = [
    { value: "district_admin", label: t("role.district_admin") },
    { value: "dept_admin", label: t("role.dept_admin") },
  ]
  const langItems: Option[] = LANGS.map((l) => ({ value: l, label: l.toUpperCase() }))
  const overviewRows = Object.entries(overview?.districts ?? {}).sort((a, b) => b[1].open - a[1].open)
  const canSubmit =
    fullName.trim().length >= 2 &&
    email.trim().length > 3 &&
    mobile.trim().length >= 10 &&
    (!superAdmin || district) &&
    (role !== "dept_admin" || departmentId)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <h1 className="font-heading text-xl font-semibold">{t("admin.title")}</h1>
          <p className="text-xs text-muted-foreground">
            {superAdmin ? t("admin.subtitle") : t("admin.districtAdminHint", { district: user?.district ?? DASH })}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1">
          <Button variant="outline" size="sm" onClick={() => navigate("/admin/metrics")}>
            <BarChart3 />
            {t("admin.metrics")}
          </Button>
          <Button variant="outline" size="sm" onClick={() => navigate("/admin/rules")}>
            <FileCog />
            {t("admin.rules")}
          </Button>
          <Button variant="ghost" size="icon" aria-label={t("common.refresh")} onClick={() => void load()} disabled={loading}>
            <RefreshCw className={loading ? "animate-spin" : undefined} />
          </Button>
          <Button
            onClick={() => {
              resetForm()
              setOpen(true)
            }}
          >
            <UserPlus />
            {t("admin.add")}
          </Button>
        </div>
      </div>

      {created ? (
        <Alert>
          <KeyRound />
          <AlertTitle>{t("admin.created")}</AlertTitle>
          <AlertDescription className="space-y-2">
            <p>{t("admin.passwordOnce", { name: created.user.full_name ?? created.user.email })}</p>
            <div className="flex flex-wrap items-center gap-2">
              <code className="rounded-md bg-muted px-2 py-1 font-mono text-sm">{created.password}</code>
              <Button size="sm" variant="outline" onClick={() => void copyPassword()}>
                <Copy />
                {t("admin.copy")}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setCreated(null)}>
                {t("common.confirm")}
              </Button>
            </div>
          </AlertDescription>
        </Alert>
      ) : null}

      <Card size="sm">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <MapPinned className="size-4" />
            {t("admin.overview")}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {overview === null ? (
            <Skeleton className="h-16 w-full" />
          ) : overviewRows.length === 0 ? (
            <p className="text-sm text-muted-foreground">{DASH}</p>
          ) : (
            <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {overviewRows.map(([d, v]) => (
                <li key={d} className="rounded-lg border p-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate font-medium">{d}</span>
                    <Badge variant={v.open > 0 ? "default" : "secondary"}>
                      {v.open} {t("admin.open")}
                    </Badge>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {v.total} {t("admin.total")} ·{" "}
                    {Object.entries(v.by_department)
                      .sort((a, b) => b[1] - a[1])
                      .slice(0, 3)
                      .map(([dept, n]) => `${name(dept, dept)} ${n}`)
                      .join(", ")}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card className="py-0">
        <CardHeader className="pt-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle className="flex items-center gap-2">
              <Users className="size-4" />
              {t("admin.staff")}
            </CardTitle>
            {superAdmin ? (
              <div className="w-56">
                <PickSelect value={districtFilter} onChange={setDistrictFilter} items={filterItems} label={t("admin.district")} />
              </div>
            ) : null}
          </div>
        </CardHeader>
        {loading && !staff ? (
          <CardContent>
            <Skeleton className="h-32 w-full" />
          </CardContent>
        ) : staff && staff.length === 0 ? (
          <CardContent>
            <p className="py-4 text-center text-sm text-muted-foreground">{t("admin.noStaff")}</p>
          </CardContent>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("admin.name")}</TableHead>
                <TableHead>{t("admin.role")}</TableHead>
                <TableHead>{t("admin.district")}</TableHead>
                <TableHead>{t("admin.department")}</TableHead>
                <TableHead>{t("admin.lastLogin")}</TableHead>
                <TableHead className="text-right">{t("admin.active")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(staff ?? []).map((u) => (
                <TableRow key={u.id}>
                  <TableCell>
                    <span className="block font-medium">{u.full_name ?? DASH}</span>
                    <span className="flex items-center gap-1 text-xs text-muted-foreground">
                      <span className="truncate">{u.email}</span>
                      {u.role !== "super_admin" || u.id === user?.id ? (
                        <Button
                          variant="ghost"
                          size="icon-xs"
                          aria-label={t("admin.editEmail")}
                          onClick={() => {
                            setEmailTarget(u)
                            setNewEmail(u.email)
                          }}
                        >
                          <MailPlus />
                        </Button>
                      ) : null}
                    </span>
                  </TableCell>
                  <TableCell>
                    <Badge variant={u.role === "super_admin" ? "default" : "secondary"}>{t(`role.${u.role}`)}</Badge>
                  </TableCell>
                  <TableCell>{u.district ?? DASH}</TableCell>
                  <TableCell>
                    {u.department_id ? (
                      <span className="inline-flex items-center gap-1">
                        <Building2 className="size-3.5 text-muted-foreground" />
                        {name(u.department_id, u.department_id)}
                      </span>
                    ) : (
                      DASH
                    )}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {u.last_login_at ? formatDateTime(u.last_login_at, i18n.language) : t("admin.never")}
                  </TableCell>
                  <TableCell className="text-right">
                    <Switch
                      checked={u.is_active !== false}
                      disabled={u.id === user?.id || u.role === "super_admin"}
                      aria-label={t("admin.active")}
                      onCheckedChange={(checked) => void toggleActive(u, checked)}
                    />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Card>

      <Dialog open={emailTarget !== null} onOpenChange={(o) => !o && setEmailTarget(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{t("admin.editEmail")}</DialogTitle>
            <DialogDescription>{t("admin.editEmailHint", { name: emailTarget?.full_name ?? emailTarget?.email ?? "" })}</DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5">
            <Label htmlFor="staff-new-email">{t("admin.newEmail")}</Label>
            <Input id="staff-new-email" type="email" value={newEmail} onChange={(e) => setNewEmail(e.target.value)} autoFocus />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setEmailTarget(null)} disabled={emailBusy}>
              {t("common.cancel")}
            </Button>
            <Button type="button" onClick={() => void saveEmail()} disabled={emailBusy || !newEmail.includes("@")}>
              {emailBusy ? <Loader2 className="animate-spin" /> : <MailPlus />}
              {t("common.confirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{t("admin.createTitle")}</DialogTitle>
            <DialogDescription>{t("admin.createHint")}</DialogDescription>
          </DialogHeader>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label>{t("admin.role")}</Label>
              <PickSelect
                value={role}
                onChange={(v) => setRole((v || "dept_admin") as StaffRole)}
                items={superAdmin ? roleItems : roleItems.slice(1)}
                label={t("admin.role")}
                disabled={!superAdmin}
              />
            </div>
            <div className="space-y-1.5">
              <Label>{t("admin.district")}</Label>
              {superAdmin ? (
                <PickSelect value={district} onChange={setDistrict} items={districtItems} label={t("admin.district")} />
              ) : (
                <Input value={user?.district ?? ""} disabled />
              )}
            </div>
            {role === "dept_admin" ? (
              <div className="space-y-1.5 sm:col-span-2">
                <Label>{t("admin.department")}</Label>
                <PickSelect value={departmentId} onChange={setDepartmentId} items={deptItems} label={t("admin.department")} />
              </div>
            ) : null}
            <div className="space-y-1.5 sm:col-span-2">
              <Label htmlFor="staff-name">{t("admin.fullName")}</Label>
              <Input id="staff-name" value={fullName} onChange={(e) => setFullName(e.target.value)} maxLength={120} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="staff-email">{t("admin.email")}</Label>
              <Input id="staff-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="staff-mobile">{t("admin.mobile")}</Label>
              <Input id="staff-mobile" inputMode="numeric" value={mobile} onChange={(e) => setMobile(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label>{t("admin.language")}</Label>
              <PickSelect value={lang} onChange={(v) => setLang(v || "en")} items={langItems} label={t("admin.language")} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="staff-password">{t("admin.password")}</Label>
              <Input
                id="staff-password"
                type="text"
                autoComplete="off"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={t("admin.passwordHint")}
              />
            </div>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOpen(false)} disabled={busy}>
              {t("common.cancel")}
            </Button>
            <Button type="button" onClick={() => void submit()} disabled={busy || !canSubmit}>
              {busy ? <Loader2 className="animate-spin" /> : <UserPlus />}
              {t("admin.add")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
