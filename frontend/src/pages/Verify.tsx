import { useEffect, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { useTranslation } from "react-i18next"
import { Loader2, Mail, RefreshCw, ShieldCheck } from "lucide-react"
import { toast } from "sonner"
import { api, ApiError } from "@/lib/api"
import { errorText } from "@/lib/errors"
import { useAuth } from "@/lib/auth"
import type { AuthResponse } from "@/lib/types"
import { AuthCard } from "@/components/AuthCard"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import { InputOTP, InputOTPGroup, InputOTPSlot } from "@/components/ui/input-otp"

const RESEND_SECONDS = 60

export default function Verify() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { login } = useAuth()
  const [params] = useSearchParams()
  const [email, setEmail] = useState(params.get("email") ?? "")
  const [code, setCode] = useState("")
  const [busy, setBusy] = useState(false)
  const [resending, setResending] = useState(false)
  const [cooldown, setCooldown] = useState(RESEND_SECONDS)

  useEffect(() => {
    if (cooldown <= 0) return
    const id = window.setInterval(() => setCooldown((c) => c - 1), 1000)
    return () => window.clearInterval(id)
  }, [cooldown])

  const verify = async (value = code) => {
    if (!email || value.length !== 6 || busy) return
    setBusy(true)
    try {
      const res = await api<AuthResponse>("/auth/verify-otp", { body: { email, code: value } })
      login(res.access_token, res.user)
      toast.success(t("verify.success"))
      navigate("/", { replace: true })
    } catch (err) {
      toast.error(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  // The contract has no dedicated resend route; POST /auth/resend-otp is assumed.
  const resend = async () => {
    if (!email || cooldown > 0) return
    setResending(true)
    try {
      await api("/auth/resend-otp", { body: { email } })
      toast.success(t("verify.sent"))
      setCooldown(RESEND_SECONDS)
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) toast.error(t("verify.resendUnavailable"))
      else toast.error(errorText(err))
    } finally {
      setResending(false)
    }
  }

  return (
    <AuthCard title={t("verify.title")} description={t("verify.hint", { email: email || "…" })}>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          void verify()
        }}
        noValidate
      >
        <FieldGroup>
          {!params.get("email") ? (
            <Field>
              <FieldLabel htmlFor="verify-email">{t("verify.emailLabel")}</FieldLabel>
              <div className="relative">
                <Mail className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  id="verify-email"
                  type="email"
                  autoComplete="email"
                  className="pl-8"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </div>
            </Field>
          ) : null}

          <Field className="items-center">
            <FieldLabel htmlFor="otp">{t("auth.code")}</FieldLabel>
            <InputOTP
              id="otp"
              maxLength={6}
              value={code}
              onChange={setCode}
              onComplete={(v: string) => void verify(v)}
              inputMode="numeric"
              autoFocus
              containerClassName="justify-center"
            >
              <InputOTPGroup>
                {[0, 1, 2, 3, 4, 5].map((i) => (
                  <InputOTPSlot key={i} index={i} className="size-11 text-lg" />
                ))}
              </InputOTPGroup>
            </InputOTP>
          </Field>

          <Button type="submit" className="w-full" disabled={busy || code.length !== 6 || !email}>
            {busy ? <Loader2 className="animate-spin" /> : <ShieldCheck />}
            {t("verify.verify")}
          </Button>

          <Button
            type="button"
            variant="link"
            className="w-full"
            disabled={cooldown > 0 || resending || !email}
            onClick={() => void resend()}
          >
            {resending ? <Loader2 className="animate-spin" /> : <RefreshCw />}
            {cooldown > 0 ? t("verify.resendIn", { s: cooldown }) : t("verify.resend")}
          </Button>
        </FieldGroup>
      </form>
    </AuthCard>
  )
}
