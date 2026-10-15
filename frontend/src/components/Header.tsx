import { Link, NavLink, useNavigate } from "react-router-dom"
import { useTranslation } from "react-i18next"
import { ClipboardList, ListChecks, LogIn, LogOut, User } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { LanguageSwitcher } from "@/components/LanguageSwitcher"
import { isStaff, useAuth } from "@/lib/auth"
import { cn } from "@/lib/utils"

export function Header() {
  const { t } = useTranslation()
  const { user, token, logout } = useAuth()
  const navigate = useNavigate()
  const staff = isStaff(user)
  const initial = (user?.email?.[0] ?? "?").toUpperCase()

  return (
    <header className="sticky top-0 z-40 border-b bg-background/95 backdrop-blur supports-backdrop-filter:bg-background/80">
      <div className="mx-auto flex h-14 w-full max-w-3xl items-center gap-2 px-4">
        <Link to="/" className="flex min-w-0 items-center gap-2">
          <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <ClipboardList className="size-4" />
          </span>
          <span className="truncate font-heading text-base font-semibold tracking-tight">
            {t("app.name")}
          </span>
        </Link>

        <nav className="ml-auto flex items-center gap-1">
          {token && staff ? (
            <NavLink
              to="/officer/queue"
              className={({ isActive }) =>
                cn(
                  "inline-flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-sm font-medium transition-colors hover:bg-muted",
                  isActive && "bg-muted",
                )
              }
            >
              <ListChecks className="size-4" />
              <span className="hidden sm:inline">{t("header.queue")}</span>
            </NavLink>
          ) : null}

          <LanguageSwitcher />

          {token ? (
            <DropdownMenu>
              <DropdownMenuTrigger
                render={
                  <Button variant="ghost" size="icon" className="rounded-full" aria-label={t("header.account")} />
                }
              >
                <Avatar size="sm">
                  <AvatarFallback>{initial}</AvatarFallback>
                </Avatar>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="min-w-52">
                <DropdownMenuGroup>
                  <DropdownMenuLabel className="truncate">
                    <span className="flex items-center gap-1.5">
                      <User className="size-3.5" />
                      <span className="truncate">{user?.email ?? t("header.account")}</span>
                    </span>
                    {user?.role ? (
                      <span className="mt-0.5 block text-[11px] font-normal text-muted-foreground">
                        {t(`role.${user.role}`)}
                      </span>
                    ) : null}
                  </DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onClick={() => navigate("/")}>
                    <ClipboardList />
                    {t("header.myComplaints")}
                  </DropdownMenuItem>
                  {staff ? (
                    <DropdownMenuItem onClick={() => navigate("/officer/queue")}>
                      <ListChecks />
                      {t("header.queue")}
                    </DropdownMenuItem>
                  ) : null}
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    variant="destructive"
                    onClick={() => {
                      logout()
                      navigate("/login")
                    }}
                  >
                    <LogOut />
                    {t("header.logout")}
                  </DropdownMenuItem>
                </DropdownMenuGroup>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : (
            <Button variant="outline" size="sm" onClick={() => navigate("/login")}>
              <LogIn />
              {t("header.login")}
            </Button>
          )}
        </nav>
      </div>
    </header>
  )
}
