# Criterios de aceptación

`Dev verificado` significa prueba automatizada o inspección reproducible en el
repositorio. `Pendiente Windows real` requiere los tres equipos y el Synology.

| # | Criterio | Estado | Evidencia |
|---:|---|---|---|
| 1 | Unidades accesibles ≤120 s tras reinicio | Pendiente Windows real | Ejecutar protocolo A-01 con cronómetro y Event Log |
| 2 | Scope SYSTEM visible para LocalSystem | Pendiente Windows real | Probar desde proceso SYSTEM; PsExec solo como instrumento de prueba |
| 3 | `add` converge sin reinicio | Dev verificado / smoke pendiente | `tests/test_cli.py`, `tests/test_reconciler.py` |
| 4 | `remove` desmonta y no reaparece | Dev verificado / smoke pendiente | `test_removes_deleted_mapping_owned_by_agent` |
| 5 | Recuperación del NAS ≤2 ciclos | Dev parcial / smoke pendiente | Backoff y cierre de incidentes implementados; apagar/encender Synology |
| 6 | Contraseña incorrecta intenta una vez | Dev verificado / smoke pendiente | `test_permanent_failure_persists_suppression`, códigos 86/1326/1909 |
| 7 | Contraseña ausente de config/log/proceso | Dev verificado / Windows pendiente | tests de secretos/redacción; inspeccionar `Win32_Process` durante mapeo |
| 8 | Config no legible por usuario estándar | Pendiente Windows real | `install.ps1` + `drivemap doctor` + intento con usuario estándar |
| 9 | Instalación offline sin Python | Build verificado / equipo real pendiente | Build offline, self-test congelado y smoke de release obligatorios en GitHub Actions |
| 10 | Instalador idempotente | CI automatizado / equipo real pendiente | El pipeline ejecuta instalación limpia y reinstalación preservando configuración |
| 11 | Uninstall limpia tarea/proceso/PATH | CI automatizado / variantes reales pendientes | El pipeline exige desinstalación con `-Purge`; falta validar mapeos reales |
| 12 | Doctor detecta cuatro fallos | Dev parcial / smoke pendiente | Implementación de host, secreto, letra, sesiones SMB |
| 13 | Sin dependencia de PsExec | Dev verificado | Búsqueda del repo; solo se menciona como instrumento de aceptación |
| 14 | Solo SMB hacia hosts configurados | Pendiente Windows real | Captura Wireshark durante 10 minutos |

## Protocolos de aceptación

### A-01 Arranque

1. Confirmar estado sano con `drivemap status --json`.
2. Reiniciar.
3. No iniciar sesión para el test SYSTEM.
4. Medir desde boot hasta tres estados `connected`.
5. Confirmar lectura real de los tres `verify_path`.

### A-02 Credencial inválida

1. Usar una cuenta de prueba que no pueda bloquear la cuenta corporativa.
2. Establecer contraseña inválida mediante prompt.
3. Confirmar un solo evento y `permanent=1` en estado de retry.
4. Esperar dos intervalos y confirmar que no hay nuevos intentos.
5. Corregir con `drivemap set <id> --password` y verificar recuperación.

### A-03 Caída del NAS

1. Apagar SMB o aislar TCP/445 con cambio autorizado.
2. Confirmar incidente abierto.
3. Restaurar el NAS.
4. Confirmar recuperación en dos ciclos y `ended_at`.
