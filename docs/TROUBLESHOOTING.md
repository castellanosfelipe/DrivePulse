# Solución de problemas

Empiece siempre con:

```powershell
drivemap doctor
drivemap status --json
drivemap logs --tail 200
Get-WinEvent -FilterHashtable @{LogName='Application';ProviderName='DriveMapper'} `
  -MaxEvents 50
```

## La unidad aparece con X roja

Es una conexión de perfil sin sesión SMB activa. Ejecute `drivemap apply`.
DriveMapper debe cancelar la letra fantasma y reconstruirla. Si persiste,
revise TCP/445, el nombre del share y el estado de retry.

## Códigos Win32

| Código | Tratamiento | Acción |
|---:|---|---|
| 53 | Transitorio | Verifique red, VLAN, IP y NAS; habrá backoff |
| 55/64 | Transitorio | Sesión caída; el agente limpia y remapea |
| 67 | Permanente | Corrija el nombre exacto del share |
| 85 | Reparación | Letra ocupada/fantasma; se cancela y remapea |
| 86/1326 | Permanente crítico | Corrija usuario/contraseña; no habrá más intentos |
| 1219 | Por host | Cierre sesiones al NAS con otro usuario |
| 1909 | Permanente crítico | Desbloquee `readuser` en el Synology |

## Error 1219

Windows no permite credenciales distintas simultáneas contra el mismo nombre de
servidor en una sesión. Compruebe:

```powershell
Get-SmbConnection |
  Where-Object ServerName -eq '192.168.230.245' |
  Format-Table ServerName,ShareName,UserName,Dialect
```

Unifique todas las unidades en `workgroup\readuser`. No mezcle el nombre DNS y
la IP para eludir esta protección.

## Secreto DPAPI no descifrable

Los blobs no se pueden copiar entre equipos. En el equipo afectado:

```powershell
drivemap set seguridad --password
```

Repita por cada unidad. No copie `config.json` con blobs y espere que funcione;
use `export`/`import`.

## ABBYY no ve la unidad

Confirme la cuenta:

```powershell
Get-CimInstance Win32_Service |
  Where-Object {$_.Name -match 'ABBYY' -or $_.DisplayName -match 'ABBYY'} |
  Select Name,DisplayName,StartName,State
```

Si `StartName` no es `LocalSystem`, el mapeo SYSTEM no pertenece a la sesión
correcta. Detenga el cambio y diseñe/valide el scope de esa identidad antes de
producción.

## Synology

Use SMB2 o SMB3; no habilite SMB1. Verifique usuario, bloqueo, permisos de share
y límite de sesiones en DSM. `AllowInsecureGuestAuth` no debe habilitarse para
una cuenta autenticada como `readuser`.

