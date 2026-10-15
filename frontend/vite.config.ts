import fs from "node:fs"
import { fileURLToPath, URL } from "node:url"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"
import { defineConfig } from "vite"

// HTTPS for phone demos: `VITE_HTTPS=1` with certs/ from scripts/make_cert.py
// (browsers allow the camera and GPS only on localhost or HTTPS).
const certDir = fileURLToPath(new URL("../certs", import.meta.url))
const https =
  process.env.VITE_HTTPS === "1" && fs.existsSync(`${certDir}/cert.pem`)
    ? { key: fs.readFileSync(`${certDir}/key.pem`), cert: fs.readFileSync(`${certDir}/cert.pem`) }
    : undefined

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: { https },
})
