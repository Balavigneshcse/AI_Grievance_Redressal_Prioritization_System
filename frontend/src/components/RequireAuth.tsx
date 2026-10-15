import { Navigate, Outlet, useLocation } from "react-router-dom"
import { isStaff, useAuth } from "@/lib/auth"
import { Skeleton } from "@/components/ui/skeleton"

/** Route guard. `staff` additionally requires an officer/admin role. */
export function RequireAuth({ staff = false }: { staff?: boolean }) {
  const { token, user, ready } = useAuth()
  const location = useLocation()

  if (!token) return <Navigate to="/login" replace state={{ from: location.pathname }} />

  if (staff) {
    if (!user && !ready) {
      return (
        <div className="space-y-3">
          <Skeleton className="h-8 w-40" />
          <Skeleton className="h-32 w-full" />
        </div>
      )
    }
    if (!isStaff(user)) return <Navigate to="/" replace />
  }

  return <Outlet />
}
