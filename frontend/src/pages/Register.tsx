import { useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { useTranslation } from "react-i18next"
import { Controller, useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { Loader2, Mail, Phone, UserPlus } from "lucide-react"
import { toast } from "sonner"
import { api, ApiError } from "@/lib/api"
import { passwordSchema } from "@/lib/password"
import { LANGS } from "@/lib/i18n"
import { AuthCard } from "@/components/AuthCard"
import { PasswordInput } from "@/components/PasswordInput"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Field, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"

const schema = z.object({
  mobile: z.string().regex(/^[0-9]{10}$/, "validation.mobile"),
  email: z.email({ error: "validation.email" }),
  password: passwordSchema,
  preferred_language: z.enum(["en", "ta", "hi"]),
})

type FormValues = z.infer<typeof schema>

export default function Register() {
  const { t, i18n } = useTranslation()
  const navigate = useNavigate()
  const [busy, setBusy] = useState(false)
  const {
    register,
    control,
    handleSubmit,
    watch,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      mobile: "",
      email: "",
      password: "",
      preferred_language: (["en", "ta", "hi"].includes(i18n.language.slice(0, 2))
        ? i18n.language.slice(0, 2)
        : "en") as FormValues["preferred_language"],
    },
  })
  const password = watch("password")
  const langItems = LANGS.map((l) => ({ value: l.code, label: l.nativeLabel }))

  const onSubmit = async (values: FormValues) => {
    setBusy(true)
    try {
      const res = await api<{ user_id: string; message?: string }>("/auth/register", { body: values })
      toast.success(res?.message || t("auth.registered"))
      navigate(`/verify?email=${encodeURIComponent(values.email)}`)
    } catch (err) {
      toast.error(err instanceof ApiError && err.message !== "network_error" ? err.message : t("errors.network"))
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthCard
      title={t("auth.registerTitle")}
      description={t("auth.registerHint")}
      footer={
        <span>
          {t("auth.haveAccount")}{" "}
          <Link to="/login" className="font-medium text-foreground underline underline-offset-4">
            {t("auth.loginLink")}
          </Link>
        </span>
      }
    >
      <form onSubmit={handleSubmit(onSubmit)} noValidate>
        <FieldGroup>
          <Field data-invalid={!!errors.mobile}>
            <FieldLabel htmlFor="mobile">{t("auth.mobile")}</FieldLabel>
            <div className="relative">
              <Phone className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                id="mobile"
                inputMode="numeric"
                autoComplete="tel-national"
                placeholder="9876543210"
                maxLength={10}
                className="pl-8"
                aria-invalid={!!errors.mobile}
                {...register("mobile")}
              />
            </div>
            <FieldError>{errors.mobile?.message ? t(errors.mobile.message) : undefined}</FieldError>
          </Field>

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
            <FieldLabel htmlFor="password">{t("auth.password")}</FieldLabel>
            <PasswordInput
              id="password"
              autoComplete="new-password"
              strength
              strengthValue={password}
              aria-invalid={!!errors.password}
              {...register("password")}
            />
            <FieldError>{errors.password?.message ? t(errors.password.message) : undefined}</FieldError>
          </Field>

          <Field>
            <FieldLabel htmlFor="preferred_language">{t("auth.preferredLanguage")}</FieldLabel>
            <Controller
              control={control}
              name="preferred_language"
              render={({ field }) => (
                <Select
                  value={field.value}
                  onValueChange={(v) => field.onChange(v ?? "en")}
                  items={langItems}
                >
                  <SelectTrigger id="preferred_language" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {langItems.map((l) => (
                      <SelectItem key={l.value} value={l.value}>
                        {l.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            />
          </Field>

          <Button type="submit" className="w-full" disabled={busy}>
            {busy ? <Loader2 className="animate-spin" /> : <UserPlus />}
            {t("auth.register")}
          </Button>
        </FieldGroup>
      </form>
    </AuthCard>
  )
}
