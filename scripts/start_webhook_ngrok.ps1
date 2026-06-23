# HQH-539 — start local Stripe webhook + ngrok tunnel
# Usage:
#   1. Get free authtoken: https://dashboard.ngrok.com/get-started/your-authtoken
#   2. ngrok config add-authtoken YOUR_TOKEN   (one-time)
#   3. .\scripts\start_webhook_ngrok.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = Join-Path $Root "venv\Scripts\python.exe"
$Ngrok = (Get-Command ngrok -ErrorAction SilentlyContinue).Source

if (-not (Test-Path $Python)) {
    Write-Error "venv not found. Run: python -m venv venv && .\venv\Scripts\pip install -r requirements.txt"
}
if (-not $Ngrok) {
    Write-Error "ngrok not found. Install: winget install Ngrok.Ngrok"
}

# Load .env into process for child jobs
if (Test-Path ".env") {
    Get-Content ".env" | ForEach-Object {
        if ($_ -match '^\s*([^#][^=]+)=(.*)$') {
            $name = $matches[1].Trim()
            $value = $matches[2].Trim()
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
}

$WebhookPort = if ($env:WEBHOOK_PORT) { $env:WEBHOOK_PORT } else { "5001" }

Write-Host "Starting webhook on http://127.0.0.1:$WebhookPort/webhook ..."
$webhookJob = Start-Job -ScriptBlock {
    param($Root, $Python, $Port)
    Set-Location $Root
    $env:PORT = $Port
    & $Python webhook_handler.py
} -ArgumentList $Root, $Python, $WebhookPort

Start-Sleep -Seconds 2
try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:$WebhookPort/health" -Method GET -TimeoutSec 5
    Write-Host "Webhook health: $($health.status)"
} catch {
    Stop-Job $webhookJob -ErrorAction SilentlyContinue
    Receive-Job $webhookJob
    throw "Webhook failed to start on port $WebhookPort"
}

Write-Host ""
Write-Host "Starting ngrok tunnel -> localhost:$WebhookPort"
Write-Host "Stripe endpoint URL will be: https://<ngrok-id>.ngrok-free.app/webhook"
Write-Host "Press Ctrl+C to stop both."
Write-Host ""

try {
    & ngrok http $WebhookPort
} finally {
    Stop-Job $webhookJob -ErrorAction SilentlyContinue
    Remove-Job $webhookJob -Force -ErrorAction SilentlyContinue
    Write-Host "Stopped webhook and ngrok."
}