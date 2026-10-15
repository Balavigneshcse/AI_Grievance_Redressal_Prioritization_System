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
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined)

function readStoredUser(): User | null {
  try {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? (JSON.parse(raw) as User) : null
  } catch {
    return null
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => getToken())
  const [user, setUser] = useState<User | null>(() => readStoredUser())
  const [ready, setReady] = useState(false)

  const login = useCallback((nextToken: string, nextUser: User) => {
    try {
      localStorage.setItem(TOKEN_KEY, nextToken)
      localStorage.setItem(USER_KEY, JSON.stringify(nextUser))
    } catch {
      /* storage unavailable - keep in memory only */
    }
    setToken(nextToken)
    setUser(nextUser)
  }, [])

  const logout = useCallback(() => {
    try {
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(USER_KEY)
    } catch {
      /* ignore */
    }
    setToken(null)
    setUser(null)
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
          localStorage.setItem(USER_KEY, JSON.stringify(me))
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
    () => ({ user, token, ready, login, logout }),
    [user, token, ready, login, logout],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>")
  return ctx
}

export function isStaff(user: User | null): boolean {
  return user?.role === "officer" || user?.role === "admin"
}
