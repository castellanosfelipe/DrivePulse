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

function Test-Python312 {
    param([Parameter(Mandatory=$true)][string]$Executable)
    try {
        $Candidate = (& $Executable -c (
            "import sys; " +
            "assert sys.version_info[:2] == (3, 12); " +
            "print(sys.executable)"
        ) 2>$null)
        if ($LASTEXITCODE -eq 0 -and $Candidate) {
            return $Candidate.Trim()
        }
    } catch {}
    return $null
}

if (-not (Test-Path -LiteralPath $Wheelhouse -PathType Container)) {
    throw "Falta .\wheelhouse\. El build offline nunca consulta PyPI."
}

$Wheels = @(Get-ChildItem -LiteralPath $Wheelhouse -Filter '*.whl' -File)
if ($Wheels.Count -eq 0) {
    throw "wheelhouse esta vacio."
}

if (-not $SkipClean) {
    foreach ($Target in @($BuildVenv, (Join-Path $Root 'build'), $DistRoot)) {
        if (Test-Path -LiteralPath $Target) {
            $Resolved = [IO.Path]::GetFullPath($Target)
            $ResolvedRoot = [IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
            if (-not $Resolved.StartsWith(
                $ResolvedRoot,
                [StringComparison]::OrdinalIgnoreCase
            )) {
                throw "Se rechazo limpiar una ruta fuera del repositorio: $Resolved"
            }
            Remove-Item -LiteralPath $Resolved -Recurse -Force
        }
    }
}

$Python = $null
$LocalPython = Join-Path $Root '.python-build\python.exe'
if (Test-Path -LiteralPath $LocalPython -PathType Leaf) {
    $Python = Test-Python312 -Executable $LocalPython
}

if (-not $Python) {
    try {
        $Candidate = (& py -3.12 -c (
            "import sys; " +
            "assert sys.version_info[:2] == (3, 12); " +
            "print(sys.executable)"
        ) 2>$null)
        if ($LASTEXITCODE -eq 0 -and $Candidate) {
            $Python = $Candidate.Trim()
        }
    } catch {}
}

if (-not $Python) {
    foreach ($CommandName in @('python3.12', 'python')) {
        $Command = Get-Command $CommandName -ErrorAction SilentlyContinue
        if ($Command) {
            $Python = Test-Python312 -Executable $Command.Source
            if ($Python) { break }
        }
    }
}

if (-not $Python) {
    $Installer = Join-Path $Root 'vendor\python-3.12.10-amd64.exe'
    if (-not (Test-Path -LiteralPath $Installer -PathType Leaf)) {
        throw "No hay Python 3.12 ni instalador vendorizado $Installer."
    }
    $Signature = Get-AuthenticodeSignature -LiteralPath $Installer
    if ($Signature.Status -ne 'Valid') {
        throw "La firma del instalador vendorizado de Python no es valida."
    }
    $Embedded = Join-Path $Root '.python-build'
    if (Test-Path -LiteralPath $Embedded) {
        Remove-Item -LiteralPath $Embedded -Recurse -Force
    }
    $Arguments = @(
        '/quiet',
        'InstallAllUsers=0',
        'Include_launcher=0',
        'Include_test=0',
        'Include_pip=1',
        "TargetDir=$Embedded"
    )
    $Process = Start-Process `
        -FilePath $Installer `
        -ArgumentList $Arguments `
        -Wait `
        -PassThru `
        -WindowStyle Hidden
    if ($Process.ExitCode -ne 0) {
        throw "El instalador vendorizado termino con codigo $($Process.ExitCode)."
    }
    $Python = Test-Python312 -Executable (Join-Path $Embedded 'python.exe')
    if (-not $Python) {
        throw (
            "El instalador vendorizado termino sin crear un Python 3.12 valido " +
            "en $Embedded. Revise instalaciones rotas en el registro de Windows."
        )
    }
}

Write-Host "Python de build: $Python"
& $Python -m venv $BuildVenv
if ($LASTEXITCODE -ne 0) {
    throw "No se pudo crear .venv-build."
}
$BuildPython = Join-Path $BuildVenv 'Scripts\python.exe'

& $BuildPython -m pip install `
    --no-index `
    --find-links $Wheelhouse `
    -r (Join-Path $Root 'requirements-dev.txt')
if ($LASTEXITCODE -ne 0) {
    throw "Fallo la instalacion estrictamente offline."
}

& $BuildPython -m pytest -q
if ($LASTEXITCODE -ne 0) {
    throw "Las pruebas fallaron; no se generara el paquete."
}

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

& $BuildPython -m PyInstaller `
    --noconfirm --clean --onedir --noconsole --name agent `
    @HiddenImports (Join-Path $Root 'agent.py')
if ($LASTEXITCODE -ne 0) {
    throw "Fallo el empaquetado de agent.exe."
}
& $BuildPython -m PyInstaller `
    --noconfirm --clean --onedir --console --name drivemap `
    @HiddenImports (Join-Path $Root 'drivemap.py')
if ($LASTEXITCODE -ne 0) {
    throw "Fallo el empaquetado de drivemap.exe."
}
& $BuildPython -m PyInstaller `
    --noconfirm --clean --onedir --noconsole --name verify_access `
    (Join-Path $Root 'verify_access.py')
if ($LASTEXITCODE -ne 0) {
    throw "Fallo el empaquetado de verify_access.exe."
}

New-Item -ItemType Directory -Path $PackageRoot -Force | Out-Null
foreach ($Bundle in @('agent', 'drivemap')) {
    Copy-Item `
        -LiteralPath (Join-Path $DistRoot $Bundle) `
        -Destination $PackageRoot `
        -Recurse `
        -Force
}
Copy-Item `
    -LiteralPath (Join-Path $DistRoot 'verify_access\verify_access.exe') `
    -Destination (Join-Path $PackageRoot 'agent\verify_access.exe') `
    -Force
foreach ($File in @('install.ps1', 'uninstall.ps1', 'README.md', 'LICENSE')) {
    Copy-Item `
        -LiteralPath (Join-Path $Root $File) `
        -Destination $PackageRoot `
        -Force
}
Copy-Item `
    -LiteralPath (Join-Path $Root 'docs') `
    -Destination $PackageRoot `
    -Recurse `
    -Force

$SelfTestProcess = Start-Process `
    -FilePath (Join-Path $PackageRoot 'agent\agent.exe') `
    -ArgumentList '--self-test' `
    -Wait `
    -PassThru
if ($SelfTestProcess.ExitCode -ne 0) {
    throw "El smoke test congelado de agent.exe fallo."
}
& (Join-Path $PackageRoot 'drivemap\drivemap.exe') --version
if ($LASTEXITCODE -ne 0) {
    throw "drivemap.exe no inicia correctamente."
}

Write-Host ""
Write-Host "Paquete offline listo: $PackageRoot" -ForegroundColor Green
Write-Host "Desde PowerShell como administrador:"
Write-Host "  powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1"
