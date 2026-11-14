# Spec: Integración desacoplada de reportes preexistentes

**Número:** 005
**Slug:** integrar-reportes-aislados

---

## Status: Active
## Dominio: reports
## Fecha: 2026-09-14

## ADDED Requirements

### Requirement: Integrar reportes aislados por comportamiento real
La suite DEBE integrar los tres scripts aislados según el reporte que realmente generan, no según el nombre del archivo: `gitlab/generate_gitlab_report.py` aporta el informe GESPRO/Redmine detallado; `gespro/generate_redmine_report.py` aporta un resumen ejecutivo de salud GitLab; y `trends/tech_trends_v2.py` aporta el boletín premium dinámico de tendencias. Las ideas y formatos útiles DEBEN quedar integrados en los entry points canónicos existentes (`gespro/gespro_report.py`, `gitlab/gitlab_report.py`, `trends/trends_report.py`) sin cambiar la interfaz del crontab.

> Estado: integrado. Los generadores heredados viven ahora como `gespro/status_report.py`, `gitlab/portfolio_report.py` y `trends/tech_trends_v2.py`, parametrizados por `config.yaml`; los scripts originales se eliminaron (siguen en el historial de git).

#### Scenario: mantener entry points canónicos
- **WHEN** se ejecuta `run.sh gespro|gitlab|trends` o `python3 cli.py run all`
- **THEN** los reportes usan la lógica integrada sin invocar los scripts aislados

#### Scenario: evitar código duplicado
- **WHEN** una capacidad aislada queda migrada al generador canónico correspondiente
- **THEN** el script aislado deja de ser necesario y se retira del árbol de ejecución

### Requirement: Parametrizar informe GESPRO detallado
El informe GESPRO DEBE conservar el contenido del script aislado: portada, resumen general, indicadores consolidados, distribución de salud, recomendaciones por proyecto, tabla de miembros, análisis por proyecto y resumen ejecutivo consolidado. La URL de Redmine, la API key, los IDs de proyecto, estados cerrados, prefijo de archivo y directorio de salida DEBEN provenir de `config.yaml` y variables de entorno ya soportadas por la suite.

#### Scenario: valores configurables
- **WHEN** se cambian `gespro.base_url`, `gespro.project_ids`, `gespro.filename_prefix` o `output.dir`
- **THEN** el reporte detallado usa esos valores sin editar código Python

#### Scenario: credenciales ausentes
- **WHEN** falta `REDMINE_API_KEY` o la variable configurada en `gespro.api_key_env`
- **THEN** la ejecución falla antes de llamar a Redmine con un mensaje accionable y sin imprimir secretos

### Requirement: Parametrizar resumen ejecutivo GitLab
El informe GitLab DEBE incorporar la presentación del script aislado en forma de resumen ejecutivo de grupo con datos reales obtenidos por la integración GitLab existente: proyectos activos, pipelines, ramas totales/stale, issues, MRs y última actividad. El grupo, cantidad máxima de proyectos, umbrales y salida DEBEN provenir de la configuración existente. No se debe depender de `docker`, de un contenedor MCP ni de rutas absolutas del entorno local.

#### Scenario: resumen generado desde API REST
- **WHEN** se ejecuta el reporte GitLab con un grupo configurado
- **THEN** el resumen se construye con los datos recolectados por `gitlab_report.py` sin invocar procesos externos

#### Scenario: métricas parciales
- **WHEN** pipelines, issues, ramas o MRs no están disponibles para un proyecto
- **THEN** el reporte muestra el valor como no disponible para ese proyecto y continúa con los demás proyectos

### Requirement: Soportar boletín premium dinámico de tendencias
El reporte de tendencias DEBE soportar el esquema v2 (`metadata`, `executive_summary`, `sources_count`, `total_signals`, `top_signals`, `other_signals`) además del esquema actual (`periodo`, `resumen_ejecutivo`, `secciones`). Para el esquema v2 DEBE agrupar señales por categorías canónicas, omitir temáticas sin señales y mantener la presentación premium de portada, tarjetas, badges y resumen dinámico. La ruta del JSON, la ruta opcional del logo, el autor y la salida DEBEN ser configurables.

#### Scenario: esquema v2 con señales
- **WHEN** `trends.data_file` apunta a un JSON v2 con señales reales
- **THEN** se genera el boletín premium con solo las temáticas presentes

#### Scenario: esquema clásico existente
- **WHEN** `trends.data_file` apunta al JSON clásico actual
- **THEN** se mantiene el flujo ya verificado del boletín actual sin exigir cambios de datos

### Requirement: Endurecer secretos y configuración
Ningún valor sensible contenido en los scripts aislados DEBE copiarse al código integrado ni al historial Git. La integración DEBE usar exclusivamente nombres de variables de entorno (`*_env`) y ejemplos vacíos en `.env.example`. Los archivos aislados con credenciales o rutas hardcodeadas DEBEN quedar excluidos del versionado y retirarse del árbol de ejecución.

#### Scenario: revisión de seguridad
- **WHEN** se revisa el resultado integrado
- **THEN** no existen tokens, API keys ni contraseñas literales en archivos rastreables

#### Scenario: historial inicial seguro
- **WHEN** se complete el versionado inicial
- **THEN** ningún commit contiene la API key incluida accidentalmente por el usuario

## Contexto (opcional, no se mergea al system-spec)

Los tres scripts llegaron como utilidades aisladas con formato visual valorado por el usuario, pero también contienen rutas absolutas, nombres FORTES hardcodeados, JSON de ejemplo y una API key embebida. La integración debe conservar su valor visual/informativo sin romper la arquitectura de REPORTS ni comprometer credenciales. Durante el análisis se detectó que los nombres de archivo no coinciden con su dominio real: el script en `gespro/` genera salud GitLab y el script en `gitlab/` genera el informe GESPRO/Redmine.
