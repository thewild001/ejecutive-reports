"""Pydantic models validating config.yaml before any network call happens.

Uso::

    from common.config_models import validate_config
    validate_config(cfg)  # SystemExit con todos los errores si es inválida

Los modelos son permisivos con claves extra (config crece por fases) pero
estrictos con tipos y valores de los campos conocidos.
"""
from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _Base(BaseModel):
    model_config = ConfigDict(extra="allow")


class CompanyConfig(_Base):
    name: str = ""
    unit: str = ""
    issued_by: str = ""
    logo_path: str = ""
    locale: str = "es"


class OutputConfig(_Base):
    dir: str = "./output"
    keep_last: int = Field(default=10, ge=1, le=1000)


class LoggingConfig(_Base):
    level: str = "INFO"
    file: str = ""
    max_bytes: int = Field(default=1_048_576, gt=0)
    backup_count: int = Field(default=3, ge=1)

    @field_validator("level")
    @classmethod
    def _level_valid(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        v = v.upper()
        if v not in allowed:
            raise ValueError(f"level debe ser uno de {sorted(allowed)}")
        return v


_URL_RE = re.compile(r"^https?://[^\s/$.?#].[^\s]*$", re.IGNORECASE)


def _check_url(v: str) -> str:
    if not _URL_RE.match(v):
        raise ValueError(f"URL inválida: {v!r} (se espera http(s)://...)")
    return v


class GesproConfig(_Base):
    enabled: bool = True
    base_url: str = ""
    api_key_env: str = "REDMINE_API_KEY"
    verify_ssl: bool = False
    project_ids: list[int | str] = Field(default_factory=list)
    closed_status_names: list[str] = Field(default_factory=list)
    previous_period_days: int = Field(default=30, ge=7, le=180)
    filename_prefix: str = "informe_gespro"
    timeout_seconds: float = Field(default=30.0, gt=0, le=300)

    @field_validator("base_url")
    @classmethod
    def _url(cls, v: str) -> str:
        return _check_url(v) if v else v


class GitlabConfig(_Base):
    enabled: bool = True
    base_url: str = ""
    token_env: str = "GITLAB_TOKEN"
    group: str = ""
    verify_ssl: bool = False
    max_projects: int = Field(default=25, ge=1, le=500)
    stale_branch_days: int = Field(default=60, ge=1)
    include_pipelines: bool = True
    include_merge_requests: bool = True
    activity_days: int = Field(default=90, ge=7, le=365)
    filename_prefix: str = "informe_gitlab"
    timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    # "portfolio" = resumen ejecutivo consolidado vía MCP (formato heredado);
    # "summary" = tabla resumida por REST (modo ligero, sin dependencias extra).
    mode: str = "portfolio"
    # Proyectos del portafolio: lista de rutas o {nombre: ruta}. Vacío = descubrir
    # los del grupo por la API (hasta max_projects).
    projects: list[str] | dict[str, str] = Field(default_factory=list)
    window_days: int = Field(default=2, ge=1, le=365)    # actividad reciente (colaboradores)
    trend_months: int = Field(default=12, ge=3, le=36)   # serie mensual de tendencia
    group_max_projects: int = Field(default=30, ge=1, le=500)
    group_min_activity_days: int = Field(default=90, ge=1)
    classification: str = ""                              # pie de página, p. ej. "USO INTERNO"
    # Comando del servidor MCP (stdio). Vacío = python mcp/gitlab_server.py --transport stdio.
    # Ej. Docker: ["docker","exec","-i","<contenedor>","python3","<server.py>","--transport","stdio"]
    mcp_command: list[str] = Field(default_factory=list)
    mcp_timeout_seconds: float = Field(default=90.0, gt=0, le=900)

    @field_validator("base_url")
    @classmethod
    def _url(cls, v: str) -> str:
        return _check_url(v) if v else v

    @field_validator("mode")
    @classmethod
    def _mode(cls, v: str) -> str:
        if v not in {"portfolio", "summary"}:
            raise ValueError("mode debe ser 'portfolio' o 'summary'")
        return v


class TrendsConfig(_Base):
    enabled: bool = True
    data_file: str = "trends/trends_data.json"
    header_title: str = "Vigilancia Tecnológica"
    filename_prefix: str = "informe_tendencias"
    rss_feeds: list[str] = Field(default_factory=list)
    # Si el JSON de datos es más viejo que esto, no se genera ni envía (0 = sin límite).
    max_age_days: int = Field(default=0, ge=0)

    @field_validator("rss_feeds")
    @classmethod
    def _urls(cls, v: list[str]) -> list[str]:
        return [_check_url(u) for u in v]


class EmailConfig(_Base):
    enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = Field(default=587, ge=1, le=65535)
    starttls: bool = True
    verify_ssl: bool = True
    user_env: str = "SMTP_USER"
    pass_env: str = "SMTP_PASS"
    sender: str = ""
    recipients: list[str] = Field(default_factory=list)
    ca_bundle: str = ""  # ruta a la CA interna (preferible a verify_ssl: false)
    # Plantillas por reporte: {"gespro": {"subject": "...", "body": "..."}, ...}
    messages: dict[str, dict[str, str]] = Field(default_factory=dict)


class TelegramConfig(_Base):
    enabled: bool = False
    bot_token_env: str = "TELEGRAM_BOT_TOKEN"
    chat_id_env: str = "TELEGRAM_CHAT_ID"


class DeliveryConfig(_Base):
    email: EmailConfig = Field(default_factory=EmailConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)


class CacheConfig(_Base):
    enabled: bool = False
    ttl_seconds: int = Field(default=3600, ge=60, le=604800)


class ExecutionConfig(_Base):
    max_workers: int = Field(default=4, ge=1, le=16)


class ExportConfig(_Base):
    formats: list[str] = Field(default_factory=lambda: ["pdf"])

    @field_validator("formats")
    @classmethod
    def _formats(cls, v: list[str]) -> list[str]:
        allowed = {"pdf", "csv", "json", "xlsx"}
        bad = [f for f in v if f not in allowed]
        if bad:
            raise ValueError(f"formatos no soportados: {bad} (válidos: {sorted(allowed)})")
        return v


class UiConfig(_Base):
    theme: str = "corporativo"


class PluginsConfig(_Base):
    enabled: list[str] = Field(default_factory=list)


class WebConfig(_Base):
    port: int = Field(default=8080, ge=1, le=65535)


class ReportsConfig(_Base):
    company: CompanyConfig = Field(default_factory=CompanyConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    export: ExportConfig = Field(default_factory=ExportConfig)
    ui: UiConfig = Field(default_factory=UiConfig)
    plugins: PluginsConfig = Field(default_factory=PluginsConfig)
    web: WebConfig = Field(default_factory=WebConfig)
    gespro: GesproConfig = Field(default_factory=GesproConfig)
    gitlab: GitlabConfig = Field(default_factory=GitlabConfig)
    trends: TrendsConfig = Field(default_factory=TrendsConfig)
    delivery: DeliveryConfig = Field(default_factory=DeliveryConfig)


def validate_config(cfg: dict) -> ReportsConfig:
    """Valida el dict de config.yaml. Sale con SystemExit y errores claros."""
    from pydantic import ValidationError

    try:
        return ReportsConfig.model_validate(cfg)
    except ValidationError as exc:
        lines = ["ERROR: config.yaml inválido. Corrige lo siguiente:"]
        for err in exc.errors():
            loc = ".".join(str(p) for p in err["loc"]) or "(raíz)"
            lines.append(f"  - {loc}: {err['msg']}")
        raise SystemExit("\n".join(lines)) from exc
