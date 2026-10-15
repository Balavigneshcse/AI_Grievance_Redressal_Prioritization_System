import { Outlet } from "react-router-dom"
import { Header } from "@/components/Header"

export function Layout() {
  return (
    <div className="flex min-h-dvh flex-col bg-background">
      <Header />
      <main className="mx-auto w-full max-w-3xl flex-1 px-4 pt-4 pb-28">
        <Outlet />
      </main>
    </div>
  )
}
