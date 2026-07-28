[CmdletBinding()]
param(
    [string]$InstallDir = 'C:\Program Files\DriveMapper',
    [string]$DataDir = 'C:\ProgramData\DriveMapper',
    [ValidateRange(30, 300)]
    [int]$StartupTimeoutSeconds = 120,
    [switch]$NonInteractive
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$TaskName = 'DriveMapper-System'
$EventSource = 'DriveMapper'

function Assert-Administrator {
    $Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $Principal = New-Object Security.Principal.WindowsPrincipal($Identity)
    if (-not $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "DriveMapper requiere elevacion. Abra PowerShell como administrador."
    }
    if (-not [Environment]::Is64BitOperatingSystem) {
        throw "DriveMapper solo admite Windows x64."
    }
}

function Resolve-SafeDirectory {
    param(
        [Parameter(Mandatory=$true)][string]$Path,
        [Parameter(Mandatory=$true)][string]$Label
    )
    if (-not [IO.Path]::IsPathRooted($Path)) {
        throw "$Label debe ser una ruta absoluta: $Path"
    }
    $Resolved = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    $Root = [IO.Path]::GetPathRoot($Resolved).TrimEnd('\')
    if (-not $Resolved -or $Resolved.Equals($Root, [StringComparison]::OrdinalIgnoreCase)) {
        throw "$Label no puede ser la raiz de una unidad: $Resolved"
    }
    if ($Resolved.Equals(
        [Environment]::GetFolderPath('Windows').TrimEnd('\'),
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "$Label no puede ser el directorio de Windows."
    }
    return $Resolved
}

function Assert-InstallBundle {
    param([Parameter(Mandatory=$true)][string]$Source)
    $Required = @(
        'agent\agent.exe',
        'agent\verify_access.exe',
        'drivemap\drivemap.exe',
        'uninstall.ps1'
    )
    foreach ($RelativePath in $Required) {
        $Candidate = Join-Path $Source $RelativePath
        if (-not (Test-Path -LiteralPath $Candidate -PathType Leaf)) {
            throw "El paquete esta incompleto. Falta: $Candidate"
        }
    }
}

function Invoke-Icacls {
    param([Parameter(Mandatory=$true)][string[]]$Arguments)
    & icacls.exe @Arguments | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "icacls termino con codigo $LASTEXITCODE."
    }
}

function Invoke-TakeOwnership {
    param([Parameter(Mandatory=$true)][string]$Path)
    & takeown.exe /F $Path /A /R | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "takeown termino con codigo $LASTEXITCODE para '$Path'."
    }
}

function Set-BinaryAcl {
    param([Parameter(Mandatory=$true)][string]$Path)
    Invoke-Icacls @(
        $Path,
        '/inheritance:r'
    )
    Invoke-Icacls @(
        $Path,
        '/remove:g',
        '*S-1-1-0',
        '*S-1-5-11',
        '*S-1-5-32-545'
    )
    Invoke-Icacls @(
        $Path,
        '/grant:r',
        '*S-1-5-18:(OI)(CI)F',
        '*S-1-5-32-544:(OI)(CI)F',
        '*S-1-5-32-545:(OI)(CI)RX'
    )
    if (Get-ChildItem -LiteralPath $Path -Force -ErrorAction SilentlyContinue) {
        Invoke-Icacls @((Join-Path $Path '*'), '/reset', '/T', '/C')
    }
}

function Set-DataAcl {
    param([Parameter(Mandatory=$true)][string]$Path)
    Invoke-TakeOwnership -Path $Path
    Invoke-Icacls @(
        $Path,
        '/grant:r',
        '*S-1-5-18:F',
        '*S-1-5-32-544:F',
        '/T',
        '/C'
    )
    Invoke-Icacls @(
        $Path,
        '/inheritance:r'
    )
    Invoke-Icacls @(
        $Path,
        '/remove:g',
        '*S-1-1-0',
        '*S-1-5-11',
        '*S-1-5-32-545'
    )
    Invoke-Icacls @(
        $Path,
        '/grant:r',
        '*S-1-5-18:(OI)(CI)F',
        '*S-1-5-32-544:(OI)(CI)F'
    )
    if (Get-ChildItem -LiteralPath $Path -Force -ErrorAction SilentlyContinue) {
        Invoke-Icacls @((Join-Path $Path '*'), '/inheritance:e', '/T', '/C')
        Invoke-Icacls @((Join-Path $Path '*'), '/reset', '/T', '/C')
    }
}

function Stop-DriveMapperRuntime {
    param([Parameter(Mandatory=$true)][string]$InstallRoot)
    Get-ScheduledTask -TaskName 'DriveMapper-*' -ErrorAction SilentlyContinue |
        Stop-ScheduledTask -ErrorAction SilentlyContinue

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
            if ($StableEmptyPolls -ge 4) {
                return
            }
        } else {
            $StableEmptyPolls = 0
            $Remaining | ForEach-Object {
                Invoke-CimMethod -InputObject $_ -MethodName Terminate `
                    -ErrorAction SilentlyContinue | Out-Null
            }
        }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $Deadline)

    $ProcessList = ($Remaining | ForEach-Object {
        "$($_.Name) (PID $($_.ProcessId))"
    }) -join ', '
    throw "No se pudieron detener procesos de DriveMapper: $ProcessList"
}

function Remove-DirectoryWithRetry {
    param(
        [Parameter(Mandatory=$true)][string]$Path,
        [Parameter(Mandatory=$true)][string]$InstallRoot
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }
    $LastError = $null
    for ($Attempt = 1; $Attempt -le 12; $Attempt++) {
        try {
            Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
            return
        } catch {
            $LastError = $_
            try {
                Stop-DriveMapperRuntime -InstallRoot $InstallRoot
            } catch {}
            Start-Sleep -Milliseconds (250 * $Attempt)
        }
    }
    throw "No se pudo eliminar '$Path' despues de reintentos: $LastError"
}

function Start-SystemTaskIfNeeded {
    param([Parameter(Mandatory=$true)][string]$Name)
    $Task = Get-ScheduledTask -TaskName $Name -ErrorAction Stop
    if ([string]$Task.State -eq 'Running') {
        return
    }
    try {
        Start-ScheduledTask -TaskName $Name -ErrorAction Stop
    } catch {
        $Current = Get-ScheduledTask -TaskName $Name -ErrorAction Stop
        if ([string]$Current.State -ne 'Running') {
            throw
        }
    }
}

function New-SystemTaskXml {
    param(
        [Parameter(Mandatory=$true)][string]$AgentPath,
        [Parameter(Mandatory=$true)][string]$WorkingDirectory,
        [Parameter(Mandatory=$true)][string]$RuntimeDataDir
    )
    $EscapedAgent = [Security.SecurityElement]::Escape($AgentPath)
    $EscapedWorking = [Security.SecurityElement]::Escape($WorkingDirectory)
    $ConfigPath = [Security.SecurityElement]::Escape(
        (Join-Path $RuntimeDataDir 'config.json')
    )
    $DatabasePath = [Security.SecurityElement]::Escape(
        (Join-Path $RuntimeDataDir 'data\drivemapper.db')
    )
    $EntropyPath = [Security.SecurityElement]::Escape(
        (Join-Path $RuntimeDataDir 'data\.entropy')
    )
    $LogDir = [Security.SecurityElement]::Escape(
        (Join-Path $RuntimeDataDir 'logs')
    )
    $SignalPath = [Security.SecurityElement]::Escape(
        (Join-Path $RuntimeDataDir 'data\.reconcile')
    )
    $HeartbeatPath = [Security.SecurityElement]::Escape(
        (Join-Path $RuntimeDataDir 'data\agent-status.json')
    )
    $Arguments = (
        '--scope system ' +
        "--config-path &quot;$ConfigPath&quot; " +
        "--database-path &quot;$DatabasePath&quot; " +
        "--entropy-path &quot;$EntropyPath&quot; " +
        "--log-dir &quot;$LogDir&quot; " +
        "--signal-path &quot;$SignalPath&quot; " +
        "--heartbeat-path &quot;$HeartbeatPath&quot;"
    )
    return @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.3" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Garantiza y repara mapeos SMB en la sesion LocalSystem.</Description>
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
      <Arguments>$Arguments</Arguments>
      <WorkingDirectory>$EscapedWorking</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@
}

function Add-MachinePath {
    param([Parameter(Mandatory=$true)][string]$CliDirectory)
    $MachineEnvironment = 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Environment'
    $CurrentPath = [string](Get-ItemProperty -Path $MachineEnvironment -Name Path).Path
    $PathParts = @($CurrentPath -split ';' | Where-Object { $_ })
    if (-not ($PathParts | Where-Object {
        $_.TrimEnd('\').Equals(
            $CliDirectory.TrimEnd('\'),
            [StringComparison]::OrdinalIgnoreCase
        )
    })) {
        $UpdatedPath = (($PathParts + $CliDirectory) -join ';')
        Set-ItemProperty -Path $MachineEnvironment -Name Path -Value $UpdatedPath
        [Environment]::SetEnvironmentVariable('Path', $UpdatedPath, 'Machine')
    }
}

function Invoke-InstalledCli {
    param(
        [Parameter(Mandatory=$true)][string]$CliPath,
        [Parameter(Mandatory=$true)][string]$RuntimeInstallDir,
        [Parameter(Mandatory=$true)][string]$RuntimeDataDir,
        [Parameter(Mandatory=$true)][string[]]$Arguments
    )
    $PreviousInstallEnvironment = $env:DRIVEMAPPER_INSTALL_DIR
    $PreviousDataEnvironment = $env:DRIVEMAPPER_DATA_DIR
    try {
        $env:DRIVEMAPPER_INSTALL_DIR = $RuntimeInstallDir
        $env:DRIVEMAPPER_DATA_DIR = $RuntimeDataDir
        $Output = & $CliPath @Arguments
        $ExitCode = $LASTEXITCODE
        return [pscustomobject]@{
            ExitCode = $ExitCode
            Output = @($Output)
        }
    } finally {
        $env:DRIVEMAPPER_INSTALL_DIR = $PreviousInstallEnvironment
        $env:DRIVEMAPPER_DATA_DIR = $PreviousDataEnvironment
    }
}

Assert-Administrator

$SourceDir = [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')
$InstallFull = Resolve-SafeDirectory -Path $InstallDir -Label 'InstallDir'
$DataFull = Resolve-SafeDirectory -Path $DataDir -Label 'DataDir'
$InstallParent = Split-Path -Parent $InstallFull
$StageDir = Join-Path $InstallParent (
    '.DriveMapper.staging.{0}.{1}' -f $PID, [Guid]::NewGuid().ToString('N')
)
$BackupDir = Join-Path $InstallParent (
    '.DriveMapper.previous.{0}' -f [Guid]::NewGuid().ToString('N')
)
$HadConfiguration = Test-Path -LiteralPath (Join-Path $DataFull 'config.json')
$HadExistingInstall = Test-Path -LiteralPath $InstallFull
$Committed = $false
$PreviousTaskXml = $null
$PreflightComplete = $false

try {
    Assert-InstallBundle -Source $SourceDir
    New-Item -ItemType Directory -Path $InstallParent -Force | Out-Null
    New-Item -ItemType Directory -Path $StageDir -Force | Out-Null

    $BundleItems = @(
        'agent',
        'drivemap',
        'docs',
        'DrivePulse-Setup.ps1',
        'Instalar DrivePulse.cmd',
        'install.ps1',
        'uninstall.ps1',
        'README.md',
        'LICENSE'
    )
    foreach ($Item in $BundleItems) {
        $Candidate = Join-Path $SourceDir $Item
        if (Test-Path -LiteralPath $Candidate) {
            Copy-Item -LiteralPath $Candidate -Destination $StageDir -Recurse -Force
        }
    }

    Get-ChildItem -LiteralPath $StageDir -Recurse -File |
        Unblock-File -ErrorAction SilentlyContinue

    $StageAgent = Join-Path $StageDir 'agent\agent.exe'
    $StageCli = Join-Path $StageDir 'drivemap\drivemap.exe'
    $SelfTestProcess = Start-Process `
        -FilePath $StageAgent `
        -ArgumentList '--self-test' `
        -Wait `
        -PassThru
    if ($SelfTestProcess.ExitCode -ne 0) {
        throw "agent.exe no supero el self-test previo a la instalacion."
    }
    & $StageCli --version
    if ($LASTEXITCODE -ne 0) {
        throw "drivemap.exe no inicia antes de la instalacion."
    }

    New-Item -ItemType Directory -Path (Join-Path $DataFull 'data') -Force |
        Out-Null
    New-Item -ItemType Directory -Path (Join-Path $DataFull 'logs') -Force |
        Out-Null
    if (-not $HadConfiguration) {
        $DefaultConfig = @{
            app = 'DriveMapper'
            version = '1.1.3'
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
            (Join-Path $DataFull 'config.json'),
            $DefaultConfig + [Environment]::NewLine,
            (New-Object Text.UTF8Encoding($false))
        )
    }
    Set-DataAcl -Path $DataFull
    $PreflightComplete = $true
} finally {
    if (-not $PreflightComplete -and (Test-Path -LiteralPath $StageDir)) {
        Remove-DirectoryWithRetry -Path $StageDir -InstallRoot $StageDir
    }
}

try {
    $PreviousTask = Get-ScheduledTask -TaskName $TaskName `
        -ErrorAction SilentlyContinue
    if ($PreviousTask) {
        $PreviousTaskXml = Export-ScheduledTask -TaskName $TaskName
    }
    Stop-DriveMapperRuntime -InstallRoot $InstallFull
    Remove-Item -LiteralPath (Join-Path $DataFull 'data\agent-status.json') `
        -Force -ErrorAction SilentlyContinue

    $CurrentLocation = [IO.Path]::GetFullPath((Get-Location).Path).TrimEnd('\')
    if ($CurrentLocation.Equals($InstallFull, [StringComparison]::OrdinalIgnoreCase) -or
        $CurrentLocation.StartsWith(
            $InstallFull + '\',
            [StringComparison]::OrdinalIgnoreCase
        )) {
        Set-Location -LiteralPath ([Environment]::GetFolderPath('Windows'))
    }

    if ($HadExistingInstall) {
        Move-Item -LiteralPath $InstallFull -Destination $BackupDir
    }
    Move-Item -LiteralPath $StageDir -Destination $InstallFull
    $StageDir = ''
    Set-BinaryAcl -Path $InstallFull

    $AgentExe = Join-Path $InstallFull 'agent\agent.exe'
    $CliDir = Join-Path $InstallFull 'drivemap'
    $CliExe = Join-Path $CliDir 'drivemap.exe'
    $AclResult = Invoke-InstalledCli `
        -CliPath $CliExe `
        -RuntimeInstallDir $InstallFull `
        -RuntimeDataDir $DataFull `
        -Arguments @('verify-acl')
    if ($AclResult.ExitCode -ne 0) {
        throw "La ACL protegida no supero la prueba de escritura y lectura."
    }
    $TaskXml = New-SystemTaskXml `
        -AgentPath $AgentExe `
        -WorkingDirectory (Split-Path $AgentExe) `
        -RuntimeDataDir $DataFull
    Register-ScheduledTask -TaskName $TaskName -Xml $TaskXml -Force | Out-Null

    if (-not [Diagnostics.EventLog]::SourceExists($EventSource)) {
        New-EventLog -LogName Application -Source $EventSource
    }
    Add-MachinePath -CliDirectory $CliDir

    $SyncResult = Invoke-InstalledCli `
        -CliPath $CliExe `
        -RuntimeInstallDir $InstallFull `
        -RuntimeDataDir $DataFull `
        -Arguments @('sync-user-tasks')
    if ($SyncResult.ExitCode -ne 0) {
        throw "No se pudieron sincronizar las tareas de scope user: $($SyncResult.Output -join ' ')"
    }

    Start-SystemTaskIfNeeded -Name $TaskName
    $Deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
    $StatusJson = $null
    $AgentHealthy = $false
    do {
        Start-Sleep -Seconds 2
        try {
            $StatusResult = Invoke-InstalledCli `
                -CliPath $CliExe `
                -RuntimeInstallDir $InstallFull `
                -RuntimeDataDir $DataFull `
                -Arguments @('status', '--json')
            if ($StatusResult.ExitCode -eq 0 -and $StatusResult.Output.Count -gt 0) {
                $StatusJson = $StatusResult.Output -join [Environment]::NewLine
                $Status = $StatusJson | ConvertFrom-Json
                if ($Status.agent_running) {
                    $AgentHealthy = $true
                    break
                }
            }
        } catch {}
        $Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
        if ([string]$Task.State -notin @('Running', 'Ready')) {
            throw "La tarea $TaskName quedo en estado $($Task.State)."
        }
    } while ((Get-Date) -lt $Deadline)

    if (-not $AgentHealthy) {
        $TaskInfo = Get-ScheduledTaskInfo -TaskName $TaskName
        throw (
            "El agente no publico un heartbeat sano en $StartupTimeoutSeconds segundos. " +
            "LastTaskResult=$($TaskInfo.LastTaskResult)."
        )
    }

    $Committed = $true
    if ($HadExistingInstall -and (Test-Path -LiteralPath $BackupDir)) {
        try {
            Remove-DirectoryWithRetry `
                -Path $BackupDir `
                -InstallRoot $BackupDir
        } catch {
            Write-Warning "No se pudo eliminar el respaldo anterior: $BackupDir"
        }
    }

    Write-Host ""
    Write-Host "DriveMapper instalado correctamente." -ForegroundColor Green
    Write-Host "Binarios: $InstallFull"
    Write-Host "Configuracion y estado: $DataFull"
    Write-Host $StatusJson

    if (-not $HadConfiguration) {
        Write-Host ""
        Write-Host "Agregue las unidades con drivemap add; la clave se solicita oculta."
        if (-not $NonInteractive) {
            Write-Host "Ejemplo:"
            Write-Host "  drivemap add --id minvivienda --letter W: --unc \\192.168.230.245\minvivienda --user workgroup\readuser --scope system"
        }
    }
} catch {
    $InstallFailure = $_
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false `
        -ErrorAction SilentlyContinue
    try {
        Stop-DriveMapperRuntime -InstallRoot $InstallFull
    } catch {
        Write-Warning "No se pudieron detener todos los procesos durante rollback."
    }

    if (-not $Committed -and (Test-Path -LiteralPath $InstallFull)) {
        try {
            Remove-DirectoryWithRetry `
                -Path $InstallFull `
                -InstallRoot $InstallFull
        } catch {
            Write-Warning "No se pudo retirar la instalacion fallida: $_"
        }
    }
    if (-not $Committed -and $HadExistingInstall -and
        (Test-Path -LiteralPath $BackupDir)) {
        if (Test-Path -LiteralPath $InstallFull) {
            throw (
                "Rollback incompleto; el respaldo permanece en '$BackupDir'. " +
                "Error original: $InstallFailure"
            )
        }
        Move-Item -LiteralPath $BackupDir -Destination $InstallFull
    }
    if (-not $Committed -and $PreviousTaskXml) {
        try {
            Register-ScheduledTask `
                -TaskName $TaskName `
                -Xml $PreviousTaskXml `
                -Force | Out-Null
            Start-SystemTaskIfNeeded -Name $TaskName
        } catch {}
    }
    throw $InstallFailure
} finally {
    if ($StageDir -and (Test-Path -LiteralPath $StageDir)) {
        Remove-DirectoryWithRetry -Path $StageDir -InstallRoot $StageDir
    }
}
