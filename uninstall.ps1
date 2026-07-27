[CmdletBinding()]
param(
    [string]$InstallDir = 'C:\Program Files\DriveMapper',
    [string]$DataDir = 'C:\ProgramData\DriveMapper',
    [switch]$RemoveMappings,
    [switch]$Purge
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$Principal = New-Object Security.Principal.WindowsPrincipal($Identity)
if (-not $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "La desinstalación requiere 'Ejecutar como administrador'."
}

if ($RemoveMappings) {
    $AgentExe = Join-Path $InstallDir 'agent\agent.exe'
    if (Test-Path -LiteralPath $AgentExe) {
        $Action = New-ScheduledTaskAction -Execute $AgentExe -Argument '--remove-managed --scope system'
        $PrincipalSystem = New-ScheduledTaskPrincipal -UserId 'NT AUTHORITY\SYSTEM' `
            -LogonType ServiceAccount -RunLevel Highest
        $Settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
        Register-ScheduledTask -TaskName 'DriveMapper-RemoveMappings' -Action $Action `
            -Principal $PrincipalSystem -Settings $Settings -Force | Out-Null
        Start-ScheduledTask -TaskName 'DriveMapper-RemoveMappings'
        $Deadline = (Get-Date).AddMinutes(2)
        do {
            Start-Sleep -Seconds 1
            $State = (Get-ScheduledTask -TaskName 'DriveMapper-RemoveMappings').State
        } while ($State -eq 'Running' -and (Get-Date) -lt $Deadline)
        Unregister-ScheduledTask -TaskName 'DriveMapper-RemoveMappings' -Confirm:$false
    }
}

Get-ScheduledTask -TaskName 'DriveMapper-*' -ErrorAction SilentlyContinue |
    Stop-ScheduledTask -ErrorAction SilentlyContinue
Get-ScheduledTask -TaskName 'DriveMapper-*' -ErrorAction SilentlyContinue |
    Unregister-ScheduledTask -Confirm:$false

Get-CimInstance Win32_Process |
    Where-Object {
        $_.ExecutablePath -and
        $_.ExecutablePath.StartsWith($InstallDir, [StringComparison]::OrdinalIgnoreCase)
    } |
    ForEach-Object { Invoke-CimMethod -InputObject $_ -MethodName Terminate | Out-Null }

if ([Diagnostics.EventLog]::SourceExists('DriveMapper')) {
    Remove-EventLog -Source 'DriveMapper'
}

$CliDir = Join-Path $InstallDir 'drivemap'
$MachineEnvironment = 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Environment'
$CurrentPath = [string](Get-ItemPropertyValue -Path $MachineEnvironment -Name Path)
$UpdatedPath = (@(
    $CurrentPath -split ';' |
        Where-Object { $_ -and -not $_.Equals($CliDir, [StringComparison]::OrdinalIgnoreCase) }
) -join ';')
Set-ItemProperty -Path $MachineEnvironment -Name Path -Value $UpdatedPath
[Environment]::SetEnvironmentVariable('Path', $UpdatedPath, 'Machine')

if (Test-Path -LiteralPath $InstallDir) {
    $ResolvedInstall = [IO.Path]::GetFullPath($InstallDir)
    if (-not $ResolvedInstall.StartsWith('C:\Program Files\DriveMapper', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Se rechazó eliminar una ruta de instalación inesperada: $ResolvedInstall"
    }
    Remove-Item -LiteralPath $ResolvedInstall -Recurse -Force
}

if ($Purge -and (Test-Path -LiteralPath $DataDir)) {
    $ResolvedData = [IO.Path]::GetFullPath($DataDir)
    if (-not $ResolvedData.StartsWith('C:\ProgramData\DriveMapper', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Se rechazó purgar una ruta de datos inesperada: $ResolvedData"
    }
    Remove-Item -LiteralPath $ResolvedData -Recurse -Force
    Write-Host "Datos eliminados permanentemente: $ResolvedData"
} elseif (Test-Path -LiteralPath $DataDir) {
    Write-Host "Configuración e historial conservados en $DataDir."
}

Write-Host "DriveMapper desinstalado." -ForegroundColor Green

