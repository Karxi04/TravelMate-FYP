param(
    [Parameter(Mandatory = $true)]
    [string]$TrustedLanCidr
)

$root = $PSScriptRoot
$services = @(
    @('backend_api', 5000, (Join-Path $root 'backend_api\.venv\Scripts\python.exe')),
    @('operator_website', 5001, (Join-Path $root 'operator_website\.venv\Scripts\python.exe')),
    @('admin_website', 5002, (Join-Path $root 'admin_website\.venv\Scripts\python.exe'))
)
foreach ($service in $services) {
    if (-not (Test-Path -LiteralPath $service[2])) {
        throw "Python runtime missing: $($service[2]). Create the service's local .venv and install its requirements first."
    }
}
foreach ($envFile in @('backend_api\.env', 'operator_website\.env', 'admin_website\.env')) {
    if (-not (Test-Path -LiteralPath (Join-Path $root $envFile))) {
        throw "Missing $envFile. Copy its .env.example and configure it without committing secrets."
    }
}
$env:LOCAL_LAN_DEMO = 'true'
$env:TRUSTED_LAN_CIDR = $TrustedLanCidr
foreach ($service in $services) {
    $port = $service[1]
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        throw "Port $port is already in use. Stop that process before starting TravelMate."
    }
    Start-Process -FilePath $service[2] -ArgumentList 'app.py' -WorkingDirectory (Join-Path $root $service[0]) -WindowStyle Hidden
}
foreach ($health in @('http://127.0.0.1:5000/api/health', 'http://127.0.0.1:5001/health', 'http://127.0.0.1:5002/health')) {
    $response = $null
    for ($attempt = 1; $attempt -le 15 -and -not $response; $attempt++) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $health -TimeoutSec 2 -ErrorAction Stop
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    if (-not $response) {
        throw "Service did not become healthy: $health"
    }
    Write-Host "$health -> HTTP $($response.StatusCode)"
}
Write-Host "Phone API: http://<your-PC-LAN-IP>:5000 (trusted network: $TrustedLanCidr)"
