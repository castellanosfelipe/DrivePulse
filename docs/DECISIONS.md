# Decisiones de arquitectura

Estado de todos los ADR: **Accepted for v1**.

## D-001 — Tarea programada, no servicio

DriveMapper usa `DriveMapper-System` como `NT AUTHORITY\SYSTEM`, con nivel
máximo, recuperación y ejecución sin límite. Reproduce la sesión que antes se
obtenía mediante PsExec y simplifica instalación y diagnóstico.

Se descartaron un servicio con `win32serviceutil` por su ciclo de vida más
complejo, NSSM por introducir una dependencia y PsExec por ser innecesario y
problemático para EDR.

## D-002 — WNetAddConnection2, no net use

El agente usa `WNetAddConnection2`/`WNetCancelConnection2`. La contraseña pasa
en memoria y los errores llegan como `winerror`.

Se descartaron `net use` por exponer el secreto en la línea de comandos,
`New-PSDrive` por su sesión de PowerShell, `mklink` porque no autentica SMB y
`HKLM\...\DOS Devices` porque solo define nombres DOS.

## D-003 — Trigger de arranque y evento de red

La tarea tiene `AtStartup` y evento
`Microsoft-Windows-NetworkProfile/Operational` 10000. `IgnoreNew` y un mutex
evitan solapamiento; `StartWhenAvailable` cubre red tardía.

Solo `AtStartup`, solo evento y un retraso fijo se descartaron porque dejan
carreras de inicialización.

## D-004 — Watchdog configurable

Un proceso de larga vida comprueba acceso real cada `check_interval_s` y
despierta mediante centinela cuando cambia la configuración. Esto cubre
AutoDisconnect, reinicios del NAS y microcortes. Una tarea periódica corta
perdería estado de backoff y multiplicaría arranques.

## D-005 — Backoff y fallos clasificados

53, 55 y 64 son transitorios. 67, 86, 1326 y 1909 detienen intentos. 85 fuerza
limpieza; 1219 cancela sesiones al host antes de remapear. Los estados de retry
persisten en SQLite, por lo que un crash no reinicia una tormenta de intentos.

Se descartó reintentar todo porque puede bloquear `readuser`, y detener todo
porque impediría la recuperación de red.

## D-006 — DPAPI de máquina

Los secretos usan `CRYPTPROTECT_LOCAL_MACHINE`, entropía adicional y prefijo
`dpapi:`. El blob no es portable. La seguridad efectiva depende también de la
ACL. `fernet:` existe solo para pruebas/CI y el runtime Windows lo rechaza.

DPAPI de usuario no cruza administrador→SYSTEM. Credential Manager con
`CONNECT_CMD_SAVECRED` duplica secretos y no resuelve la carrera de red. Una
clave simétrica junto al archivo no crea una frontera de seguridad.

## D-007 — Program Files y ProgramData

Binarios: `C:\Program Files\DriveMapper`. Configuración, datos y logs:
`C:\ProgramData\DriveMapper`. Se rompe deliberadamente la ejecución portable
para proteger escritura y sobrevivir actualizaciones. SYSTEM y Administrators
tienen control; usuarios estándar no tienen acceso.

## D-008 — Scope por unidad

El modelo distingue `system` y `user`; `user` exige `target_user`. Las sesiones
no comparten mapeos. Para usuario, el CLI deriva una configuración que contiene
solo sus unidades, aplica ACL por SID y registra una tarea `AtLogOn` con
`InteractiveToken`; el archivo global y los secretos SYSTEM siguen ocultos. La
instalación productiva inicial usa `system` por el procedimiento PsExec
existente y queda pendiente confirmar la cuenta del servicio ABBYY antes del
smoke test final.

`EnableLinkedConnections` no cruza hacia SYSTEM y no sustituye este modelo.

## D-009 — Configuración declarativa e inventario de propiedad

`config.json` es el estado deseado. SQLite conserva `managed_mappings` para
recordar qué creó DriveMapper. Solo se desmonta una entrada conocida que aún
apunta al UNC registrado. Si otra aplicación reutiliza la letra, se registra un
conflicto y no se toca.

Se descartó desmontar toda letra ausente del JSON por ser destructivo.

## D-010 — Redacción por construcción

Un registro de secretos activos filtra mensajes y argumentos antes de que
cualquier handler escriba. `secret` no aparece en `repr`; `export` lo elimina.
Los tests usan valores marcadores. Depender de la disciplina de cada llamada de
logging se consideró insuficiente.

## D-011 — Persistencia garantizada por el agente

SYSTEM usa `persistent=false` por defecto. La garantía proviene de cuatro capas:
tarea de arranque, evento de red, watchdog y recuperación del Scheduler.
`CONNECT_UPDATE_PROFILE` puede dejar letras fantasma y no retransmite por sí
solo la credencial workgroup.

Para `scope:user`, el perfil puede habilitarse por compatibilidad con Explorer,
pero el agente continúa siendo la autoridad. `CONNECT_CMD_SAVECRED` se descartó
por duplicar el almacén de secretos y ampliar acceso desde SYSTEM.

## Panel web

Se posterga. Un servidor HTTP dentro de un proceso SYSTEM aumenta superficie de
ataque sin aportar valor a la reparación de unidades. CLI, Event Log y SQLite
cubren v1.

## GPO

Tres equipos no justifican sustituir el agente por GPO. Una GPO puede distribuir
el paquete, pero Drive Maps Preferences no cubre de forma completa la sesión
SYSTEM, DPAPI, backoff, verificación real ni recuperación continua.
