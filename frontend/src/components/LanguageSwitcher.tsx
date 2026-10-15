import { useTranslation } from "react-i18next"
import { Check, Languages } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { LANGS } from "@/lib/i18n"

export function LanguageSwitcher() {
  const { t, i18n } = useTranslation()
  const active = i18n.language.slice(0, 2)

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={<Button variant="ghost" size="icon" aria-label={t("header.language")} />}
      >
        <Languages />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-40">
        <DropdownMenuGroup>
          <DropdownMenuLabel>{t("header.language")}</DropdownMenuLabel>
          <DropdownMenuSeparator />
          {LANGS.map((l) => (
            <DropdownMenuItem key={l.code} onClick={() => void i18n.changeLanguage(l.code)}>
              <span className="flex-1">{l.nativeLabel}</span>
              {active === l.code ? <Check className="text-primary" /> : null}
            </DropdownMenuItem>
          ))}
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
