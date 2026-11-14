# Plan de implementación: ejecuciones programadas observables, recuperables y verificables

**Rama base:** `refactor/cron-wrappers`  
**Rama de trabajo:** `feat/scheduled-execution-reliability`  
**Estado:** planificación; no implica que las tareas estén implementadas.

## 1. Objetivo y alcance

Endurecer el mecanismo actual de cron —wrappers Bash específicos más `scripts/run_report.sh` y generadores Python independientes— sin introducir un scheduler nuevo ni acoplar la ejecución a un servicio residente.

Cada ejecución debe permitir determinar:

1. Qué reporte debía ejecutarse y con qué parámetros.
2. Cuándo comenzó y terminó, cuánto duró y cuál fue su resultado.
3. Si el artefacto fue generado, validado y entregado.
4. Qué falló, dónde consultar evidencia y cómo reintentar sin duplicar efectos.

**Fuera de alcance inicial:** sustituir cron, construir una plataforma distribuida de orquestación, introducir Celery/Redis, o prometer recuperación automática de ejecuciones que el scheduler nunca lanzó.

## 2. Principios y decisiones de diseño

- Mantener cron como disparador y el wrapper común como punto de entrada.
- Separar el estado de la ejecución del texto de los logs.
- Registrar estados terminales distintos: `SUCCEEDED`, `FAILED`, `SKIPPED_LOCKED`, `TIMED_OUT` y `INTERRUPTED`.
- No tratar una ejecución omitida por lock como éxito. Definir códigos de salida documentados y estables.
- Usar un **ledger SQLite local** para el historial consultable, con transacciones y esquema versionado. No usar archivos JSON independientes como fuente de verdad concurrente.
- Mantener logs de texto/JSON para diagnóstico; el ledger conserva metadatos y referencias, no secretos ni contenido sensible.
- No reintentar a ciegas el flujo completo: clasificar errores y garantizar idempotencia antes de automatizar reintentos.
- Los locks `flock` son coordinación local. No asumir que ofrecen exclusión distribuida fiable sobre NFS o entre hosts.
- Proteger logs, base de datos y locks con permisos restrictivos; nunca registrar tokens, contraseñas ni variables secretas.

## 3. Plan de tareas

### Fase 0 — Contrato operativo y línea base

- [ ] **OPS-001** Documentar el contrato actual de cada wrapper: nombre del reporte, generador, argumentos, variables de entorno, directorios y código de salida.
- [ ] **OPS-002** Definir catálogo de estados y códigos de salida del runner. Diferenciar fallo, timeout y omisión por concurrencia.
- [ ] **OPS-003** Definir el modelo de ejecución: `run_id`, `report_name`, `trigger`, `scheduled_for`, `started_at`, `finished_at`, `duration_ms`, `status`, `exit_code`, `artifact_path`, `artifact_sha256`, `delivery_status`, `log_path` y `error_summary`.
- [ ] **OPS-004** Establecer retención configurable para logs, ledger y artefactos; documentar espacio en disco esperado.
- [ ] **OPS-005** Fijar explícitamente el alcance de una sola máquina. Si se necesita ejecución multi-host, abrir un diseño separado para locking y almacenamiento compartidos.

**Entregable:** contrato operativo aprobado y criterios de aceptación medibles.

### Fase 1 — Registro y observabilidad de extremo a extremo

- [ ] **OBS-001** Crear módulo Python de tracking con SQLite (schema versionado, transacciones, timeout de conexión y migraciones seguras).
- [ ] **OBS-002** Crear un `run_id` único por intento y propagarlo desde el wrapper al generador mediante entorno/CLI.
- [ ] **OBS-003** Registrar eventos de inicio, fin, cambio de estado, generación de artefacto y entrega. Garantizar cierre del registro ante excepciones y señales capturables.
- [ ] **OBS-004** Emitir logs estructurados con timestamp, nivel, reporte, `run_id`, etapa y duración; conservar stdout/stderr del generador.
- [ ] **OBS-005** Hacer que el wrapper emita a stderr un resumen accionable cuando falle: reporte, `run_id`, código y ruta del log. Esto permite que cron/monitor externo detecte fallos.
- [ ] **OBS-006** Registrar por separado resultado de generación y resultado de cada canal de entrega. Una generación válida con entrega fallida no debe aparecer como éxito completo.
- [ ] **OBS-007** Añadir comando CLI de consulta: listar últimas ejecuciones, filtrar por reporte/estado/fecha y mostrar detalle de un `run_id`.
- [ ] **OBS-008** Añadir rotación/retención de logs y limpieza controlada de registros antiguos, sin borrar ejecuciones aún necesarias para auditoría.

**Criterio de salida:** toda invocación produce un registro consultable, incluso si falla antes de generar el PDF; los logs pueden correlacionarse por `run_id`.

