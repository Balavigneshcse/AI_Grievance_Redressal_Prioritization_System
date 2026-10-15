import { useState } from "react"
import { Link, useLocation, useNavigate } from "react-router-dom"
import { useTranslation } from "react-i18next"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { Loader2, LogIn, Mail } from "lucide-react"
import { toast } from "sonner"
import { api, ApiError } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import type { AuthResponse } from "@/lib/types"
import { AuthCard } from "@/components/AuthCard"
import { PasswordInput } from "@/components/PasswordInput"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Field, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field"

const schema = z.object({
  email: z.email({ error: "validation.email" }),
  password: z.string().min(1, "validation.required"),
})

type FormValues = z.infer<typeof schema>

export default function Login() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const location = useLocation()
  const { login } = useAuth()
  const [busy, setBusy] = useState(false)
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormValues>({ resolver: zodResolver(schema), defaultValues: { email: "", password: "" } })

  const from = (location.state as { from?: string } | null)?.from || "/"

  const onSubmit = async (values: FormValues) => {
    setBusy(true)
    try {
      const res = await api<AuthResponse>("/auth/login", { body: values })
      login(res.access_token, res.user)
      toast.success(t("auth.welcome"))
      navigate(from, { replace: true })
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        toast.info(t("auth.notVerified"))
        navigate(`/verify?email=${encodeURIComponent(values.email)}`)
        return
      }
      toast.error(err instanceof ApiError && err.message !== "network_error" ? err.message : t("errors.network"))
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthCard
      title={t("auth.loginTitle")}
      description={t("auth.loginHint")}
      footer={
        <span>
          {t("auth.noAccount")}{" "}
          <Link to="/register" className="font-medium text-foreground underline underline-offset-4">
            {t("auth.registerLink")}
          </Link>
        </span>
      }
    >
      <form onSubmit={handleSubmit(onSubmit)} noValidate>
        <FieldGroup>
          <Field data-invalid={!!errors.email}>
            <FieldLabel htmlFor="email">{t("auth.email")}</FieldLabel>
            <div className="relative">
              <Mail className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                id="email"
                type="email"
                autoComplete="email"
                placeholder="you@example.com"
                className="pl-8"
                aria-invalid={!!errors.email}
                {...register("email")}
              />
            </div>
            <FieldError>{errors.email?.message ? t(errors.email.message) : undefined}</FieldError>
          </Field>

          <Field data-invalid={!!errors.password}>
            <div className="flex items-center justify-between">
              <FieldLabel htmlFor="password">{t("auth.password")}</FieldLabel>
              <Link to="/forgot" className="text-xs text-muted-foreground underline underline-offset-4">
                {t("auth.forgotLink")}
              </Link>
            </div>
            <PasswordInput
              id="password"
              autoComplete="current-password"
              aria-invalid={!!errors.password}
              {...register("password")}
            />
            <FieldError>{errors.password?.message ? t(errors.password.message) : undefined}</FieldError>
          </Field>

          <Button type="submit" className="w-full" disabled={busy}>
            {busy ? <Loader2 className="animate-spin" /> : <LogIn />}
            {t("auth.login")}
          </Button>
        </FieldGroup>
      </form>
    </AuthCard>
  )
}
