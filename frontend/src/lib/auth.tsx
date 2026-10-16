import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react"
import { api, ApiError, getToken, TOKEN_KEY } from "@/lib/api"
import type { User } from "@/lib/types"

const USER_KEY = "synapse_user"

interface AuthContextValue {
  user: User | null
  token: string | null
  /** true once the initial token/user restore has settled */
  ready: boolean
  login: (token: string, user: User) => void
  logout: () => void
  /** Replace the stored user after a profile change (PATCH /auth/me). */
  updateUser: (user: User) => void
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined)

// Per-tab session with the last login as the fallback for new tabs; see getToken() in api.ts.
function readStoredUser(): User | null {
  try {
    const own = sessionStorage.getItem(USER_KEY)
    const raw = own ?? localStorage.getItem(USER_KEY)
    if (raw && !own) sessionStorage.setItem(USER_KEY, raw)
    return raw ? (JSON.parse(raw) as User) : null
  } catch {
    return null
  }
}

function storeSession(token: string | null, user: User | null) {
  try {
    for (const store of [sessionStorage, localStorage]) {
      if (token && user) {
        store.setItem(TOKEN_KEY, token)
        store.setItem(USER_KEY, JSON.stringify(user))
      } else {
        store.removeItem(TOKEN_KEY)
        store.removeItem(USER_KEY)
      }
    }
  } catch {
    /* storage unavailable - keep in memory only */
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => getToken())
  const [user, setUser] = useState<User | null>(() => readStoredUser())
  const [ready, setReady] = useState(false)

  const login = useCallback((nextToken: string, nextUser: User) => {
    storeSession(nextToken, nextUser)
    setToken(nextToken)
    setUser(nextUser)
  }, [])

  const logout = useCallback(() => {
    storeSession(null, null)
    setToken(null)
    setUser(null)
  }, [])

  const updateUser = useCallback((nextUser: User) => {
    try {
      for (const store of [sessionStorage, localStorage]) {
        if (store.getItem(USER_KEY)) store.setItem(USER_KEY, JSON.stringify(nextUser))
      }
    } catch {
      /* ignore */
    }
    setUser(nextUser)
  }, [])

  // Refresh the user from /auth/me on boot; drop the session only on a real 401.
  useEffect(() => {
    let cancelled = false
    if (!token) {
      setReady(true)
      return
    }
    api<User>("/auth/me")
      .then((me) => {
        if (cancelled) return
        setUser(me)
        try {
          sessionStorage.setItem(USER_KEY, JSON.stringify(me))
        } catch {
          /* ignore */
        }
      })
      .catch((err: unknown) => {
        if (cancelled) return
        if (err instanceof ApiError && err.status === 401) logout()
      })
      .finally(() => {
        if (!cancelled) setReady(true)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Any 401 from the API wrapper ends the session.
  useEffect(() => {
    const onUnauthorized = () => logout()
    window.addEventListener("synapse:unauthorized", onUnauthorized)
    return () => window.removeEventListener("synapse:unauthorized", onUnauthorized)
  }, [logout])

  const value = useMemo(
    () => ({ user, token, ready, login, logout, updateUser }),
    [user, token, ready, login, logout, updateUser],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>")
  return ctx
}

const STAFF_ROLES = new Set(["dept_admin", "district_admin", "super_admin", "officer", "admin"])

/** Any role that works complaints: department, district or super admin. */
export function isStaff(user: User | null): boolean {
  return !!user && STAFF_ROLES.has(user.role)
}

/** Roles that manage staff accounts: super admin (all districts) and district admin (own district). */
export function isAdmin(user: User | null): boolean {
  return user?.role === "super_admin" || user?.role === "district_admin"
}
