import { useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { useTranslation } from "react-i18next"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { Loader2, Mail, Send } from "lucide-react"
import { toast } from "sonner"
import { api, ApiError } from "@/lib/api"
import { AuthCard } from "@/components/AuthCard"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Field, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field"

const schema = z.object({ email: z.email({ error: "validation.email" }) })
type FormValues = z.infer<typeof schema>

export default function Forgot() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [busy, setBusy] = useState(false)
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormValues>({ resolver: zodResolver(schema), defaultValues: { email: "" } })

  const onSubmit = async (values: FormValues) => {
    setBusy(true)
    try {
      const res = await api<{ message?: string }>("/auth/forgot", { body: values })
      toast.success(res?.message || t("auth.codeSent"))
      navigate(`/reset?email=${encodeURIComponent(values.email)}`)
    } catch (err) {
      toast.error(err instanceof ApiError && err.message !== "network_error" ? err.message : t("errors.network"))
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthCard
      title={t("auth.forgotTitle")}
      description={t("auth.forgotHint")}
      footer={
        <Link to="/login" className="font-medium text-foreground underline underline-offset-4">
          {t("auth.backToLogin")}
        </Link>
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
          <Button type="submit" className="w-full" disabled={busy}>
            {busy ? <Loader2 className="animate-spin" /> : <Send />}
            {t("auth.sendCode")}
          </Button>
        </FieldGroup>
      </form>
    </AuthCard>
  )
}