### Fase 2 — Confiabilidad del runner y control de concurrencia

- [ ] **REL-001** Endurecer `scripts/run_report.sh`: rutas relativas resueltas desde la raíz del repo, validación temprana de intérprete, entrypoint y directorios.
- [ ] **REL-002** Aplicar `umask 077` y permisos restrictivos a logs, ledger y archivos de lock.
- [ ] **REL-003** Definir comportamiento explícito cuando `flock` no está disponible: fallar de forma segura por defecto o permitir modo sin lock solo mediante configuración explícita.
- [ ] **REL-004** Mantener locks independientes por tipo de reporte y documentar su límite a nivel de host/sistema de archivos.
- [ ] **REL-005** Devolver estado/código específico al no adquirir lock; registrar `SKIPPED_LOCKED` y no confundirlo con éxito.
- [ ] **REL-006** Implementar timeout configurable por reporte, con terminación del proceso hijo/grupo y registro `TIMED_OUT`.
- [ ] **REL-007** Capturar señales `TERM`/`INT` para registrar `INTERRUPTED` cuando sea posible y liberar recursos; contemplar SIGKILL/corte eléctrico mediante reconciliación posterior.
- [ ] **REL-008** Validar rutas de log/ledger y comportamiento desde un CWD distinto, como ocurre en cron.
- [ ] **REL-009** Revisar la carga de `.env`: definir formato soportado y evitar evaluar contenido como shell. Resolver el contrato entre el parser Bash y `common/settings.py` para que no existan interpretaciones distintas.

**Criterio de salida:** no hay falsos éxitos por lock, los procesos no pueden colgarse indefinidamente y los fallos de infraestructura quedan registrados.

### Fase 3 — Recuperación y reintentos seguros

- [ ] **REC-001** Implementar reconciliación al inicio/consulta para detectar registros `RUNNING` cuyo proceso ya no existe o cuya antigüedad supera el umbral; marcarlos `INTERRUPTED`/stale con evidencia, sin asumir automáticamente que fallaron antes de completar el artefacto.
- [ ] **REC-002** Añadir comando de reejecución manual por reporte y parámetros, generando un nuevo `run_id` y guardando `retry_of_run_id`.
- [ ] **REC-003** Definir clasificación de errores transitorios, permanentes y desconocidos. No reintentar errores de configuración/autorización como si fueran fallos de red.
- [ ] **REC-004** Implementar reintentos acotados con backoff exponencial y jitter únicamente en operaciones identificadas como seguras/idempotentes (por ejemplo, ciertas lecturas HTTP y entregas con clave de idempotencia cuando el proveedor la soporte).
- [ ] **REC-005** Evitar duplicación de entregas: guardar estado por canal y clave de operación; si el canal no ofrece idempotencia, exigir comprobación/confirmación antes de repetir.
- [ ] **REC-006** Definir política de recuperación de artefactos: conservar PDF válido ya producido cuando falle la entrega; validar si una nueva generación debe reemplazarlo o crear versión nueva.
- [ ] **REC-007** Proveer procedimiento de recuperación documentado: inspeccionar, validar artefacto, corregir causa, reintentar y comprobar entrega.
- [ ] **REC-008** Definir política para ejecuciones perdidas por caída del host: inicialmente detección/alerta y recuperación manual; el catch-up automático requerirá conocer calendario y ventana de validez del reporte.

**Criterio de salida:** una ejecución fallida puede investigarse y reintentarse con trazabilidad, sin sobrescribir evidencia ni duplicar entregas silenciosamente.

### Fase 4 — Verificación de resultados y alertas

- [ ] **VER-001** Validar el artefacto al finalizar: existencia, tamaño mínimo, extensión esperada y apertura/estructura PDF (p. ej. lectura de cabecera y parser disponible).
- [ ] **VER-002** Calcular SHA-256 y registrar ruta, tamaño, timestamp y hash del artefacto.
- [ ] **VER-003** Verificar que el artefacto corresponde al reporte/ejecución actual y no es un PDF antiguo dejado por una ejecución previa.
- [ ] **VER-004** Verificar por canal el resultado de entrega y persistir identificador/respuesta del proveedor cuando esté disponible, sin secretos.
- [ ] **VER-005** Implementar notificación de fallo y timeout mediante mecanismo configurable (stderr para cron como mínimo; email/Telegram opcional). Evitar notificar `SKIPPED_LOCKED` como fallo salvo política explícita.
- [ ] **VER-006** Añadir comando `status/health` que resuma última ejecución, última ejecución exitosa, fallos recientes, ejecuciones stale y antigüedad del último artefacto.
- [ ] **VER-007** Definir umbrales de alerta: ausencia de ejecución esperada, última ejecución exitosa demasiado antigua, fallo repetido y falta de espacio/permisos cuando se pueda medir.

