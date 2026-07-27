# DriveMapper

DriveMapper mantiene unidades SMB disponibles después del arranque y las repara
si Windows o el NAS pierden la sesión. Está pensado para ABBYY en tres equipos
Windows 10 Pro 22H2 sin internet y reemplaza el procedimiento con PsExec y
`net use`.

La solución:

- ejecuta un watchdog como `NT AUTHORITY\SYSTEM`;
- usa `WNetAddConnection2`, por lo que la contraseña no aparece en procesos;
- protege secretos con DPAPI de máquina y ACL de ProgramData;
- distingue fallos transitorios de credenciales inválidas;
- detiene reintentos ante 86, 1326 o 1909;
- limpia unidades fantasma antes de reconstruirlas;
- registra transiciones en SQLite, `agent.log` y Windows Event Log;
- se compila e instala completamente offline.

## Instalación rápida

En la máquina de build:

```powershell
.\build.ps1
```

Copie `dist\DriveMapper\` completa al equipo destino y ejecute como
administrador:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\install.ps1
```

Agregue las unidades. Cada comando solicita la contraseña por prompt oculto:

```powershell
drivemap add --id minvivienda --letter W: `
  --unc \\192.168.230.245\minvivienda --user workgroup\readuser

drivemap add --id seguridad --letter Z: `
  --unc \\192.168.230.245\seguridad --user workgroup\readuser

drivemap add --id minvdomustemp --letter F: `
  --unc \\192.168.230.245\minvdomustemp --user workgroup\readuser

drivemap doctor
drivemap status
```

Rote la contraseña histórica de `readuser` antes de producción: su uso previo
en `net use` debe tratarse como exposición.

Consulte [docs/USER_GUIDE.md](docs/USER_GUIDE.md) para operación completa y
[docs/ACCEPTANCE.md](docs/ACCEPTANCE.md) para las pruebas pendientes en los
equipos reales.

