[CmdletBinding()]
param(
    [string]$PackagePath,
    [switch]$NonInteractive,
    [string]$TargetUser,
    [switch]$Elevated
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

function Test-Administrator {
    $Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $Principal = New-Object Security.Principal.WindowsPrincipal($Identity)
    return $Principal.IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator
    )
}

function Quote-ProcessArgument {
    param([Parameter(Mandatory=$true)][string]$Value)
    return '"' + $Value.Replace('"', '\"') + '"'
}

if (-not $TargetUser) {
    $TargetUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
}

if (-not (Test-Administrator)) {
    $PowerShell = Join-Path $env:SystemRoot (
        'System32\WindowsPowerShell\v1.0\powershell.exe'
    )
    $Arguments = @(
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-File', (Quote-ProcessArgument $PSCommandPath),
        '-TargetUser', (Quote-ProcessArgument $TargetUser),
        '-Elevated'
    )
    if ($PackagePath) {
        $Arguments += @('-PackagePath', (Quote-ProcessArgument $PackagePath))
    }
    if ($NonInteractive) {
        $Arguments += '-NonInteractive'
    }
    $Process = Start-Process -FilePath $PowerShell -Verb RunAs `
        -ArgumentList ($Arguments -join ' ') -Wait -PassThru
    exit $Process.ExitCode
}

function Resolve-ReleasePackage {
    param([string]$RequestedPath)
    if ($RequestedPath) {
        $Resolved = (Resolve-Path -LiteralPath $RequestedPath -ErrorAction Stop).Path
        if (-not $Resolved.EndsWith('.zip', [StringComparison]::OrdinalIgnoreCase)) {
            throw "PackagePath debe apuntar al ZIP win64 publicado."
        }
        return $Resolved
    }

    $Candidates = @(
        Get-ChildItem -LiteralPath $PSScriptRoot -File |
            Where-Object { $_.Name -like 'DrivePulse-*-win64.zip' }
    )
    if ($Candidates.Count -ne 1) {
        throw (
            "Coloque este instalador junto a un unico archivo " +
            "DrivePulse-*-win64.zip o use -PackagePath."
        )
    }
    return $Candidates[0].FullName
}

function Confirm-PackageChecksum {
    param([Parameter(Mandatory=$true)][string]$ArchivePath)
    $ChecksumPath = [IO.Path]::ChangeExtension($ArchivePath, '.sha256')
    if (-not (Test-Path -LiteralPath $ChecksumPath -PathType Leaf)) {
        throw "Falta el checksum requerido: $ChecksumPath"
    }
    $ChecksumText = [IO.File]::ReadAllText($ChecksumPath).Trim()
    if ($ChecksumText -notmatch '^(?<hash>[A-Fa-f0-9]{64})(\s+.+)?$') {
        throw "El archivo SHA-256 tiene un formato invalido: $ChecksumPath"
    }
    $Expected = $Matches['hash'].ToUpperInvariant()
    $Actual = (Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256).Hash
    if (-not $Actual.Equals($Expected, [StringComparison]::OrdinalIgnoreCase)) {
        throw "El ZIP no coincide con su SHA-256. No se ejecutara."
    }
}

$Archive = Resolve-ReleasePackage -RequestedPath $PackagePath
Confirm-PackageChecksum -ArchivePath $Archive

$ExtractionRoot = Join-Path ([IO.Path]::GetTempPath()) (
    'DrivePulse-Setup-{0}' -f [Guid]::NewGuid().ToString('N')
)
New-Item -ItemType Directory -Path $ExtractionRoot -Force | Out-Null

try {
    Expand-Archive -LiteralPath $Archive -DestinationPath $ExtractionRoot -Force
    $Installers = @(
        Get-ChildItem -LiteralPath $ExtractionRoot -Filter 'install.ps1' `
            -File -Recurse
    )
    if ($Installers.Count -ne 1) {
        throw "El ZIP no contiene exactamente un install.ps1."
    }
    $Script = $Installers[0].FullName
    $Arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File')
    if (-not $NonInteractive) {
        $Wizard = Join-Path $Installers[0].DirectoryName 'DrivePulse-Setup.ps1'
        if (-not (Test-Path -LiteralPath $Wizard -PathType Leaf)) {
            throw "El ZIP no contiene el asistente gráfico de DrivePulse."
        }
        $Script = $Wizard
    }
    $Arguments += $Script
    if ($NonInteractive) {
        $Arguments += '-NonInteractive'
    } else {
        $Arguments += @('-TargetUser', $TargetUser, '-Elevated')
    }
    & powershell.exe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "La instalacion termino con codigo $LASTEXITCODE."
    }
} finally {
    if (Test-Path -LiteralPath $ExtractionRoot) {
        Remove-Item -LiteralPath $ExtractionRoot -Recurse -Force
    }
}
