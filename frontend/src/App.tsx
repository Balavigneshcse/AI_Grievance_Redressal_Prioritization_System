import { lazy, Suspense, type ReactNode } from "react"
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom"
import { AuthProvider } from "@/lib/auth"
import { TooltipProvider } from "@/components/ui/tooltip"
import { Toaster } from "@/components/ui/sonner"
import { Skeleton } from "@/components/ui/skeleton"
import { Layout } from "@/components/Layout"
import { RequireAuth } from "@/components/RequireAuth"
import Register from "@/pages/Register"
import Verify from "@/pages/Verify"
import Login from "@/pages/Login"
import Forgot from "@/pages/Forgot"
import Reset from "@/pages/Reset"
import MyComplaints from "@/pages/MyComplaints"
import Track from "@/pages/Track"

// Pages one audience never opens load on first visit, in their own chunks: the admin pages, the
// officer pages, and the complaint form, which brings Leaflet for its map (as the admin map does).
const NewComplaint = lazy(() => import("@/pages/NewComplaint"))
const OfficerQueue = lazy(() => import("@/pages/OfficerQueue"))
const OfficerComplaint = lazy(() => import("@/pages/OfficerComplaint"))
const Admin = lazy(() => import("@/pages/Admin"))
const AdminRules = lazy(() => import("@/pages/AdminRules"))
const AdminMetrics = lazy(() => import("@/pages/AdminMetrics"))
const AdminMap = lazy(() => import("@/pages/AdminMap"))

/** The header stays while a lazy page's chunk loads. */
function Lazy({ children }: { children: ReactNode }) {
  return <Suspense fallback={<Skeleton className="h-40 w-full rounded-xl" />}>{children}</Suspense>
}

export default function App() {
  return (
    <AuthProvider>
      <TooltipProvider>
        <BrowserRouter>
          <Routes>
            <Route element={<Layout />}>
              <Route path="/register" element={<Register />} />
              <Route path="/verify" element={<Verify />} />
              <Route path="/login" element={<Login />} />
              <Route path="/forgot" element={<Forgot />} />
              <Route path="/reset" element={<Reset />} />

              <Route element={<RequireAuth />}>
                <Route path="/" element={<MyComplaints />} />
                <Route path="/new" element={<Lazy><NewComplaint /></Lazy>} />
                <Route path="/c/:id" element={<Track />} />
              </Route>

              <Route element={<RequireAuth staff />}>
                <Route path="/officer/queue" element={<Lazy><OfficerQueue /></Lazy>} />
                <Route path="/officer/c/:id" element={<Lazy><OfficerComplaint /></Lazy>} />
                <Route path="/admin/map" element={<Lazy><AdminMap /></Lazy>} />
              </Route>

              <Route element={<RequireAuth staff admin />}>
                <Route path="/admin" element={<Lazy><Admin /></Lazy>} />
                <Route path="/admin/rules" element={<Lazy><AdminRules /></Lazy>} />
                <Route path="/admin/metrics" element={<Lazy><AdminMetrics /></Lazy>} />
              </Route>

              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </BrowserRouter>
        <Toaster position="top-center" richColors closeButton />
      </TooltipProvider>
    </AuthProvider>
  )
}
