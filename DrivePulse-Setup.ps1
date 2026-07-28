[CmdletBinding()]
param(
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
        '-WindowStyle', 'Hidden',
        '-File', (Quote-ProcessArgument $PSCommandPath),
        '-TargetUser', (Quote-ProcessArgument $TargetUser),
        '-Elevated'
    ) -join ' '
    try {
        $Process = Start-Process -FilePath $PowerShell -Verb RunAs `
            -ArgumentList $Arguments -Wait -PassThru
        exit $Process.ExitCode
    } catch {
        Add-Type -AssemblyName System.Windows.Forms
        [Windows.Forms.MessageBox]::Show(
            "La instalación necesita autorización de administrador.",
            "DrivePulse",
            [Windows.Forms.MessageBoxButtons]::OK,
            [Windows.Forms.MessageBoxIcon]::Warning
        ) | Out-Null
        exit 1
    }
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()

function Show-Error {
    param([Parameter(Mandatory=$true)][string]$Message)
    [Windows.Forms.MessageBox]::Show(
        $Message,
        "DrivePulse",
        [Windows.Forms.MessageBoxButtons]::OK,
        [Windows.Forms.MessageBoxIcon]::Error
    ) | Out-Null
}

function Invoke-Provision {
    param(
        [Parameter(Mandatory=$true)][string]$Executable,
        [Parameter(Mandatory=$true)][string]$Payload
    )
    $StartInfo = New-Object Diagnostics.ProcessStartInfo
    $StartInfo.FileName = $Executable
    $StartInfo.Arguments = 'provision'
    $StartInfo.UseShellExecute = $false
    $StartInfo.CreateNoWindow = $true
    $StartInfo.RedirectStandardInput = $true
    $StartInfo.RedirectStandardOutput = $true
    $StartInfo.RedirectStandardError = $true
    $StartInfo.StandardOutputEncoding = [Text.Encoding]::UTF8
    $StartInfo.StandardErrorEncoding = [Text.Encoding]::UTF8

    $Process = New-Object Diagnostics.Process
    $Process.StartInfo = $StartInfo
    if (-not $Process.Start()) {
        throw "No se pudo iniciar el configurador de DrivePulse."
    }
    $Process.StandardInput.Write($Payload)
    $Process.StandardInput.Close()
    $Output = $Process.StandardOutput.ReadToEnd()
    $ErrorOutput = $Process.StandardError.ReadToEnd()
    $Process.WaitForExit()
    if ($Process.ExitCode -ne 0) {
        throw (($ErrorOutput + [Environment]::NewLine + $Output).Trim())
    }
    return $Output.Trim()
}

$Form = New-Object Windows.Forms.Form
$Form.Text = 'Instalar DrivePulse'
$Form.StartPosition = 'CenterScreen'
$Form.ClientSize = New-Object Drawing.Size(1010, 505)
$Form.FormBorderStyle = 'FixedDialog'
$Form.MaximizeBox = $false
$Form.MinimizeBox = $false
$Form.Font = New-Object Drawing.Font('Segoe UI', 9)

$Title = New-Object Windows.Forms.Label
$Title.Text = 'Unidades de red siempre disponibles'
$Title.Font = New-Object Drawing.Font('Segoe UI Semibold', 17)
$Title.AutoSize = $true
$Title.Location = New-Object Drawing.Point(28, 22)
$Form.Controls.Add($Title)

$Intro = New-Object Windows.Forms.Label
$Intro.Text = (
    "Indique las rutas del NAS. DrivePulse las mostrará en el Explorador " +
    "y las reconectará al iniciar sesión."
)
$Intro.Location = New-Object Drawing.Point(31, 62)
$Intro.Size = New-Object Drawing.Size(930, 42)
$Form.Controls.Add($Intro)

$MappingGroup = New-Object Windows.Forms.GroupBox
$MappingGroup.Text = 'Unidades'
$MappingGroup.Location = New-Object Drawing.Point(28, 106)
$MappingGroup.Size = New-Object Drawing.Size(954, 184)
$Form.Controls.Add($MappingGroup)

$Headers = @(
    @('Comando', 18),
    @('Letra', 98),
    @('Ruta compartida', 157),
    @('Contraseña', 450),
    @('Usuario', 596),
    @('Persistencia', 824)
)
foreach ($Header in $Headers) {
    $HeaderLabel = New-Object Windows.Forms.Label
    $HeaderLabel.Text = $Header[0]
    $HeaderLabel.Location = New-Object Drawing.Point($Header[1], 28)
    $HeaderLabel.AutoSize = $true
    $MappingGroup.Controls.Add($HeaderLabel)
}

$Defaults = @(
    @('W:', '\\192.168.230.245\minvivienda'),
    @('Z:', '\\192.168.230.245\seguridad'),
    @('F:', '\\192.168.230.245\minvdomustemp')
)
$LetterBoxes = @()
$PathBoxes = @()
$PasswordBoxes = @()
$UserBoxes = @()
for ($Index = 0; $Index -lt $Defaults.Count; $Index++) {
    $Y = 53 + ($Index * 36)
    $CommandLabel = New-Object Windows.Forms.Label
    $CommandLabel.Text = "$($Index + 1). net use"
    $CommandLabel.Location = New-Object Drawing.Point(18, ($Y + 4))
    $CommandLabel.AutoSize = $true
    $MappingGroup.Controls.Add($CommandLabel)

    $LetterBox = New-Object Windows.Forms.TextBox
    $LetterBox.Text = $Defaults[$Index][0]
    $LetterBox.CharacterCasing = 'Upper'
    $LetterBox.MaxLength = 2
    $LetterBox.Location = New-Object Drawing.Point(98, $Y)
    $LetterBox.Size = New-Object Drawing.Size(45, 25)
    $MappingGroup.Controls.Add($LetterBox)
    $LetterBoxes += $LetterBox

    $PathBox = New-Object Windows.Forms.TextBox
    $PathBox.Text = $Defaults[$Index][1]
    $PathBox.Location = New-Object Drawing.Point(157, $Y)
    $PathBox.Size = New-Object Drawing.Size(280, 25)
    $MappingGroup.Controls.Add($PathBox)
    $PathBoxes += $PathBox

    $PasswordBox = New-Object Windows.Forms.TextBox
    $PasswordBox.UseSystemPasswordChar = $true
    $PasswordBox.Location = New-Object Drawing.Point(450, $Y)
    $PasswordBox.Size = New-Object Drawing.Size(130, 25)
    $MappingGroup.Controls.Add($PasswordBox)
    $PasswordBoxes += $PasswordBox

    $UserBox = New-Object Windows.Forms.TextBox
    $UserBox.Text = 'workgroup\readuser'
    $UserBox.Location = New-Object Drawing.Point(596, $Y)
    $UserBox.Size = New-Object Drawing.Size(210, 25)
    $MappingGroup.Controls.Add($UserBox)
    $UserBoxes += $UserBox

    $PersistentLabel = New-Object Windows.Forms.Label
    $PersistentLabel.Text = '/persistent:yes'
    $PersistentLabel.Location = New-Object Drawing.Point(824, ($Y + 4))
    $PersistentLabel.AutoSize = $true
    $MappingGroup.Controls.Add($PersistentLabel)
}

$SystemBox = New-Object Windows.Forms.CheckBox
$SystemBox.Text = 'También habilitar las unidades para ABBYY y servicios de Windows'
$SystemBox.Checked = $true
$SystemBox.Location = New-Object Drawing.Point(31, 310)
$SystemBox.Size = New-Object Drawing.Size(930, 25)
$Form.Controls.Add($SystemBox)

$SecurityNote = New-Object Windows.Forms.Label
$SecurityNote.Text = (
    "La contraseña se cifra con Windows DPAPI. No se guarda en texto plano " +
    "ni aparece en la línea de comandos."
)
$SecurityNote.ForeColor = [Drawing.Color]::DimGray
$SecurityNote.Location = New-Object Drawing.Point(31, 344)
$SecurityNote.Size = New-Object Drawing.Size(930, 40)
$Form.Controls.Add($SecurityNote)

$StatusLabel = New-Object Windows.Forms.Label
$StatusLabel.Text = 'Listo para instalar.'
$StatusLabel.Location = New-Object Drawing.Point(31, 433)
$StatusLabel.Size = New-Object Drawing.Size(710, 26)
$Form.Controls.Add($StatusLabel)

$InstallButton = New-Object Windows.Forms.Button
$InstallButton.Text = 'Instalar y mapear'
$InstallButton.Location = New-Object Drawing.Point(816, 424)
$InstallButton.Size = New-Object Drawing.Size(166, 36)
$InstallButton.BackColor = [Drawing.Color]::FromArgb(20, 115, 230)
$InstallButton.ForeColor = [Drawing.Color]::White
$InstallButton.FlatStyle = 'Flat'
$Form.Controls.Add($InstallButton)
$Form.AcceptButton = $InstallButton

$InstallButton.Add_Click({
    try {
        $Drives = @()
        $Seen = @{}
        for ($Index = 0; $Index -lt $LetterBoxes.Count; $Index++) {
            $Letter = $LetterBoxes[$Index].Text.Trim().ToUpperInvariant()
            if ($Letter -match '^[A-Z]$') {
                $Letter += ':'
            }
            $Unc = $PathBoxes[$Index].Text.Trim()
            if ($Letter -notmatch '^[D-Z]:$') {
                throw "La letra de la unidad $($Index + 1) debe estar entre D: y Z:."
            }
            if ($Seen.ContainsKey($Letter)) {
                throw "La letra $Letter está repetida."
            }
            $Seen[$Letter] = $true
            if ($Unc -notmatch '^\\\\[^\\/:*?"<>|]+\\[^\\/:*?"<>|]+$') {
                throw "La ruta de $Letter debe usar el formato \\servidor\carpeta."
            }
            if (-not $UserBoxes[$Index].Text.Trim()) {
                throw "Ingrese el usuario del NAS para $Letter."
            }
            if (-not $PasswordBoxes[$Index].Text) {
                throw "Ingrese la contraseña del NAS para $Letter."
            }
            $Drives += [ordered]@{
                letter = $Letter
                unc = $Unc
                username = $UserBoxes[$Index].Text.Trim()
                password = $PasswordBoxes[$Index].Text
            }
        }

        $InstallButton.Enabled = $false
        $Form.UseWaitCursor = $true
        $StatusLabel.Text = 'Instalando DrivePulse...'
        $Form.Refresh()

        $Installer = Join-Path $PSScriptRoot 'install.ps1'
        if (-not (Test-Path -LiteralPath $Installer -PathType Leaf)) {
            throw "El paquete está incompleto: falta install.ps1."
        }
        $InstallOutput = & powershell.exe -NoProfile -ExecutionPolicy Bypass `
            -File $Installer -NonInteractive 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "La instalación falló:`r`n$($InstallOutput -join "`r`n")"
        }

        $StatusLabel.Text = 'Protegiendo credenciales y creando unidades...'
        $Form.Refresh()
        $Request = [ordered]@{
            target_user = $TargetUser
            include_system = [bool]$SystemBox.Checked
            drives = $Drives
        }
        $Payload = $Request | ConvertTo-Json -Depth 5 -Compress
        $Cli = 'C:\Program Files\DriveMapper\drivemap\drivemap.exe'
        $ProvisionOutput = Invoke-Provision -Executable $Cli -Payload $Payload
        $null = $ProvisionOutput | ConvertFrom-Json

        foreach ($PasswordBox in $PasswordBoxes) {
            $PasswordBox.Clear()
        }
        $Payload = $null
        $Request = $null
        $StatusLabel.Text = 'Instalación completada.'
        $Form.UseWaitCursor = $false
        [Windows.Forms.MessageBox]::Show(
            (
                "DrivePulse quedó instalado para $TargetUser.`r`n`r`n" +
                "Las unidades aparecerán en el Explorador cuando el NAS esté " +
                "disponible y se reconectarán automáticamente al iniciar sesión."
            ),
            "DrivePulse instalado",
            [Windows.Forms.MessageBoxButtons]::OK,
            [Windows.Forms.MessageBoxIcon]::Information
        ) | Out-Null
        Start-Process explorer.exe 'shell:MyComputerFolder'
        $Form.DialogResult = [Windows.Forms.DialogResult]::OK
        $Form.Close()
    } catch {
        $Form.UseWaitCursor = $false
        $InstallButton.Enabled = $true
        $StatusLabel.Text = 'No se completó la instalación.'
        Show-Error -Message $_.Exception.Message
    }
})

$null = $Form.ShowDialog()
