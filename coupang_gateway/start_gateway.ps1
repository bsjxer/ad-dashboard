# start_gateway.ps1
# Start the gateway server hidden if it is not already running (prevents duplicates).
$ErrorActionPreference = "SilentlyContinue"

$here   = Split-Path -Parent $MyInvocation.MyCommand.Path
$server = Join-Path $here "server.py"

$listening = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($listening) { return }   # already running

$pyw = "C:\Users\bsjxe\AppData\Local\Programs\Python\Python313\pythonw.exe"
if (-not (Test-Path $pyw)) { $pyw = "pythonw" }

Start-Process -FilePath $pyw -ArgumentList ('"' + $server + '"') `
    -WorkingDirectory $here -WindowStyle Hidden
