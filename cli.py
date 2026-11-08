#!/usr/bin/env python3
"""
REPORTS — CLI (Fase 4, Typer).

    python cli.py run gespro|gitlab|trends|all [--force] [--workers N] [--format csv,json]
    python cli.py validate
    python cli.py cache clear
    python cli.py rss-draft
    python cli.py init
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import typer

app = typer.Typer(help="REPORTS — suite de reportería ejecutiva.",
                  no_args_is_help=True)
cache_app = typer.Typer(help="Gestión de la caché de API.")
app.add_typer(cache_app, name="cache")

_RUNNERS = {
    "gespro": "gespro.gespro_report",
    "gitlab": "gitlab.gitlab_report",
    "trends": "trends.trends_report",
}


@app.command()
def run(
    report: str = typer.Argument(..., help="gespro | gitlab | trends | all"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Log en DEBUG"),
    force: bool = typer.Option(False, "--force", "-f", help="Ignora la caché de API"),
    workers: int = typer.Option(None, "--workers", "-w", help="Proyectos en paralelo"),
    formats: str = typer.Option(None, "--format", help="Exports extra: csv,json,xlsx"),
) -> None:
    """Genera uno o varios reportes (equivalente a run.sh, con overrides)."""
    import importlib

    import common.settings as settings
    orig_load = settings.load_config

    def load_with_overrides(config_path: str | None = None) -> dict:
        cfg = orig_load(config_path)
        if verbose:
            cfg["logging"]["level"] = "DEBUG"
        if force:
            cfg["cache"]["enabled"] = False
        if workers:
            cfg["execution"]["max_workers"] = workers
        if formats:
            cfg["export"]["formats"] = [f.strip() for f in formats.split(",")]
        return cfg

    settings.load_config = load_with_overrides

    targets = list(_RUNNERS) if report == "all" else [report]
    if any(r not in _RUNNERS for r in targets):
        typer.echo(f"Reporte desconocido: {report} (usa gespro|gitlab|trends|all)")
        raise typer.Exit(2)
    for name in targets:
        code = importlib.import_module(_RUNNERS[name]).main()
        if code:
            raise typer.Exit(code)


@app.command()
def validate() -> None:
    """Valida config.yaml y las variables de entorno sin generar reportes."""
    from common.settings import load_config
    cfg = load_config()
    typer.echo("config.yaml válido ✅")
    for section, key, default in (
        ("gespro", "api_key_env", "REDMINE_API_KEY"),
        ("gitlab", "token_env", "GITLAB_TOKEN"),
    ):
        if cfg.get(section, {}).get("enabled"):
            import os
            var = cfg[section].get(key, default)
            estado = "definida ✅" if os.environ.get(var) else "FALTA ❌"
            typer.echo(f"  {var}: {estado}")


@cache_app.command("clear")
def cache_clear() -> None:
    """Vacía la caché de respuestas de API."""
    from common.cache import ApiCache
    from common.settings import load_config
    cache = ApiCache.from_config(load_config())
    n = cache.clear()
    cache.close()
    typer.echo(f"Caché vaciada ({n} entradas).")


@app.command(name="rss-draft")
def rss_draft() -> None:
    """Genera trends/trends_draft.json desde los feeds RSS configurados."""
    from trends.rss_fetcher import main as rss_main
    raise typer.Exit(rss_main())


@app.command()
def init() -> None:
    """Asistente mínimo: prepara .env y muestra qué configurar."""
    import shutil
    root = Path(__file__).resolve().parent
    env = root / ".env"
    if env.exists():
        typer.echo(".env ya existe — no se sobrescribe.")
    else:
        example = root / ".env.example"
        if example.exists():
            shutil.copy(example, env)
            typer.echo(".env creado desde .env.example — edítalo con tus credenciales.")
        else:
            typer.echo("No hay .env.example; crea .env con las claves documentadas en README.")
    typer.echo("Siguiente: revisa config.yaml (empresa, URLs, proyectos) y ejecuta:")
    typer.echo("  python cli.py validate")


if __name__ == "__main__":
    app()
