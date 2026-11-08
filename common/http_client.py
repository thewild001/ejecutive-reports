"""Shared HTTP client factory with retry, backoff and safe error reporting.

Los wrappers de API (RedmineAPI, GitLabAPI) construyen su ``httpx.Client``
con :func:`build_client` y procesan respuestas con :func:`checked_json`,
que reintenta errores transitorios (5xx, red, timeout) con exponential
backoff y nunca reintenta errores 4xx.

Nunca se loggean headers (pueden contener tokens).
"""
from __future__ import annotations

import logging
import time

import httpx

log = logging.getLogger(__name__)

DEFAULT_RETRIES = 3
_BACKOFF_BASE = 1.0  # segundos; espera = base * 2**intento


class ApiError(RuntimeError):
    """Error de API no recuperable (tras reintentos o 4xx)."""

    def __init__(self, method: str, path: str, detail: str):
        super().__init__(f"{method} {path}: {detail}")
        self.method, self.path = method, path


def build_client(
    base_url: str,
    headers: dict[str, str] | None = None,
    verify_ssl: bool = True,
    timeout: float = 30.0,
    follow_redirects: bool = False,
) -> httpx.Client:
    """Crea un httpx.Client con base_url, headers y timeout configurables."""
    return httpx.Client(
        base_url=base_url.rstrip("/"),
        verify=verify_ssl,
        timeout=timeout,
        headers=headers or {},
        follow_redirects=follow_redirects,
    )


def _cache_key(path: str, params: dict | None) -> str:
    import hashlib
    import json as _json

    raw = path + _json.dumps(params or {}, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode()).hexdigest()


def checked_json(client: httpx.Client, path: str, params: dict | None = None,
                 cache=None) -> dict:
    """GET con retry/backoff. Devuelve JSON. Sin secretos en logs ni errores.

    - 4xx → error inmediato (no tiene sentido reintentar).
    - 5xx / error de red / timeout → hasta 3 intentos con backoff exponencial.
    - Si se pasa ``cache`` (common.cache.ApiCache), las respuestas exitosas
      se reutilizan hasta su TTL; los errores nunca se cachean.
    """
    if cache is not None and (hit := cache.get(_cache_key(path, params))):
        import json as _json
        return _json.loads(hit)

    last_error = ""
    for attempt in range(1, DEFAULT_RETRIES + 1):
        try:
            resp = client.get(path, params=params)
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
            last_error = f"error de red/timeout ({type(exc).__name__})"
            log.warning("GET %s falló (intento %d/%d): %s", path, attempt, DEFAULT_RETRIES, last_error)
            if attempt < DEFAULT_RETRIES:
                time.sleep(_BACKOFF_BASE * 2 ** (attempt - 1))
            continue

        if resp.status_code < 400:
            if cache is not None:
                cache.set(_cache_key(path, params), resp.text)
            return resp.json()

        status = resp.status_code
        if 400 <= status < 500:
            log.error("GET %s devolvió %d (error de cliente, no se reintenta)", path, status)
            raise ApiError("GET", path, f"HTTP {status}")

        last_error = f"HTTP {status} (error de servidor)"
        log.warning("GET %s devolvió %d (intento %d/%d)", path, status, attempt, DEFAULT_RETRIES)
        if attempt < DEFAULT_RETRIES:
            time.sleep(_BACKOFF_BASE * 2 ** (attempt - 1))

    raise ApiError("GET", path, f"{last_error} tras {DEFAULT_RETRIES} intentos")
