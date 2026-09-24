param([string]$Python = '')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not $Python) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $Python = & py -3 -c 'import sys; print(sys.executable)'
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        $Python = & python -c 'import sys; print(sys.executable)'
    }
}
if (-not $Python) { throw 'Install Python 3.12 or later from https://www.python.org/downloads/ first.' }
& $Python -c 'import sys; assert sys.version_info >= (3,12), "Python 3.12+ required"'
if ($LASTEXITCODE -ne 0) { throw 'Python version check failed.' }
$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    & $Python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
}
& $venvPython -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check your internet access and Python installation.' }
& $venvPython -c 'import pypdf, pypdfium2, reportlab, docx, PIL, cryptography, msoffcrypto, pyzipper'
if ($LASTEXITCODE -ne 0) { throw 'Dependency import check failed.' }
Write-Host 'Setup complete. Open Kaperio.cmd. Configure Hashcat and optional zip2john in Settings.'
Write-Host 'External tools are not bundled. See kaperio/docs/DISTRIBUTION.md.'
