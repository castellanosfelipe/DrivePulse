[CmdletBinding()]
param(
    [switch]$SkipClean
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$Root = $PSScriptRoot
$Wheelhouse = Join-Path $Root 'wheelhouse'
$BuildVenv = Join-Path $Root '.venv-build'
$DistRoot = Join-Path $Root 'dist'
$PackageRoot = Join-Path $DistRoot 'DriveMapper'

if (-not (Test-Path -LiteralPath $Wheelhouse -PathType Container)) {
    throw "Falta .\wheelhouse\. El build offline nunca consulta PyPI."
}

$Wheels = @(Get-ChildItem -LiteralPath $Wheelhouse -Filter '*.whl' -File)
if ($Wheels.Count -eq 0) {
    throw "wheelhouse está vacío. Regénérelo en una máquina con internet según USER_GUIDE.md."
}

if (-not $SkipClean) {
    foreach ($Target in @($BuildVenv, (Join-Path $Root 'build'), $DistRoot)) {
        if (Test-Path -LiteralPath $Target) {
            $Resolved = [System.IO.Path]::GetFullPath($Target)
            $ResolvedRoot = [System.IO.Path]::GetFullPath($Root)
            if (-not $Resolved.StartsWith($ResolvedRoot, [StringComparison]::OrdinalIgnoreCase)) {
                throw "Se rechazó limpiar una ruta fuera del repositorio: $Resolved"
            }
            Remove-Item -LiteralPath $Resolved -Recurse -Force
        }
    }
}

$Python = $null
try {
    $Candidate = (& py -3.12 -c "import sys; print(sys.executable)" 2>$null)
    if ($LASTEXITCODE -eq 0 -and $Candidate) { $Python = $Candidate.Trim() }
} catch {}

if (-not $Python) {
    try {
        $Candidate = (& python -c "import sys; assert sys.version_info[:2] == (3,12); print(sys.executable)" 2>$null)
        if ($LASTEXITCODE -eq 0 -and $Candidate) { $Python = $Candidate.Trim() }
    } catch {}
}

if (-not $Python) {
    $Installer = Join-Path $Root 'vendor\python-3.12.10-amd64.exe'
    if (-not (Test-Path -LiteralPath $Installer)) {
        throw "No hay Python 3.12 ni instalador vendorizado $Installer."
    }
    $Embedded = Join-Path $Root '.python-build'
    $Arguments = @(
        '/quiet',
        'InstallAllUsers=0',
        'Include_launcher=0',
        'Include_test=0',
        'Include_pip=1',
        "TargetDir=$Embedded"
    )
    $Process = Start-Process -FilePath $Installer -ArgumentList $Arguments -Wait -PassThru -WindowStyle Hidden
    if ($Process.ExitCode -ne 0) {
        throw "El instalador vendorizado de Python terminó con código $($Process.ExitCode)."
    }
    $Python = Join-Path $Embedded 'python.exe'
}

& $Python -m venv $BuildVenv
if ($LASTEXITCODE -ne 0) { throw "No se pudo crear .venv-build." }
$BuildPython = Join-Path $BuildVenv 'Scripts\python.exe'

& $BuildPython -m pip install --no-index --find-links $Wheelhouse -r (Join-Path $Root 'requirements-dev.txt')
if ($LASTEXITCODE -ne 0) { throw "Falló la instalación estrictamente offline." }

& $BuildPython -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Las pruebas fallaron; no se generará el paquete." }

$HiddenImports = @(
    '--hidden-import=win32wnet',
    '--hidden-import=win32crypt',
    '--hidden-import=win32net',
    '--hidden-import=win32evtlog',
    '--hidden-import=win32evtlogutil',
    '--hidden-import=win32security',
    '--hidden-import=servicemanager',
    '--collect-all=pydantic'
)

& $BuildPython -m PyInstaller --noconfirm --clean --onedir --noconsole --name agent @HiddenImports (Join-Path $Root 'agent.py')
if ($LASTEXITCODE -ne 0) { throw "Falló el empaquetado de agent.exe." }
& $BuildPython -m PyInstaller --noconfirm --clean --onedir --console --name drivemap @HiddenImports (Join-Path $Root 'drivemap.py')
if ($LASTEXITCODE -ne 0) { throw "Falló el empaquetado de drivemap.exe." }
& $BuildPython -m PyInstaller --noconfirm --clean --onedir --noconsole --name verify_access (Join-Path $Root 'verify_access.py')
if ($LASTEXITCODE -ne 0) { throw "Falló el empaquetado de verify_access.exe." }

New-Item -ItemType Directory -Path $PackageRoot -Force | Out-Null
foreach ($Bundle in @('agent', 'drivemap')) {
    Copy-Item -LiteralPath (Join-Path $DistRoot $Bundle) -Destination $PackageRoot -Recurse -Force
}
Copy-Item -LiteralPath (Join-Path $DistRoot 'verify_access\verify_access.exe') `
    -Destination (Join-Path $PackageRoot 'agent\verify_access.exe') -Force
Copy-Item -LiteralPath (Join-Path $Root 'install.ps1') -Destination $PackageRoot -Force
Copy-Item -LiteralPath (Join-Path $Root 'uninstall.ps1') -Destination $PackageRoot -Force
Copy-Item -LiteralPath (Join-Path $Root 'docs') -Destination $PackageRoot -Recurse -Force
Copy-Item -LiteralPath (Join-Path $Root 'README.md') -Destination $PackageRoot -Force
Copy-Item -LiteralPath (Join-Path $Root 'LICENSE') -Destination $PackageRoot -Force

& (Join-Path $PackageRoot 'agent\agent.exe') --self-test
if ($LASTEXITCODE -ne 0) {
    throw "El smoke test congelado falló; revise hidden imports de pywin32."
}
& (Join-Path $PackageRoot 'drivemap\drivemap.exe') --version
if ($LASTEXITCODE -ne 0) { throw "drivemap.exe no inicia correctamente." }

Write-Host ""
Write-Host "Paquete offline listo: $PackageRoot" -ForegroundColor Green
Write-Host "Copie la carpeta completa y ejecute como administrador:"
Write-Host "  powershell.exe -ExecutionPolicy Bypass -File .\install.ps1"
