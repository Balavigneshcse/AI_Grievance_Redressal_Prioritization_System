# Ollama settings for a 4 GB RTX 3050: keep every Gemma layer on the GPU.
# Run once in PowerShell:  powershell -ExecutionPolicy Bypass -File scripts\setup\set_ollama_gpu.ps1
# Then Ollama is restarted so the settings take effect.

setx OLLAMA_FLASH_ATTENTION 1 | Out-Null     # less VRAM for attention, faster prompt processing
setx OLLAMA_KV_CACHE_TYPE q8_0 | Out-Null    # halves the KV cache so a 4096 context fits beside the weights
setx OLLAMA_KEEP_ALIVE 30m | Out-Null        # keep the model loaded between complaints
setx OLLAMA_NUM_PARALLEL 1 | Out-Null        # one request at a time: no duplicated KV cache on a small card

Write-Host "Environment variables set. Restarting Ollama..."
Get-Process -Name "ollama app", "ollama" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2
$app = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama app.exe"
if (Test-Path $app) { Start-Process $app } else { Write-Host "Ollama app not found at $app; start it from the Start menu." }
Start-Sleep -Seconds 5
Write-Host "Done. Check placement with:  ollama run gemma3:4b 'hi'  then  ollama ps   (aim for 100% GPU)"
