import { forwardRef, useState, type ComponentProps } from "react"
import { useTranslation } from "react-i18next"
import { Eye, EyeOff, Lock } from "lucide-react"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
import { passwordLevel, passwordScore } from "@/lib/password"
import { cn } from "@/lib/utils"

type Props = Omit<ComponentProps<typeof Input>, "type"> & {
  /** Show the strength Progress bar under the field. */
  strength?: boolean
  /** Current value, needed for the strength meter when using react-hook-form register. */
  strengthValue?: string
}

const LEVEL_BAR = {
  weak: "**:data-[slot=progress-indicator]:bg-red-500",
  fair: "**:data-[slot=progress-indicator]:bg-amber-500",
  strong: "**:data-[slot=progress-indicator]:bg-emerald-600",
} as const

const LEVEL_TEXT = {
  weak: "text-red-700",
  fair: "text-amber-700",
  strong: "text-emerald-700",
} as const

export const PasswordInput = forwardRef<HTMLInputElement, Props>(function PasswordInput(
  { strength = false, strengthValue = "", className, ...props },
  ref,
) {
  const { t } = useTranslation()
  const [show, setShow] = useState(false)
  const score = passwordScore(strengthValue)
  const level = passwordLevel(score)

  return (
    <div className="space-y-1.5">
      <div className="relative">
        <Lock className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          ref={ref}
          type={show ? "text" : "password"}
          autoComplete={props.autoComplete ?? "current-password"}
          className={cn("pr-9 pl-8", className)}
          {...props}
        />
        <Button
          type="button"
          variant="ghost"
          size="icon-xs"
          className="absolute top-1/2 right-1 -translate-y-1/2 text-muted-foreground"
          aria-label={show ? t("auth.hidePassword") : t("auth.showPassword")}
          onClick={() => setShow((s) => !s)}
          tabIndex={-1}
        >
          {show ? <EyeOff /> : <Eye />}
        </Button>
      </div>
      {strength ? (
        <div className={cn("space-y-1", LEVEL_BAR[level])}>
          <Progress value={score} className="gap-0" aria-label={t(`password.${level}`)} />
          <p className="flex justify-between gap-2 text-xs text-muted-foreground">
            <span>{t("password.rules")}</span>
            {strengthValue ? (
              <span className={cn("shrink-0 font-medium", LEVEL_TEXT[level])}>{t(`password.${level}`)}</span>
            ) : null}
          </p>
        </div>
      ) : null}
    </div>
  )
})
