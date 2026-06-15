# Start MoneyLine live API + WebSocket dashboards (single process).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root
$env:PYTHONPATH = Join-Path $root "src"

# Stop stale listeners that block ports but no longer respond.
foreach ($port in 8080, 8501) {
    $lines = netstat -ano | Select-String ":$port\s.*LISTENING"
    foreach ($line in $lines) {
        if ($line -match "\s(\d+)\s*$") {
            $procId = [int]$Matches[1]
            if ($procId -gt 0) {
                Write-Host "Stopping stale process on port ${port} (PID $procId)..."
                Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

Start-Sleep -Seconds 1
Write-Host "Starting MoneyLine on http://localhost:8080"
Write-Host "  Public:  http://localhost:8080/"
Write-Host "  Admin:   http://localhost:8080/admin"
Write-Host "  Subs:    http://localhost:8080/dashboard"
Write-Host "  Health:  http://localhost:8080/health"
Write-Host ""
Write-Host "Runs automatically: prematch scanner, WebSocket feeds, Telegram arb alerts,"
Write-Host "                    Telegram subscription bot (/subscribe)."
& (Join-Path $root ".venv\Scripts\python.exe") -m moneyline.cli serve --host 0.0.0.0 --port 8080
