import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom"
import { AuthProvider } from "@/lib/auth"
import { TooltipProvider } from "@/components/ui/tooltip"
import { Toaster } from "@/components/ui/sonner"
import { Layout } from "@/components/Layout"
import { RequireAuth } from "@/components/RequireAuth"
import Register from "@/pages/Register"
import Verify from "@/pages/Verify"
import Login from "@/pages/Login"
import Forgot from "@/pages/Forgot"
import Reset from "@/pages/Reset"
import MyComplaints from "@/pages/MyComplaints"
import NewComplaint from "@/pages/NewComplaint"
import Track from "@/pages/Track"
import OfficerQueue from "@/pages/OfficerQueue"
import OfficerComplaint from "@/pages/OfficerComplaint"
import Admin from "@/pages/Admin"
import AdminRules from "@/pages/AdminRules"
import AdminMetrics from "@/pages/AdminMetrics"
import AdminMap from "@/pages/AdminMap"

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
                <Route path="/new" element={<NewComplaint />} />
                <Route path="/c/:id" element={<Track />} />
              </Route>

              <Route element={<RequireAuth staff />}>
                <Route path="/officer/queue" element={<OfficerQueue />} />
                <Route path="/officer/c/:id" element={<OfficerComplaint />} />
                <Route path="/admin/map" element={<AdminMap />} />
              </Route>

              <Route element={<RequireAuth staff admin />}>
                <Route path="/admin" element={<Admin />} />
                <Route path="/admin/rules" element={<AdminRules />} />
                <Route path="/admin/metrics" element={<AdminMetrics />} />
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
