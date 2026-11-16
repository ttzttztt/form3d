param([switch]$Install, [int]$Port = 8000)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $pythonPath)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create Python environment.' }
    $Install = $true
}
if ($Install) {
    & $pythonPath -m pip install -r requirements.txt --disable-pip-version-check
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
    npm ci --registry=https://registry.npmjs.org --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw 'Node dependency installation failed.' }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
}
if (!(Test-Path -LiteralPath 'apps\web\dist\index.html')) {
    throw 'Frontend is not built. Run .\start.ps1 -Install first.'
}
Write-Host "FORM workbench: http://127.0.0.1:$Port"
& $pythonPath -m uvicorn services.api.app:app --host 127.0.0.1 --port $Port
