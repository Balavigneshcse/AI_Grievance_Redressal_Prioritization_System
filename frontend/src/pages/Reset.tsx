import { useState } from "react"
import { Link, useNavigate, useSearchParams } from "react-router-dom"
import { useTranslation } from "react-i18next"
import { Controller, useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { KeyRound, Loader2, Mail } from "lucide-react"
import { toast } from "sonner"
import { api, ApiError } from "@/lib/api"
import { passwordSchema } from "@/lib/password"
import { AuthCard } from "@/components/AuthCard"
import { PasswordInput } from "@/components/PasswordInput"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Field, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field"
import { InputOTP, InputOTPGroup, InputOTPSlot } from "@/components/ui/input-otp"

const schema = z.object({
  email: z.email({ error: "validation.email" }),
  code: z.string().length(6, "validation.code"),
  new_password: passwordSchema,
})
type FormValues = z.infer<typeof schema>

export default function Reset() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [busy, setBusy] = useState(false)
  const {
    register,
    control,
    handleSubmit,
    watch,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { email: params.get("email") ?? "", code: "", new_password: "" },
  })
  const newPassword = watch("new_password")

  const onSubmit = async (values: FormValues) => {
    setBusy(true)
    try {
      const res = await api<{ message?: string }>("/auth/reset", { body: values })
      toast.success(res?.message || t("auth.resetDone"))
      navigate("/login", { replace: true })
    } catch (err) {
      toast.error(err instanceof ApiError && err.message !== "network_error" ? err.message : t("errors.network"))
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthCard
      title={t("auth.resetTitle")}
      description={t("auth.resetHint")}
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
                className="pl-8"
                aria-invalid={!!errors.email}
                {...register("email")}
              />
            </div>
            <FieldError>{errors.email?.message ? t(errors.email.message) : undefined}</FieldError>
          </Field>

          <Field data-invalid={!!errors.code} className="items-center">
            <FieldLabel htmlFor="code">{t("auth.code")}</FieldLabel>
            <Controller
              control={control}
              name="code"
              render={({ field }) => (
                <InputOTP
                  id="code"
                  maxLength={6}
                  value={field.value}
                  onChange={field.onChange}
                  inputMode="numeric"
                  containerClassName="justify-center"
                >
                  <InputOTPGroup>
                    {[0, 1, 2, 3, 4, 5].map((i) => (
                      <InputOTPSlot key={i} index={i} className="size-11 text-lg" />
                    ))}
                  </InputOTPGroup>
                </InputOTP>
              )}
            />
            <FieldError>{errors.code?.message ? t(errors.code.message) : undefined}</FieldError>
          </Field>

          <Field data-invalid={!!errors.new_password}>
            <FieldLabel htmlFor="new_password">{t("auth.newPassword")}</FieldLabel>
            <PasswordInput
              id="new_password"
              autoComplete="new-password"
              strength
              strengthValue={newPassword}
              aria-invalid={!!errors.new_password}
              {...register("new_password")}
            />
            <FieldError>{errors.new_password?.message ? t(errors.new_password.message) : undefined}</FieldError>
          </Field>

          <Button type="submit" className="w-full" disabled={busy}>
            {busy ? <Loader2 className="animate-spin" /> : <KeyRound />}
            {t("auth.reset")}
          </Button>
        </FieldGroup>
      </form>
    </AuthCard>
  )
}
