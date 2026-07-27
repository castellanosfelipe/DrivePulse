[CmdletBinding()]
param(
    [string]$InstallDir = 'C:\Program Files\DriveMapper',
    [string]$DataDir = 'C:\ProgramData\DriveMapper',
    [switch]$NonInteractive
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

function Assert-Administrator {
    $Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $Principal = New-Object Security.Principal.WindowsPrincipal($Identity)
    if (-not $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "DriveMapper requiere elevación. Abra PowerShell con 'Ejecutar como administrador'."
    }
    if (-not [Environment]::Is64BitOperatingSystem) {
        throw "DriveMapper solo admite Windows x64."
    }
}

function Set-DriveMapperAcl {
    param([Parameter(Mandatory=$true)][string]$Path)
    & icacls.exe $Path /inheritance:r /remove:g `
        '*S-1-5-32-545' '*S-1-1-0' '*S-1-5-11' /grant:r `
        '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' /T /C | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "No se pudo aplicar la ACL a $Path." }
}

function New-SystemTaskXml {
    param([string]$AgentPath, [string]$WorkingDirectory)
    $EscapedAgent = [Security.SecurityElement]::Escape($AgentPath)
    $EscapedWorking = [Security.SecurityElement]::Escape($WorkingDirectory)
    return @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Garantiza y repara mapeos SMB en la sesión LocalSystem.</Description>
    <Author>DriveMapper</Author>
  </RegistrationInfo>
  <Triggers>
    <BootTrigger><Enabled>true</Enabled></BootTrigger>
    <EventTrigger>
      <Enabled>true</Enabled>
      <Subscription>&lt;QueryList&gt;&lt;Query Id="0" Path="Microsoft-Windows-NetworkProfile/Operational"&gt;&lt;Select Path="Microsoft-Windows-NetworkProfile/Operational"&gt;*[System[(EventID=10000)]]&lt;/Select&gt;&lt;/Query&gt;&lt;/QueryList&gt;</Subscription>
    </EventTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>S-1-5-18</UserId>
      <LogonType>ServiceAccount</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure><Interval>PT1M</Interval><Count>999</Count></RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>$EscapedAgent</Command>
      <Arguments>--scope system</Arguments>
      <WorkingDirectory>$EscapedWorking</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@
}

Assert-Administrator
$SourceDir = $PSScriptRoot
$SourceFull = [IO.Path]::GetFullPath($SourceDir).TrimEnd('\')
$InstallFull = [IO.Path]::GetFullPath($InstallDir).TrimEnd('\')
$HadConfiguration = Test-Path -LiteralPath (Join-Path $DataDir 'config.json')

New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $DataDir 'data') -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $DataDir 'logs') -Force | Out-Null

if (-not $SourceFull.Equals($InstallFull, [StringComparison]::OrdinalIgnoreCase)) {
    Get-ChildItem -LiteralPath $SourceDir -Force |
        Where-Object { $_.Name -notin @('.git', '.venv-build', '.venv-dev') } |
        ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination $InstallDir -Recurse -Force
        }
}

if (-not $HadConfiguration) {
    $DefaultConfig = @{
        app = 'DriveMapper'
        version = '1.0.0'
        settings = @{
            check_interval_s = 60
            startup_grace_s = 15
            connect_timeout_s = 20
            backoff_initial_s = 5
            backoff_max_s = 300
            log_retention_days = 30
            eventlog_enabled = $true
        }
        drives = @()
    } | ConvertTo-Json -Depth 6
    [IO.File]::WriteAllText(
        (Join-Path $DataDir 'config.json'),
        $DefaultConfig + [Environment]::NewLine,
        (New-Object Text.UTF8Encoding($false))
    )
}

Set-DriveMapperAcl -Path $InstallDir
Set-DriveMapperAcl -Path $DataDir

$AgentExe = Join-Path $InstallDir 'agent\agent.exe'
$CliDir = Join-Path $InstallDir 'drivemap'
$CliExe = Join-Path $CliDir 'drivemap.exe'
if (-not (Test-Path -LiteralPath $AgentExe)) { throw "No se encontró $AgentExe." }
if (-not (Test-Path -LiteralPath $CliExe)) { throw "No se encontró $CliExe." }

$TaskXml = New-SystemTaskXml -AgentPath $AgentExe -WorkingDirectory (Split-Path $AgentExe)
Register-ScheduledTask -TaskName 'DriveMapper-System' -Xml $TaskXml -Force | Out-Null

if (-not [Diagnostics.EventLog]::SourceExists('DriveMapper')) {
    New-EventLog -LogName Application -Source 'DriveMapper'
}

$MachineEnvironment = 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Environment'
$CurrentPath = [string](Get-ItemPropertyValue -Path $MachineEnvironment -Name Path)
$PathParts = @($CurrentPath -split ';' | Where-Object { $_ })
if ($PathParts -notcontains $CliDir) {
    $UpdatedPath = (($PathParts + $CliDir) -join ';')
    Set-ItemProperty -Path $MachineEnvironment -Name Path -Value $UpdatedPath
    [Environment]::SetEnvironmentVariable('Path', $UpdatedPath, 'Machine')
}

Start-ScheduledTask -TaskName 'DriveMapper-System'
$Deadline = (Get-Date).AddSeconds(60)
$StatusJson = $null
do {
    Start-Sleep -Seconds 2
    try {
        $StatusJson = & $CliExe status --json 2>$null
        if ($LASTEXITCODE -eq 0 -and $StatusJson) {
            $Status = $StatusJson | ConvertFrom-Json
            if ($Status.agent_running) { break }
        }
    } catch {}
} while ((Get-Date) -lt $Deadline)

& $CliExe sync-user-tasks
if ($LASTEXITCODE -ne 0) {
    throw "No se pudieron sincronizar las tareas de scope user."
}

Write-Host ""
Write-Host "DriveMapper instalado correctamente." -ForegroundColor Green
Write-Host "Binarios: $InstallDir"
Write-Host "Configuración y estado: $DataDir"
if ($StatusJson) { Write-Host $StatusJson }

if (-not $HadConfiguration) {
    Write-Host ""
    Write-Host "No había configuración previa. Agregue las unidades con:"
    Write-Host "  drivemap add --id minvivienda --letter W: --unc \\192.168.230.245\minvivienda --user workgroup\readuser"
    Write-Host "  drivemap add --id seguridad --letter Z: --unc \\192.168.230.245\seguridad --user workgroup\readuser"
    Write-Host "  drivemap add --id minvdomustemp --letter F: --unc \\192.168.230.245\minvdomustemp --user workgroup\readuser"
    if (-not $NonInteractive) {
        $Answer = Read-Host "¿Desea configurar ahora la primera unidad W:? [s/N]"
        if ($Answer -match '^[sS]') {
            & $CliExe add --id minvivienda --letter W: `
                --unc '\\192.168.230.245\minvivienda' `
                --user 'workgroup\readuser'
            if ($LASTEXITCODE -ne 0) { throw "No se pudo agregar la unidad inicial." }
        }
    }
}
