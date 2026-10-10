$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Build this package on Windows x64.' }
Set-Location (Split-Path $PSScriptRoot -Parent)
function Invoke-Checked { param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed with exit code $LASTEXITCODE" }
}
# Prefer the Windows Python launcher so a newer default Python does not
# accidentally select an interpreter incompatible with the release lock.
$BuildPython = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
    $Candidate = & py -3.13 packaging/check-python.py
    if ($LASTEXITCODE -eq 0) { $BuildPython = ($Candidate | Select-Object -Last 1) }
}
if (-not $BuildPython -and (Get-Command python -ErrorAction SilentlyContinue)) {
    $Candidate = & python packaging/check-python.py
    if ($LASTEXITCODE -eq 0) { $BuildPython = ($Candidate | Select-Object -Last 1) }
}
if (-not $BuildPython) {
    throw 'Install Python 3.13 x64 with its Python launcher or add it to PATH. Python 3.14 is not supported by this build lock.'
}
$NodeVersion = & node --version
if ($LASTEXITCODE -ne 0 -or $NodeVersion -notmatch '^v22\.') {
    throw 'Node.js 22 is required for this build.'
}
Invoke-Checked -Program $BuildPython -Arguments @('-m', 'venv', '.venv-build')
$Python = Join-Path $PWD '.venv-build/Scripts/python.exe'
Invoke-Checked -Program $Python -Arguments @('-m', 'pip', 'install', 'pip==25.2')
Invoke-Checked -Program $Python -Arguments @('-m', 'pip', 'install', '-r', 'packaging/requirements-windows.lock')
Invoke-Checked -Program $Python -Arguments @('-m', 'pip', 'install', '--no-deps', '--no-build-isolation', '.')
Invoke-Checked -Program npm.cmd -Arguments @('--prefix', 'frontend', 'ci')
Invoke-Checked -Program npm.cmd -Arguments @('--prefix', 'frontend', 'run', 'build')
Invoke-Checked -Program $Python -Arguments @('-m', 'PyInstaller', '--clean', '--noconfirm', 'packaging/windows.spec')
Copy-Item LICENSE 'dist/LMU Telemetry/LICENSE.txt'
Copy-Item packaging/PORTABLE.txt 'dist/LMU Telemetry/README.txt'
Invoke-Checked -Program $Python -Arguments @('packaging/smoke-windows.py', 'dist/LMU Telemetry/LMU Telemetry.exe')
Compress-Archive -Path 'dist/LMU Telemetry' -DestinationPath 'dist/LMU-Telemetry-windows-x64.zip' -Force
