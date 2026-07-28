[CmdletBinding()]
param(
    [string]$Version = 'v1.1.2',
    [string]$OutputDirectory
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $PSScriptRoot 'dist\release'
}

$PackageRoot = Join-Path $PSScriptRoot 'dist\DriveMapper'
if (-not (Test-Path -LiteralPath $PackageRoot -PathType Container)) {
    throw "Falta dist\DriveMapper. Ejecute .\build.ps1 primero."
}

$OutputFull = [IO.Path]::GetFullPath($OutputDirectory)
$RepositoryRoot = [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\') + '\'
if (-not ($OutputFull.TrimEnd('\') + '\').StartsWith(
    $RepositoryRoot,
    [StringComparison]::OrdinalIgnoreCase
)) {
    throw "OutputDirectory debe estar dentro del repositorio."
}

New-Item -ItemType Directory -Path $OutputFull -Force | Out-Null
$ArchiveName = "DrivePulse-$Version-win64.zip"
$ChecksumName = "DrivePulse-$Version-win64.sha256"
$SetupName = "DrivePulse-$Version-Setup.exe"
$ArchivePath = Join-Path $OutputFull $ArchiveName
$ChecksumPath = Join-Path $OutputFull $ChecksumName
$SetupPath = Join-Path $OutputFull $SetupName

foreach ($Target in @($ArchivePath, $ChecksumPath, $SetupPath)) {
    if (Test-Path -LiteralPath $Target -PathType Leaf) {
        Remove-Item -LiteralPath $Target -Force
    }
}

Compress-Archive -Path (Join-Path $PackageRoot '*') `
    -DestinationPath $ArchivePath -CompressionLevel Optimal
$Hash = (Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256).Hash
[IO.File]::WriteAllText(
    $ChecksumPath,
    "$Hash  $ArchiveName`r`n",
    [Text.Encoding]::ASCII
)

$Stage = Join-Path ([IO.Path]::GetTempPath()) 'DrivePulse-IExpress'
if (Test-Path -LiteralPath $Stage) {
    Remove-Item -LiteralPath $Stage -Recurse -Force
}
$SourceStage = Join-Path $Stage 'source'
$BuildStage = Join-Path $Stage 'output'
New-Item -ItemType Directory -Path $SourceStage -Force | Out-Null
New-Item -ItemType Directory -Path $BuildStage -Force | Out-Null
Copy-Item -LiteralPath $ArchivePath -Destination $SourceStage
Copy-Item -LiteralPath $ChecksumPath -Destination $SourceStage
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'setup.ps1') `
    -Destination $SourceStage
$StagedSetup = Join-Path $SourceStage 'setup.ps1'
$SetupContent = [IO.File]::ReadAllText(
    $StagedSetup,
    [Text.Encoding]::UTF8
)
[IO.File]::WriteAllText(
    $StagedSetup,
    $SetupContent,
    (New-Object Text.UTF8Encoding($true))
)

$Launcher = @'
@echo off
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
exit /b %errorlevel%
'@
[IO.File]::WriteAllText(
    (Join-Path $SourceStage 'launch.cmd'),
    $Launcher,
    [Text.Encoding]::ASCII
)

$StageWithSlash = [IO.Path]::GetFullPath($SourceStage).TrimEnd('\') + '\'
$IExpressTarget = Join-Path $BuildStage $SetupName
$SedPath = Join-Path $BuildStage 'DrivePulse.sed'
$Sed = @"
[Version]
Class=IEXPRESS
SEDVersion=3

[Options]
PackagePurpose=InstallApp
ShowInstallProgramWindow=0
HideExtractAnimation=1
UseLongFileName=1
InsideCompressed=0
CAB_FixedSize=0
CAB_ResvCodeSigning=0
RebootMode=N
InstallPrompt=
DisplayLicense=
FinishMessage=
TargetName=$IExpressTarget
FriendlyName=DrivePulse $Version
AppLaunched=launch.cmd
PostInstallCmd=<None>
AdminQuietInstCmd=
UserQuietInstCmd=
SourceFiles=SourceFiles

[Strings]
FILE0="$ArchiveName"
FILE1="$ChecksumName"
FILE2="setup.ps1"
FILE3="launch.cmd"

[SourceFiles]
SourceFiles0=$StageWithSlash

[SourceFiles0]
%FILE0%=
%FILE1%=
%FILE2%=
%FILE3%=
"@
[IO.File]::WriteAllText($SedPath, $Sed, [Text.Encoding]::ASCII)

$IExpress = Join-Path $env:SystemRoot 'System32\iexpress.exe'
if (-not (Test-Path -LiteralPath $IExpress -PathType Leaf)) {
    throw "Windows no incluye iexpress.exe; no se puede crear el instalador único."
}
& $IExpress /N /Q $SedPath
$Deadline = (Get-Date).AddMinutes(3)
do {
    if (Test-Path -LiteralPath $IExpressTarget -PathType Leaf) {
        break
    }
    Start-Sleep -Milliseconds 500
} while ((Get-Date) -lt $Deadline)
if (-not (Test-Path -LiteralPath $IExpressTarget -PathType Leaf)) {
    throw "IExpress no pudo crear el instalador de doble clic."
}
$ProcessDeadline = (Get-Date).AddMinutes(2)
do {
    $ActivePackaging = @(
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object {
                $_.Name -in @('iexpress.exe', 'makecab.exe') -and
                $_.CommandLine -like '*DrivePulse-IExpress*'
            }
    )
    if ($ActivePackaging.Count -eq 0) {
        break
    }
    Start-Sleep -Milliseconds 500
} while ((Get-Date) -lt $ProcessDeadline)

$Ready = $false
for ($Attempt = 1; $Attempt -le 60; $Attempt++) {
    try {
        $Handle = [IO.File]::Open(
            $IExpressTarget,
            [IO.FileMode]::Open,
            [IO.FileAccess]::Read,
            [IO.FileShare]::None
        )
        $Handle.Dispose()
        $Ready = $true
        break
    } catch {
        Start-Sleep -Milliseconds 500
    }
}
if (-not $Ready) {
    throw "IExpress no liberó el instalador terminado."
}
$Copied = $false
for ($Attempt = 1; $Attempt -le 20; $Attempt++) {
    try {
        Copy-Item -LiteralPath $IExpressTarget -Destination $SetupPath `
            -Force -ErrorAction Stop
        $Copied = $true
        break
    } catch {
        Start-Sleep -Milliseconds 500
    }
}
if (-not $Copied) {
    throw "No se pudo copiar el instalador terminado a $SetupPath."
}
for ($Attempt = 1; $Attempt -le 20; $Attempt++) {
    try {
        Remove-Item -LiteralPath $Stage -Recurse -Force -ErrorAction Stop
        break
    } catch {
        if ($Attempt -eq 20) {
            Write-Warning "No se pudo limpiar el temporal de IExpress: $Stage"
        } else {
            Start-Sleep -Milliseconds 500
        }
    }
}

Write-Host ""
Write-Host "Instalador de doble clic listo: $SetupPath" -ForegroundColor Green
Write-Host "SHA-256: $((Get-FileHash -LiteralPath $SetupPath -Algorithm SHA256).Hash)"
