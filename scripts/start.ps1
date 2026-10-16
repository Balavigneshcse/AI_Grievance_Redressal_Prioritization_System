<#
One-command start for the demo laptop.

  powershell -ExecutionPolicy Bypass -File scripts\start.ps1            # Postgres + Mailpit, API :8000, app :5173
  powershell -ExecutionPolicy Bypass -File scripts\start.ps1 -Https     # same over HTTPS on the LAN address, for phones
  powershell -ExecutionPolicy Bypass -File scripts\start.ps1 -NoFrontend

The API and the app each open in their own PowerShell window so their logs stay visible.
Ollama must already be running (it starts with Windows). Phones: open https://<ip>:8000/health once and
accept the certificate warning, then https://<ip>:5173.
#>
param(
    [switch]$Https,
    [switch]$NoFrontend
)

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

docker compose up -d
if ($LASTEXITCODE -ne 0) { Write-Host "docker compose failed; is Docker Desktop running?" -ForegroundColor Red; exit 1 }

$api = "python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000"
$web = "npm run dev --prefix frontend -- --host 0.0.0.0 --port 5173"
$envPrefix = ""

if ($Https) {
    if (-not (Test-Path "certs\cert.pem")) { python scripts\setup\make_cert.py }
    $ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -like "192.168.*" -or $_.IPAddress -like "10.*" -or $_.IPAddress -like "172.*" } | Select-Object -First 1).IPAddress
    if (-not $ip) { $ip = "127.0.0.1" }
    $api += " --ssl-keyfile certs\key.pem --ssl-certfile certs\cert.pem"
    $envPrefix = "`$env:VITE_HTTPS='1'; `$env:VITE_API_URL='https://$($ip):8000'; "
    Write-Host ""
    Write-Host "HTTPS demo mode. On the phone (same Wi-Fi):" -ForegroundColor Cyan
    Write-Host "  1. open https://$($ip):8000/health and accept the certificate warning" -ForegroundColor Cyan
    Write-Host "  2. open https://$($ip):5173" -ForegroundColor Cyan
    Write-Host ""
}

Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root'; $api"
if (-not $NoFrontend) {
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root'; $envPrefix$web"
}
Write-Host "API: http://localhost:8000/docs   App: http://localhost:5173   Mail: http://localhost:8025"
