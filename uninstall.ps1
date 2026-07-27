[CmdletBinding()]
param(
    [string]$InstallDir = 'C:\Program Files\DriveMapper',
    [string]$DataDir = 'C:\ProgramData\DriveMapper',
    [switch]$RemoveMappings,
    [switch]$Purge
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

function Resolve-SafeRemovalDirectory {
    param(
        [Parameter(Mandatory=$true)][string]$Path,
        [Parameter(Mandatory=$true)][string]$Label
    )
    if (-not [IO.Path]::IsPathRooted($Path)) {
        throw "$Label debe ser una ruta absoluta."
    }
    $Resolved = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    $Forbidden = @(
        [IO.Path]::GetPathRoot($Resolved).TrimEnd('\'),
        [Environment]::GetFolderPath('Windows').TrimEnd('\'),
        [Environment]::GetFolderPath('ProgramFiles').TrimEnd('\'),
        [Environment]::GetFolderPath('CommonApplicationData').TrimEnd('\')
    )
    if ($Forbidden | Where-Object {
        $_ -and $_.Equals($Resolved, [StringComparison]::OrdinalIgnoreCase)
    }) {
        throw "Se rechazo una ruta demasiado amplia para $Label`: $Resolved"
    }
    return $Resolved
}

function Stop-InstalledProcesses {
    param([Parameter(Mandatory=$true)][string]$InstallRoot)
    $Prefix = $InstallRoot.TrimEnd('\') + '\'
    $Deadline = (Get-Date).AddSeconds(15)
    $StableEmptyPolls = 0
    do {
        $Remaining = @(
            Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
                Where-Object {
                    $_.ExecutablePath -and
                    $_.ExecutablePath.StartsWith(
                        $Prefix,
                        [StringComparison]::OrdinalIgnoreCase
                    )
                }
        )
        if ($Remaining.Count -eq 0) {
            $StableEmptyPolls++
            if ($StableEmptyPolls -ge 4) { return }
        } else {
            $StableEmptyPolls = 0
            $Remaining | ForEach-Object {
                Invoke-CimMethod -InputObject $_ -MethodName Terminate `
                    -ErrorAction SilentlyContinue | Out-Null
            }
        }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $Deadline)
    throw "No se pudieron detener todos los procesos de DriveMapper."
}

function Remove-DirectoryWithRetry {
    param(
        [Parameter(Mandatory=$true)][string]$Path,
        [Parameter(Mandatory=$true)][string]$InstallRoot
    )
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $LastError = $null
    for ($Attempt = 1; $Attempt -le 12; $Attempt++) {
        try {
            Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
            return
        } catch {
            $LastError = $_
            try {
                Stop-InstalledProcesses -InstallRoot $InstallRoot
            } catch {}
            Start-Sleep -Milliseconds (250 * $Attempt)
        }
    }
    throw "No se pudo eliminar '$Path' despues de reintentos: $LastError"
}

$Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$Principal = New-Object Security.Principal.WindowsPrincipal($Identity)
if (-not $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "La desinstalacion requiere PowerShell como administrador."
}

$ResolvedInstall = Resolve-SafeRemovalDirectory `
    -Path $InstallDir -Label 'InstallDir'
$ResolvedData = Resolve-SafeRemovalDirectory -Path $DataDir -Label 'DataDir'

if ($RemoveMappings) {
    $AgentExe = Join-Path $ResolvedInstall 'agent\agent.exe'
    if (Test-Path -LiteralPath $AgentExe) {
        $Action = New-ScheduledTaskAction `
            -Execute $AgentExe `
            -Argument (
                '--remove-managed --scope system ' +
                '--database-path "' +
                (Join-Path $ResolvedData 'data\drivemapper.db') +
                '"'
            )
        $PrincipalSystem = New-ScheduledTaskPrincipal `
            -UserId 'NT AUTHORITY\SYSTEM' `
            -LogonType ServiceAccount `
            -RunLevel Highest
        $Settings = New-ScheduledTaskSettingsSet `
            -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
        Register-ScheduledTask `
            -TaskName 'DriveMapper-RemoveMappings' `
            -Action $Action `
            -Principal $PrincipalSystem `
            -Settings $Settings `
            -Force | Out-Null
        Start-ScheduledTask -TaskName 'DriveMapper-RemoveMappings'
        $Deadline = (Get-Date).AddMinutes(2)
        do {
            Start-Sleep -Seconds 1
            $State = (
                Get-ScheduledTask -TaskName 'DriveMapper-RemoveMappings'
            ).State
        } while ($State -eq 'Running' -and (Get-Date) -lt $Deadline)
        Unregister-ScheduledTask `
            -TaskName 'DriveMapper-RemoveMappings' `
            -Confirm:$false
    }
}

Get-ScheduledTask -TaskName 'DriveMapper-*' -ErrorAction SilentlyContinue |
    Stop-ScheduledTask -ErrorAction SilentlyContinue
Get-ScheduledTask -TaskName 'DriveMapper-*' -ErrorAction SilentlyContinue |
    Unregister-ScheduledTask -Confirm:$false

Stop-InstalledProcesses -InstallRoot $ResolvedInstall

if ([Diagnostics.EventLog]::SourceExists('DriveMapper')) {
    Remove-EventLog -Source 'DriveMapper'
}

$CliDir = Join-Path $ResolvedInstall 'drivemap'
$MachineEnvironment = 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Environment'
$CurrentPath = [string](Get-ItemProperty -Path $MachineEnvironment -Name Path).Path
$UpdatedPath = (@(
    $CurrentPath -split ';' |
        Where-Object {
            $_ -and -not $_.TrimEnd('\').Equals(
                $CliDir.TrimEnd('\'),
                [StringComparison]::OrdinalIgnoreCase
            )
        }
) -join ';')
Set-ItemProperty -Path $MachineEnvironment -Name Path -Value $UpdatedPath
[Environment]::SetEnvironmentVariable('Path', $UpdatedPath, 'Machine')

if (Test-Path -LiteralPath $ResolvedInstall) {
    $CurrentLocation = [IO.Path]::GetFullPath((Get-Location).Path).TrimEnd('\')
    if ($CurrentLocation.Equals(
        $ResolvedInstall,
        [StringComparison]::OrdinalIgnoreCase
    ) -or $CurrentLocation.StartsWith(
        $ResolvedInstall.TrimEnd('\') + '\',
        [StringComparison]::OrdinalIgnoreCase
    )) {
        Set-Location -LiteralPath ([Environment]::GetFolderPath('Windows'))
    }
    Remove-DirectoryWithRetry `
        -Path $ResolvedInstall `
        -InstallRoot $ResolvedInstall
}

if ($Purge -and (Test-Path -LiteralPath $ResolvedData)) {
    Remove-Item -LiteralPath $ResolvedData -Recurse -Force
    Write-Host "Datos eliminados permanentemente: $ResolvedData"
} elseif (Test-Path -LiteralPath $ResolvedData) {
    Write-Host "Configuracion e historial conservados en $ResolvedData."
}

Write-Host "DriveMapper desinstalado." -ForegroundColor Green