**Criterio de salida:** el sistema no declara éxito solo porque el proceso Python terminó con código cero; verifica artefacto y entrega conforme a la política configurada.

### Fase 5 — Pruebas, documentación y operación

- [ ] **TST-001** Crear suite de pruebas shell para CWD externo, intérprete configurado, `.env`, creación de logs, propagación de códigos y rutas relativas.
- [ ] **TST-002** Probar concurrencia del mismo reporte: una ejecución adquiere lock y la segunda queda `SKIPPED_LOCKED`.
- [ ] **TST-003** Probar ejecución simultánea de reportes distintos sin bloqueo mutuo.
- [ ] **TST-004** Simular ausencia de `flock`, timeout, SIGTERM, fallo del generador, caída de entrega y reinicio con registro stale.
- [ ] **TST-005** Probar migraciones SQLite, escrituras concurrentes, consulta histórica, retención y reejecución enlazada al intento original.
- [ ] **TST-006** Probar PDF inexistente, vacío, corrupto, antiguo y válido; verificar hash y estado de entrega.
- [ ] **TST-007** Ejecutar la suite Python existente y las nuevas pruebas de integración; comparar regresión de contenido de reportes migrados, no solo que el PDF exista.
- [ ] **DOC-001** Actualizar `README.md` con variables, códigos de salida, comandos de consulta/recuperación, rutas de estado/logs, retención y limitaciones.
- [ ] **DOC-002** Actualizar `crontab.example` para mostrar entorno, redirección, notificaciones y comportamiento de locks sin ocultar fallos.
- [ ] **DOC-003** Crear runbook de operación: diagnóstico, recuperación, limpieza, restauración y escalamiento.
- [ ] **DOC-004** Documentar instalación/backup del ledger y advertir que el estado SQLite debe residir en almacenamiento local compatible, no en NFS.

**Criterio de salida:** pruebas automatizadas reproducen los fallos operativos principales y otra persona puede diagnosticar y recuperar una ejecución siguiendo el runbook.

## 4. Orden recomendado de implementación

1. **Primero:** OPS-001..005 y OBS-001..005. Definir contrato antes de automatizar recuperación.
2. **Segundo:** REL-001..009. Corregir falsos éxitos, locks, timeout y señales.
3. **Tercero:** OBS-006..008 y OBS-007. Completar consulta y retención.
4. **Cuarto:** VER-001..007. Acordar qué significa realmente `SUCCEEDED`.
5. **Quinto:** REC-001..008. Habilitar reintentos solo después de tener estados y verificación.
6. **En paralelo desde el inicio:** TST y DOC; README y `crontab.example` deben mantenerse sincronizados con cada cambio.

## 5. Definición de éxito global

La implementación se considera terminada cuando se cumplan todos estos puntos:

- Cada invocación tiene `run_id` y registro persistente, incluso si falla.
- Ninguna ejecución omitida por lock se reporta como exitosa.
- Toda ejecución tiene inicio, fin/estado, duración, código de salida y log correlacionado.
- Timeout, interrupción y fallo de entrega son distinguibles.
- El éxito exige artefacto válido y el resultado de entrega cumple la política configurada.
- El PDF queda identificado por hash y no se confunde con un artefacto anterior.
- Existe consulta histórica y un procedimiento probado para reejecutar sin perder trazabilidad.
- Los reintentos están limitados, clasificados y no duplican entregas.
- Las pruebas cubren concurrencia, interrupciones, recuperación y regresiones de reportes.
- README, ejemplo de cron y runbook describen el comportamiento real.

## 6. Riesgos y decisiones que no deben darse por resueltas

- **NFS/multi-host:** `flock` y SQLite locales no constituyen una solución distribuida. Si los cron jobs se ejecutan en más de un host, se necesita otro diseño de coordinación.
- **Cron no es un scheduler durable:** no garantiza catch-up tras una caída del host. Para eso se requiere un watchdog o scheduler con persistencia y calendario explícito.
- **Entrega exactamente una vez:** SMTP y algunos canales no ofrecen garantías de idempotencia. El diseño debe reconocer estados ambiguos (p. ej. timeout después de que el proveedor aceptó el mensaje) y evitar afirmar entrega única sin evidencia.
- **Secretos:** los logs, el ledger y las notificaciones deben excluir credenciales, tokens, payloads sensibles y valores de entorno secretos.
- **Semántica de éxito:** decidir si un reporte generado pero no entregado es `SUCCEEDED_WITH_WARNINGS` o `FAILED_DELIVERY`; la recomendación es conservar dos dimensiones separadas (generación y entrega) y derivar el estado global por política.

---
Este documento es un plan de trabajo. Las casillas solo se marcarán al implementar y verificar cada tarea.
