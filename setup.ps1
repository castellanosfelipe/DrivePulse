[CmdletBinding()]
param(
    [string]$PackagePath,
    [switch]$NonInteractive
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

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
    $Arguments = @(
        '-NoProfile',
        '-ExecutionPolicy',
        'Bypass',
        '-File',
        $Installers[0].FullName
    )
    if ($NonInteractive) {
        $Arguments += '-NonInteractive'
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
