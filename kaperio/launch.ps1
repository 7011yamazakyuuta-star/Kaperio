$ErrorActionPreference = 'Stop'
$appRoot = $PSScriptRoot
$pythonExe = Join-Path $appRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw 'Python environment missing. Run Setup.cmd first. See kaperio/README.md.'
}
$statePath = Join-Path (Split-Path $appRoot) 'outputs\kaperio\launch.json'
if (Test-Path -LiteralPath $statePath) {
    $launch = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    if (Get-Process -Id $launch.pid -ErrorAction SilentlyContinue) {
        try {
            $response = Invoke-WebRequest -Uri $launch.url -UseBasicParsing -SessionVariable kaperioSession -TimeoutSec 5
            if ($response.StatusCode -eq 200) {
                Start-Process $launch.url
                exit 0
            }
        } catch { }
    }
}
Start-Process -FilePath $pythonExe -ArgumentList @('"' + (Join-Path $appRoot 'app.py') + '"') -WorkingDirectory $appRoot -WindowStyle Hidden
