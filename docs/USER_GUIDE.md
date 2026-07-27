# Guía de usuario y operación

## Requisitos

- Windows 10 Pro 22H2 x64.
- PowerShell 5.1.
- Cuenta administrativa para instalar y administrar.
- Acceso TCP/445 al NAS `192.168.230.245`.
- Paquete `dist\DriveMapper\` completo.
- Contraseña vigente de `workgroup\readuser`, ingresada únicamente por prompt.

El destino no necesita Python, PsExec, NSSM ni internet.

## Build estrictamente offline

`build.ps1` rechaza un `wheelhouse` vacío y siempre instala con `--no-index`.
Ejecuta todas las pruebas antes de PyInstaller y luego corre un self-test dentro
del `agent.exe` congelado.

```powershell
.\build.ps1
```

Resultado:

```text
dist\DriveMapper\
├── agent\agent.exe
├── drivemap\drivemap.exe
├── install.ps1
├── uninstall.ps1
└── docs\
```

### Regenerar wheelhouse desde un equipo con internet

Use CPython 3.12 x64:

```powershell
pip download -r requirements.txt -r requirements-dev.txt `
  --dest .\wheelhouse --only-binary=:all: `
  --platform win_amd64 --python-version 312 --implementation cp
```

El build usa `pyinstaller==6.11.1`, fijado en `requirements-dev.txt`; no instale
una versión distinta por fuera del archivo.

Para regenerar el instalador de Python de contingencia, descargue
`python-3.12.10-amd64.exe` desde Python.org, verifique su SHA-256 y colóquelo en
`vendor\`. El runtime de destino no usa ese instalador.

## Instalación

Para instalar directamente desde los assets de una release, coloque el ZIP, el
archivo `.sha256` y `DrivePulse-<versión>-install.ps1` en la misma carpeta.
Desde PowerShell como administrador ejecute un solo comando:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\DrivePulse-<versión>-install.ps1
```

El bootstrap valida el SHA-256 antes de extraer y ejecutar el instalador
incluido. Si el ZIP ya está extraído, use:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```

El instalador:

1. verifica elevación y x64;
2. valida el bundle y sus ejecutables antes de modificar la instalación vigente;
3. prepara los binarios en *staging* y detiene tareas/procesos anteriores;
4. intercambia versiones con rollback automático si falla un paso;
5. conserva los datos en `C:\ProgramData\DriveMapper`;
6. permite lectura/ejecución de binarios a usuarios, pero mantiene configuración,
   secretos e historial solo para SYSTEM y Administrators;
7. registra `DriveMapper-System` con arranque y evento de red 10000;
8. registra el origen `DriveMapper` de Event Log y actualiza el PATH;
9. inicia el watchdog y exige un heartbeat sano antes de informar éxito.

Es idempotente. Puede ejecutarse nuevamente para actualizar binarios o reparar
tareas y ACL sin borrar la configuración.

## Configuración inicial recomendada

Abra una consola administrativa nueva para recibir el PATH actualizado:

```powershell
drivemap add --id minvivienda --letter W: `
  --unc \\192.168.230.245\minvivienda `
  --user workgroup\readuser --scope system

drivemap add --id seguridad --letter Z: `
  --unc \\192.168.230.245\seguridad `
  --user workgroup\readuser --scope system

drivemap add --id minvdomustemp --letter F: `
  --unc \\192.168.230.245\minvdomustemp `
  --user workgroup\readuser --scope system
```

La contraseña se solicita y confirma de forma oculta. No existe un argumento
que acepte su valor.

El *scope* `system` es el recomendado porque el procedimiento anterior creaba
las unidades dentro de `NT AUTHORITY\SYSTEM`. Antes de producción, confirme que
el servicio ABBYY realmente usa esa cuenta con:

```powershell
Get-CimInstance Win32_Service |
  Where-Object {
    $_.Name -match 'ABBYY' -or $_.DisplayName -match 'ABBYY'
  } |
  Select-Object Name, DisplayName, StartName, State, PathName
```

Si ABBYY usa otra cuenta, no cambie el *scope* a ciegas: valide el diseño de
tarea de usuario y la sesión de logon correspondiente.

## Comandos cotidianos

```powershell
drivemap list
drivemap status --json
drivemap apply
drivemap test seguridad
drivemap set seguridad --password
drivemap disable minvdomustemp
drivemap enable minvdomustemp
drivemap remove minvdomustemp
drivemap logs --tail 200
drivemap doctor
drivemap export C:\Temp\drives-without-secrets.json
drivemap import C:\Temp\drives-without-secrets.json
```

`remove` desmonta por convergencia. Use `--keep-mounted` solo cuando otro
sistema asumirá deliberadamente la propiedad del mapeo.

## Diagnóstico del Synology

Ejecute:

```powershell
drivemap doctor

Get-SmbConnection |
  Where-Object ServerName -eq '192.168.230.245' |
  Select-Object ServerName,ShareName,UserName,Dialect,Signed,Encrypted
```

En DSM registre modelo y versión desde **Panel de control → Centro de
información**, y el mínimo/máximo SMB desde **Servicios de archivos → SMB →
Configuración avanzada**. No habilite SMB1 ni acceso invitado salvo aprobación
de seguridad explícita.

## Actualización

Construya una nueva versión, copie el paquete y ejecute `install.ps1` de nuevo.
La configuración, secretos, historial e incidentes permanecen en ProgramData.

## Desinstalación

Conservar configuración y mapeos:

```powershell
.\uninstall.ps1
```

Desmontar mapeos gestionados:

```powershell
.\uninstall.ps1 -RemoveMappings
```

Eliminar también configuración, blobs DPAPI, logs e historial:

```powershell
.\uninstall.ps1 -RemoveMappings -Purge
```

`-Purge` es irreversible.
