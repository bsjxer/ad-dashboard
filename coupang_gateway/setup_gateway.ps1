# setup_gateway.ps1   (run once, as Administrator)
# 1) Auto-start the gateway whenever this PC logs on
# 2) Allow inbound TCP 8000 on the local network (so LAN teammates can reach it)
#
# Run:  Start menu -> PowerShell (right-click) -> Run as administrator -> paste:
#       powershell -ExecutionPolicy Bypass -File "C:\Users\bsjxe\Desktop\승진\클로드코드\coupang_gateway\setup_gateway.ps1"

$ErrorActionPreference = "Stop"
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$startScript = Join-Path $dir "start_gateway.ps1"

Write-Host "1) Auto-start on logon"
$run = 'powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $startScript + '"'
New-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' `
    -Name 'CoupangGateway' -Value $run -PropertyType String -Force | Out-Null
Write-Host "   done"

Write-Host "2) Firewall inbound TCP 8000 (Private/Domain profiles)"
if (-not (Get-NetFirewallRule -DisplayName "Coupang Gateway 8000" -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName "Coupang Gateway 8000" -Direction Inbound `
        -Action Allow -Protocol TCP -LocalPort 8000 -Profile Domain,Private | Out-Null
    Write-Host "   rule added"
} else {
    Write-Host "   rule already exists"
}

Write-Host "3) Start gateway now"
& $startScript

Write-Host ""
Write-Host "Done. Gateway auto-runs whenever this PC is on."
Write-Host "Teammates on the same network call:  http://192.168.0.19:8000/<vendorId>/settlement"
