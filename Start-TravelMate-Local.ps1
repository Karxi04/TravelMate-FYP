param(
    [Parameter(Mandatory = $true)]
    [string]$TrustedLanCidr
)

$root = $PSScriptRoot
$python = Join-Path (Split-Path $root -Parent) '.venv311\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw "Python runtime missing. Create backend_api\.venv and install backend_api\requirements-test.txt first."
}
foreach ($envFile in @('backend_api\.env', 'operator_website\.env', 'admin_website\.env')) {
    if (-not (Test-Path -LiteralPath (Join-Path $root $envFile))) {
        throw "Missing $envFile. Copy its .env.example and configure it without committing secrets."
    }
}
$env:LOCAL_LAN_DEMO = 'true'
$env:TRUSTED_LAN_CIDR = $TrustedLanCidr
foreach ($service in @(@('backend_api', 5000), @('operator_website', 5001), @('admin_website', 5002))) {
    $port = $service[1]
    if (Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue) {
        throw "Port $port is already in use. Stop that process before starting TravelMate."
    }
    Start-Process -FilePath $python -ArgumentList 'app.py' -WorkingDirectory (Join-Path $root $service[0]) -WindowStyle Hidden
}
Start-Sleep -Seconds 2
foreach ($health in @('http://127.0.0.1:5000/api/health', 'http://127.0.0.1:5001/health', 'http://127.0.0.1:5002/health')) {
    $response = Invoke-WebRequest -UseBasicParsing -Uri $health -TimeoutSec 10
    Write-Host "$health -> HTTP $($response.StatusCode)"
}
Write-Host "Phone API: http://<your-PC-LAN-IP>:5000 (trusted network: $TrustedLanCidr)"
