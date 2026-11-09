"""
GESPRO MCP Server
Connects to any Redmine-based instance (GESPRO compatible).
Provides tools to query projects, members, tasks, and member status.

Configuration via environment variables (see .env.example):
  GESPRO_URL, GESPRO_API_KEY, GESPRO_VERIFY_SSL, GESPRO_TIMEOUT,
  GESPRO_DEFAULT_LIMIT, GESPRO_PROJECT_FILTER
"""

import concurrent.futures
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

# Logging SIEMPRE a stderr: stdout queda puro para el protocolo MCP.
# Nunca se registra la API key.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("gespro-mcp")

try:
    from dotenv import load_dotenv

    _env_path = Path(__file__).parent / ".env"
    load_dotenv(_env_path if _env_path.exists() else None)
except ImportError:
    pass


def _parse_bool(value: Optional[str], default: bool) -> bool:
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _parse_float(value: Optional[str], default: float) -> float:
    try:
        return float(str(value).strip()) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _parse_int(value: Optional[str], default: int) -> int:
    try:
        return int(float(str(value).strip())) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


# Configuration (sin secretos quemados; todo via entorno)
GESPRO_URL = os.getenv("GESPRO_URL", "https://redmine.example.com/")
GESPRO_API_KEY = os.getenv("GESPRO_API_KEY", "")
GESPRO_VERIFY_SSL = _parse_bool(os.getenv("GESPRO_VERIFY_SSL"), True)
GESPRO_TIMEOUT = _parse_float(os.getenv("GESPRO_TIMEOUT"), 30.0)
GESPRO_DEFAULT_LIMIT = _parse_int(os.getenv("GESPRO_DEFAULT_LIMIT"), 50)

# Filtro opcional de proyectos: ids o identifiers separados por coma.
# Vacio/ausente = sin restriccion (comportamiento original).
GESPRO_PROJECT_FILTER = os.getenv("GESPRO_PROJECT_FILTER", "")


_ALLOWLIST_CACHE: Optional[Optional[set[str]]] = None
_ALLOWLIST_IDS: Optional[set[int]] = None


def _project_allowlist() -> Optional[set[str]]:
    """Devuelve el conjunto de tokens (ids o identifiers) permitidos.

    None = sin restriccion. Cache en modulo para no recomputar.
    """
    global _ALLOWLIST_CACHE
    if _ALLOWLIST_CACHE is not None:
        return _ALLOWLIST_CACHE
    raw = GESPRO_PROJECT_FILTER or ""
    tokens = {t.strip() for t in raw.split(",") if t.strip()}
    _ALLOWLIST_CACHE = tokens or None
    return _ALLOWLIST_CACHE


def _allowlist_ids() -> Optional[set[int]]:
    """Resuelve identifiers -> ids consultando list_projects de Redmine (lazy, cacheado).

    Devuelve None si no hay filtro activo. Los tokens numericos se conservan
    como ids aunque no existan en la instancia.
    """
    global _ALLOWLIST_IDS
    if _ALLOWLIST_IDS is not None:
        return _ALLOWLIST_IDS
    tokens = _project_allowlist()
    if tokens is None:
        return None
    ids: set[int] = set()
    identifiers: set[str] = set()
    for tok in tokens:
        if tok.isdigit():
            ids.add(int(tok))
        else:
            identifiers.add(tok)
    if identifiers:
        try:
            for p in redmine.get_projects():
                if (p.identifier or "") in identifiers:
                    ids.add(int(p.id))
        except Exception as e:
            logger.warning("No se pudieron resolver identifiers del filtro: %s", e)
    _ALLOWLIST_IDS = ids
    logger.info("GESPRO_PROJECT_FILTER activo: %d proyecto(s) permitidos", len(ids))
    return ids


def _project_allowed(project_id: int) -> bool:
    """True si el proyecto esta permitido por GESPRO_PROJECT_FILTER."""
    ids = _allowlist_ids()
    if ids is None:
        return True
    return int(project_id) in ids


def _check_project_allowed(project_id: int) -> None:
    """Lanza RuntimeError si el proyecto no esta en el allowlist activo."""
    if not _project_allowed(project_id):
        raise RuntimeError(
            f"Proyecto {project_id} no esta permitido por GESPRO_PROJECT_FILTER"
        )


def _resolve_project_id(project_id: Any) -> int:
    """Valida y resuelve project_id (numerico) aplicando el allowlist."""
    pid = _require_id(project_id, "project_id")
    _check_project_allowed(pid)
    return pid

# Fail-fast al arrancar: mensaje claro, sin traceback criptico.
# Se evalua antes de importar dependencias de terceros para que el
# mensaje sea visible incluso sin `pip install -r requirements.txt`.
if not GESPRO_API_KEY:
    raise SystemExit(
        "GESPRO_API_KEY no esta configurada. "
        "Copie .env.example a .env y defina GESPRO_API_KEY."
    )
if not GESPRO_URL:
    raise SystemExit(
        "GESPRO_URL no esta configurada. "
        "Copie .env.example a .env y defina GESPRO_URL."
    )

try:
    from fastmcp import FastMCP
    from redmine_client import RedmineClient as Redmine
    from redmine_client.exceptions import (
        RedmineNotFoundError as ResourceNotFoundError,
        RedmineError as ServerError,
    )
    from pydantic import BaseModel
except ImportError as exc:
    raise SystemExit(
        f"Falta una dependencia ({exc.name}). "
        "Ejecute: pip install -r requirements.txt"
    ) from None

logger.info(
    "Configuracion: url=%s verify_ssl=%s timeout=%s default_limit=%s",
    GESPRO_URL,
    GESPRO_VERIFY_SSL,
    GESPRO_TIMEOUT,
    GESPRO_DEFAULT_LIMIT,
)
_allowlist_tokens = _project_allowlist()
if _allowlist_tokens is not None:
    logger.info(
        "GESPRO_PROJECT_FILTER configurado: %d token(s) en allowlist",
        len(_allowlist_tokens),
    )


def create_redmine_client(url: str, api_key: str, timeout: float, verify_ssl: bool) -> Redmine:
    """Fabrica del cliente Redmine que respeta VERIFY_SSL.

    Reemplaza el antiguo monkey-patch global que forzaba verify=False:
    el cliente httpx subyacente se configura por instancia segun
    GESPRO_VERIFY_SSL. Con verify=False se registra un aviso porque
    desactiva la verificacion TLS (aceptable con certificados autofirmados).
    """
    import httpx

    if not verify_ssl:
        logger.warning(
            "Verificacion SSL desactivada (GESPRO_VERIFY_SSL=false). "
            "Uselo solo con certificados autofirmados en red de confianza."
        )
    client = Redmine(url, api_key=api_key, timeout=timeout)
    client._client = httpx.Client(
        base_url=client.base_url,
        verify=verify_ssl,
        timeout=timeout,
        headers={
            "X-Redmine-API-Key": api_key,
            "Content-Type": "application/json",
        },
    )
    return client


# Initialize Redmine client
redmine = create_redmine_client(
    GESPRO_URL, api_key=GESPRO_API_KEY, timeout=GESPRO_TIMEOUT, verify_ssl=GESPRO_VERIFY_SSL
)

# Initialize FastMCP
mcp = FastMCP("gespro-mcp")


class ProjectInfo(BaseModel):
    id: int
    name: str
    identifier: str
    description: Optional[str] = None
    status: int
    created_on: str
    updated_on: str


class MemberInfo(BaseModel):
    id: int
    name: str
    login: Optional[str] = None
    mail: Optional[str] = None
    roles: list[str] = []


class TaskInfo(BaseModel):
    id: int
    subject: str
    status: str
    priority: str
    tracker: str
    assigned_to: Optional[str] = None
    author: Optional[str] = None
    created_on: str
    updated_on: str
    due_date: Optional[str] = None
    estimated_hours: Optional[float] = None
    spent_hours: Optional[float] = None
    done_ratio: int = 0


class MemberStatus(BaseModel):
    member: MemberInfo
    project: ProjectInfo
    tasks_assigned: list[TaskInfo]
    total_tasks: int
    open_tasks: int
    closed_tasks: int
    total_estimated_hours: float
    total_spent_hours: float


# Fallback cuando el objeto de estado no expone is_closed
CLOSED_STATUS_NAMES = {
    "closed",
    "resolved",
    "rechazado",
    "rejected",
    "cerrada",
    "cerrado",
    "resuelta",
    "resuelto",
}


def _issue_due_date(issue) -> Optional[str]:
    """Mapea el valor real de due_date del issue (antes siempre None)."""
    due = getattr(issue, "due_date", None)
    if due is None:
        return None
    return str(due)


def _issue_is_closed(issue, status_name: str) -> bool:
    """Prefiere el atributo is_closed del estado; si no existe, usa la lista."""
    for candidate in (
        getattr(getattr(issue, "status", None), "is_closed", None),
        getattr(issue, "is_closed", None),
    ):
        if isinstance(candidate, bool):
            return candidate
    return (status_name or "").strip().lower() in CLOSED_STATUS_NAMES


def _issue_to_task(issue) -> TaskInfo:
    return TaskInfo(
        id=issue.id,
        subject=issue.subject,
        status=issue.status_name or "",
        priority=issue.priority_name or "",
        tracker=issue.tracker_name or "",
        assigned_to=issue.assigned_to_name,
        author=issue.author_name,
        created_on=issue.created_on or "",
        updated_on=issue.updated_on or "",
        due_date=_issue_due_date(issue),
        estimated_hours=issue.estimated_hours,
        spent_hours=issue.spent_hours,
        done_ratio=issue.done_ratio or 0,
    )


@mcp.tool()
def list_projects(
    include_inactive: bool = False, limit: Optional[int] = None
) -> list[ProjectInfo]:
    """
    List all projects in GESPRO.

    When GESPRO_PROJECT_FILTER is set, the result is the intersection with
    the allowlist (matched by id or identifier).

    Args:
        include_inactive: Whether to include closed/archived projects (default: False)
        limit: Maximum number of projects to return (optional, no limit by default)

    Returns:
        List of projects with basic info
    """
    try:
        projects = redmine.get_projects()
        allowlist_ids = _allowlist_ids()
        result = []
        for p in projects:
            if not include_inactive and p.status != 1:  # 1 = active
                continue
            if allowlist_ids is not None and int(p.id) not in allowlist_ids:
                continue
            result.append(ProjectInfo(
                id=p.id,
                name=p.name,
                identifier=p.identifier or "",
                description=p.description,
                status=p.status or 1,
                created_on=p.created_on or "",
                updated_on=p.updated_on or ""
            ))
        if limit is not None:
            result = result[:limit]
        return result
    except Exception as e:
        raise RuntimeError(f"Failed to list projects: {str(e)}") from e


@mcp.tool()
def get_project(project_id: int) -> ProjectInfo:
    """
    Get detailed information about a specific project.

    Args:
        project_id: The numeric ID of the project

    Returns:
        Project details
    """
    _check_project_allowed(project_id)
    try:
        p = redmine.get_project(project_id)
        return ProjectInfo(
            id=p.id,
            name=p.name,
            identifier=p.identifier,
            description=getattr(p, 'description', None),
            status=p.status,
            created_on=str(p.created_on) if hasattr(p, 'created_on') else "",
            updated_on=str(p.updated_on) if hasattr(p, 'updated_on') else ""
        )
    except ResourceNotFoundError:
        raise RuntimeError(f"Project {project_id} not found") from None
    except Exception as e:
        raise RuntimeError(f"Failed to get project: {str(e)}") from e


@mcp.tool()
def get_project_members(project_id: int) -> list[MemberInfo]:
    """
    Get all members of a project with their roles.

    Args:
        project_id: The numeric ID of the project

    Returns:
        List of members with their roles in the project
    """
    _check_project_allowed(project_id)
    try:
        # Use the memberships endpoint directly since redmine_client doesn't support include=['memberships']
        response = redmine._get(f"/projects/{project_id}/memberships.json")
        memberships = response.get("memberships", [])

        members = []
        for membership in memberships:
            # Membership can have either 'user' or 'group' - we only want users
            if "user" in membership:
                user = membership["user"]
                roles = [role["name"] for role in membership.get("roles", [])]
                members.append(MemberInfo(
                    id=user["id"],
                    name=user["name"],
                    login=None,  # Not available in memberships endpoint
                    mail=None,   # Not available in memberships endpoint
                    roles=roles
                ))
        return members
    except ResourceNotFoundError:
        raise RuntimeError(f"Project {project_id} not found") from None
    except Exception as e:
        raise RuntimeError(f"Failed to get project members: {str(e)}") from e


@mcp.tool()
def get_member_tasks(project_id: int, user_id: int) -> list[TaskInfo]:
    """
    Get all tasks assigned to a specific member in a project.

    Args:
        project_id: The numeric ID of the project
        user_id: The numeric ID of the user/member

    Returns:
        List of tasks assigned to the member in the project
    """
    _check_project_allowed(project_id)
    try:
        issues = redmine.get_issues(project_id=project_id, assigned_to_id=user_id)
        return [_issue_to_task(issue) for issue in issues]
    except Exception as e:
        raise RuntimeError(f"Failed to get member tasks: {str(e)}") from e


@mcp.tool()
def get_member_status(project_id: int, user_id: int) -> MemberStatus:
    """
    Get comprehensive status of a member in a project including all assigned tasks and statistics.

    Args:
        project_id: The numeric ID of the project
        user_id: The numeric ID of the user/member

    Returns:
        Member status with tasks and statistics
    """
    _check_project_allowed(project_id)
    try:
        # Get project info
        project = redmine.get_project(project_id)
        project_info = ProjectInfo(
            id=project.id,
            name=project.name,
            identifier=project.identifier or "",
            description=getattr(project, 'description', None),
            status=project.status or 1,
            created_on=project.created_on or "",
            updated_on=project.updated_on or ""
        )

        # Get member info from memberships
        response = redmine._get(f"/projects/{project_id}/memberships.json")
        memberships = response.get("memberships", [])
        member_info = None
        for m in memberships:
            user = m.get("user", {})
            if user.get("id") == user_id:
                roles = [role.get("name", "") for role in m.get("roles", [])]
                member_info = MemberInfo(
                    id=user["id"],
                    name=user["name"],
                    login=user.get("login"),
                    mail=None,
                    roles=roles
                )
                break

        if not member_info:
            raise RuntimeError(f"User {user_id} is not a member of project {project_id}")

        # Get raw issues to compute is_closed from the status attribute
        issues = list(redmine.get_issues(project_id=project_id, assigned_to_id=user_id))
        tasks = [_issue_to_task(issue) for issue in issues]

        # Calculate statistics
        total_tasks = len(tasks)
        closed_tasks = sum(
            1 for issue, task in zip(issues, tasks) if _issue_is_closed(issue, task.status)
        )
        open_tasks = total_tasks - closed_tasks
        total_estimated = sum(t.estimated_hours or 0 for t in tasks)
        total_spent = sum(t.spent_hours or 0 for t in tasks)

        return MemberStatus(
            member=member_info,
            project=project_info,
            tasks_assigned=tasks,
            total_tasks=total_tasks,
            open_tasks=open_tasks,
            closed_tasks=closed_tasks,
            total_estimated_hours=total_estimated,
            total_spent_hours=total_spent
        )
    except Exception as e:
        raise RuntimeError(f"Failed to get member status: {str(e)}") from e


@mcp.tool()
def get_all_members_status(project_id: int) -> list[MemberStatus]:
    """
    Get status of all members in a project.

    Args:
        project_id: The numeric ID of the project

    Returns:
        List of member statuses with their tasks and statistics
    """
    _check_project_allowed(project_id)
    try:
        members = get_project_members(project_id)

        # Consultas en paralelo (max 5 hilos); executor.map preserva el orden
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            results = list(
                executor.map(
                    lambda member: get_member_status(project_id, member.id),
                    members,
                )
            )

        return results
    except Exception as e:
        raise RuntimeError(f"Failed to get all members status: {str(e)}") from e


@mcp.tool()
def search_issues(project_id: Optional[int] = None,
                  status: Optional[str] = None,
                  assigned_to_id: Optional[int] = None,
                  tracker: Optional[str] = None,
                  limit: Optional[int] = None,
                  offset: int = 0) -> list[TaskInfo]:
    """
    Search issues/tasks with filters.

    When GESPRO_PROJECT_FILTER is active and project_id is omitted, the
    search is implicitly restricted to the allowed projects (server-side
    filter with the allowlist ids joined by ','). If project_id is given
    but not allowed, a RuntimeError is raised.

    Args:
        project_id: Filter by project (optional)
        status: Filter by status name (e.g., 'open', 'closed') (optional)
        assigned_to_id: Filter by assignee user ID (optional)
        tracker: Filter by tracker name (e.g., 'Bug', 'Feature') (optional)
        limit: Maximum results to return (default: GESPRO_DEFAULT_LIMIT)
        offset: Number of results to skip for pagination (default: 0)

    Returns:
        List of matching tasks
    """
    try:
        effective_limit = limit if limit is not None else GESPRO_DEFAULT_LIMIT
        params: dict = {"limit": max(1, int(effective_limit)), "offset": max(0, int(offset))}
        if project_id:
            _check_project_allowed(project_id)
            params['project_id'] = project_id
        else:
            allowlist_ids = _allowlist_ids()
            if allowlist_ids is not None:
                if not allowlist_ids:
                    return []
                params['project_id'] = ",".join(str(i) for i in sorted(allowlist_ids))
        if status:
            params['status_id'] = status
        if assigned_to_id:
            params['assigned_to_id'] = assigned_to_id
        if tracker:
            params['tracker_id'] = tracker

        # Raw single-page call: redmine_client.get_issues pagina TODO
        # internamente (ignora el limit como page-size y sigue hasta agotar),
        # lo que causaba 500+ requests con limit=1. Aqui limit/offset se
        # respetan server-side y se convierte via _dict_to_task (incluye
        # due_date real, que el wrapper descarta).
        resp = _raw_get("/issues.json", params)
        return [_dict_to_task(d) for d in resp.get("issues", []) or []]
    except Exception as e:
        raise RuntimeError(f"Failed to search issues: {str(e)}") from e


@mcp.tool()
def get_users() -> list[MemberInfo]:
    """
    Get all users in GESPRO.

    Returns:
        List of all users
    """
    try:
        users = redmine.get_users()
        result = []
        for u in users:
            result.append(MemberInfo(
                id=u.id,
                name=u.full_name,
                login=getattr(u, 'login', None),
                mail=getattr(u, 'mail', None),
                roles=[]
            ))
        return result
    except Exception as e:
        raise RuntimeError(f"Failed to get users: {str(e)}") from e


# ---------------------------------------------------------------------------
# Gestion tools (T1-T5): pulso, planificacion, carga, flujo/catalogos, escritura
#
# Nota: redmine_client.RedmineIssue no expone due_date/closed_on/is_closed
# (from_api_response los descarta), por eso las herramientas basadas en fechas
# usan REST crudo (redmine._get) con paginacion defensiva en lugar del wrapper.
# Nunca se registra la API key. Fechas ISO YYYY-MM-DD.
# ---------------------------------------------------------------------------

RAW_PAGE_SIZE = 100
RAW_MAX_TOTAL = 500
RECENT_ACTIVITY_CAP = 50


class VersionInfo(BaseModel):
    id: int
    name: str
    status: str = ""
    due_date: Optional[str] = None
    description: Optional[str] = None
    share: Optional[str] = None


class ActivitySummary(BaseModel):
    project_id: int
    since: str
    created: int = 0
    closed: int = 0
    updated: list[TaskInfo] = []


class IssueDetail(TaskInfo):
    description: str = ""
    children: list[int] = []
    relations: list[dict] = []
    journals_count: int = 0


class WorkloadEntry(BaseModel):
    member: MemberInfo
    open_tasks: int = 0
    overdue_tasks: int = 0
    estimated_hours: float = 0.0
    spent_hours: float = 0.0


class TimeEntryInfo(BaseModel):
    id: int
    issue_id: Optional[int] = None
    user: str = ""
    hours: float = 0.0
    activity: str = ""
    comments: Optional[str] = None
    spent_on: Optional[str] = None


class TrackerStats(BaseModel):
    tracker: str
    open: int = 0
    closed: int = 0
    total: int = 0
    avg_close_days: Optional[float] = None


def _raw_get(path: str, params: Optional[dict] = None) -> dict:
    """GET crudo defensivo: usa redmine._get; si falta, cae a httpx."""
    getter = getattr(redmine, "_get", None)
    if callable(getter):
        return getter(path, params or {})
    resp = redmine.client.get(path, params=params or {})
    resp.raise_for_status()
    return resp.json() if resp.content else {}


def _raw_post(path: str, payload: dict) -> dict:
    """POST crudo defensivo: usa redmine._post; si falta, cae a httpx."""
    poster = getattr(redmine, "_post", None)
    if callable(poster):
        return poster(path, payload)
    resp = redmine.client.post(path, json=payload)
    resp.raise_for_status()
    return resp.json() if resp.content else {}


def _raw_put(path: str, payload: dict) -> dict:
    """PUT crudo defensivo: usa redmine._put; si falta, cae a httpx."""
    putter = getattr(redmine, "_put", None)
    if callable(putter):
        return putter(path, payload)
    resp = redmine.client.put(path, json=payload)
    resp.raise_for_status()
    return resp.json() if resp.content else {}


def _parse_date(value: Any) -> Optional[date]:
    """Parsea YYYY-MM-DD (o prefijo de ISO datetime); None si no parsea."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _require_date(value: Optional[str], field: str) -> Optional[str]:
    """Valida fecha estricta YYYY-MM-DD; lanza RuntimeError si es invalida."""
    if value is None:
        return None
    parsed = _parse_date(value)
    if parsed is None or str(value).strip() != parsed.isoformat():
        raise RuntimeError(
            f"Invalid {field}: expected YYYY-MM-DD, got {value!r}"
        )
    return parsed.isoformat()


def _require_id(value: Any, field: str) -> int:
    """Valida ID entero positivo; lanza RuntimeError si es invalido."""
    try:
        ivalue = int(value)
    except (TypeError, ValueError):
        raise RuntimeError(f"Invalid {field}: expected positive int") from None
    if ivalue <= 0:
        raise RuntimeError(f"Invalid {field}: expected positive int")
    return ivalue


def _status_is_closed_dict(status: Any, status_name: str) -> bool:
    """is_closed desde dict crudo; si no hay flag, usa CLOSED_STATUS_NAMES."""
    if isinstance(status, dict) and isinstance(status.get("is_closed"), bool):
        return status["is_closed"]
    return (status_name or "").strip().lower() in CLOSED_STATUS_NAMES


def _dict_to_task(d: dict) -> TaskInfo:
    """Convierte un issue crudo (dict REST) a TaskInfo."""
    status = d.get("status") or {}
    tracker = d.get("tracker") or {}
    priority = d.get("priority") or {}
    assigned = d.get("assigned_to") or {}
    author = d.get("author") or {}
    try:
        estimated = (
            float(d["estimated_hours"])
            if d.get("estimated_hours") is not None
            else None
        )
    except (TypeError, ValueError):
        estimated = None
    try:
        spent = (
            float(d["spent_hours"]) if d.get("spent_hours") is not None else None
        )
    except (TypeError, ValueError):
        spent = None
    try:
        done = int(d.get("done_ratio") or 0)
    except (TypeError, ValueError):
        done = 0
    due = d.get("due_date")
    return TaskInfo(
        id=int(d.get("id", 0)),
        subject=str(d.get("subject", "")),
        status=str(status.get("name", "")),
        priority=str(priority.get("name", "")),
        tracker=str(tracker.get("name", "")),
        assigned_to=assigned.get("name"),
        author=author.get("name"),
        created_on=str(d.get("created_on") or ""),
        updated_on=str(d.get("updated_on") or ""),
        due_date=str(due) if due else None,
        estimated_hours=estimated,
        spent_hours=spent,
        done_ratio=done,
    )


def _fetch_raw_issues(
    project_id: int,
    status_id: Any = "*",
    extra: Optional[dict] = None,
    per_page: int = RAW_PAGE_SIZE,
    max_total: int = RAW_MAX_TOTAL,
    sort: Optional[str] = None,
) -> list[dict]:
    """Fetch paginado crudo de /issues.json (loop offset hasta < pagina o max)."""
    issues: list[dict] = []
    offset = 0
    while True:
        params: dict[str, Any] = {
            "project_id": project_id,
            "status_id": status_id,
            "limit": per_page,
            "offset": offset,
        }
        if sort:
            params["sort"] = sort
        if extra:
            params.update(extra)
        resp = _raw_get("/issues.json", params)
        batch = resp.get("issues", []) or []
        issues.extend(batch)
        total = resp.get("total_count", offset + len(batch))
        if (
            len(batch) < per_page
            or len(issues) >= max_total
            or len(issues) >= total
        ):
            break
        offset += per_page
    return issues[:max_total]


# ----------------------------- T1 Pulso ------------------------------------


@mcp.tool()
def get_overdue_issues(
    project_id: int, limit: int = 50
) -> list[TaskInfo]:
    """
    Open issues of a project with due_date before today (overdue).

    Args:
        project_id: The numeric ID of the project
        limit: Maximum overdue issues to return (default: 50)

    Returns:
        Overdue open issues as TaskInfo, ordered by due_date ascending

    Example:
        get_overdue_issues(project_id=1)
    """
    _require_id(project_id, "project_id")
    _check_project_allowed(project_id)
    try:
        raw = _fetch_raw_issues(project_id, status_id="open", sort="due_date")
        today = date.today()
        result: list[TaskInfo] = []
        for d in raw:
            due = _parse_date(d.get("due_date"))
            if due is None or due >= today:
                continue
            status = d.get("status") or {}
            if _status_is_closed_dict(status, status.get("name", "")):
                continue
            result.append(_dict_to_task(d))
            if len(result) >= limit:
                break
        return result
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Failed to get overdue issues: {str(e)}") from e


@mcp.tool()
def get_recent_activity(
    project_id: int, days: int = 7
) -> ActivitySummary:
    """
    Activity pulse of a project: created/closed counts plus updated issues.

    Args:
        project_id: The numeric ID of the project
        days: Lookback window in days (default: 7)

    Returns:
        ActivitySummary with since date, created/closed counts and updated issues

    Example:
        get_recent_activity(project_id=1, days=7)
    """
    _require_id(project_id, "project_id")
    _check_project_allowed(project_id)
    try:
        since_date = date.today() - timedelta(days=max(int(days), 0))
        since = since_date.isoformat()
        raw = _fetch_raw_issues(
            project_id,
            status_id="*",
            extra={"updated_on": f">={since}"},
            sort="updated_on:desc",
        )
        created = 0
        closed = 0
        updated: list[TaskInfo] = []
        for d in raw:
            if (
                _parse_date(d.get("created_on")) is not None
                and _parse_date(d.get("created_on")) >= since_date
            ):
                created += 1
            status = d.get("status") or {}
            if _status_is_closed_dict(status, status.get("name", "")):
                ref = _parse_date(d.get("closed_on")) or _parse_date(
                    d.get("updated_on")
                )
                if ref is not None and ref >= since_date:
                    closed += 1
            updated.append(_dict_to_task(d))
        return ActivitySummary(
            project_id=project_id,
            since=since,
            created=created,
            closed=closed,
            updated=updated[:RECENT_ACTIVITY_CAP],
        )
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Failed to get recent activity: {str(e)}") from e


@mcp.tool()
def get_stalled_issues(
    project_id: int, days: int = 14, limit: int = 50
) -> list[TaskInfo]:
    """
    Open issues with no update for more than `days` days (stalled).

    Args:
        project_id: The numeric ID of the project
        days: Inactivity threshold in days (default: 14)
        limit: Maximum stalled issues to return (default: 50)

    Returns:
        Stalled open issues as TaskInfo, oldest update first

    Example:
        get_stalled_issues(project_id=1, days=14)
    """
    _require_id(project_id, "project_id")
    _check_project_allowed(project_id)
    try:
        cutoff = date.today() - timedelta(days=max(int(days), 0))
        raw = _fetch_raw_issues(project_id, status_id="open")
        stalled: list[tuple[date, dict]] = []
        for d in raw:
            upd = _parse_date(d.get("updated_on"))
            if upd is None or upd >= cutoff:
                continue
            stalled.append((upd, d))
        stalled.sort(key=lambda item: item[0])
        return [_dict_to_task(d) for _, d in stalled[:limit]]
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Failed to get stalled issues: {str(e)}") from e


# ------------------------- T2 Planificacion --------------------------------


@mcp.tool()
def get_versions(project_id: int) -> list[VersionInfo]:
    """
    List roadmap versions (milestones) of a project.

    Args:
        project_id: The numeric ID of the project

    Returns:
        List of versions with status and due date

    Example:
        get_versions(project_id=1)
    """
    _require_id(project_id, "project_id")
    _check_project_allowed(project_id)
    try:
        resp = _raw_get(f"/projects/{project_id}/versions.json")
        result = []
        for v in resp.get("versions", []) or []:
            result.append(
                VersionInfo(
                    id=int(v.get("id", 0)),
                    name=str(v.get("name", "")),
                    status=str(v.get("status", "")),
                    due_date=v.get("due_date"),
                    description=v.get("description"),
                    share=v.get("sharing"),
                )
            )
        return result
    except ResourceNotFoundError:
        raise RuntimeError(f"Project {project_id} not found") from None
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Failed to get versions: {str(e)}") from e


@mcp.tool()
def get_issue_details(issue_id: int) -> IssueDetail:
    """
    Full detail of an issue including children, relations and journal count.

    Args:
        issue_id: The numeric ID of the issue

    Returns:
        IssueDetail extending TaskInfo with description, children IDs,
        relations and journals count

    Example:
        get_issue_details(issue_id=42)
    """
    _require_id(issue_id, "issue_id")
    try:
        resp = _raw_get(
            f"/issues/{issue_id}.json",
            {"include": "children,relations,journals"},
        )
        d = resp.get("issue", {})
        if not d:
            raise RuntimeError(f"Issue {issue_id} not found")
        base = _dict_to_task(d)
        children = [
            c["id"]
            for c in (d.get("children") or [])
            if isinstance(c, dict) and c.get("id") is not None
        ]
        relations = d.get("relations") or []
        journals = d.get("journals") or []
        return IssueDetail(
            **base.model_dump(),
            description=str(d.get("description") or ""),
            children=[int(c) for c in children],
            relations=list(relations),
            journals_count=len(journals),
        )
    except ResourceNotFoundError:
        raise RuntimeError(f"Issue {issue_id} not found") from None
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Failed to get issue details: {str(e)}") from e


@mcp.tool()
def get_upcoming_deadlines(
    project_id: int, days: int = 14, limit: int = 50
) -> list[TaskInfo]:
    """
    Open issues due within the next `days` days, sorted by due_date.

    Args:
        project_id: The numeric ID of the project
        days: Forward window in days (default: 14)
        limit: Maximum issues to return (default: 50)

    Returns:
        Open issues with due_date in [today, today+days], soonest first

    Example:
        get_upcoming_deadlines(project_id=1, days=14)
    """
    _require_id(project_id, "project_id")
    _check_project_allowed(project_id)
    try:
        today = date.today()
        end = today + timedelta(days=max(int(days), 0))
        raw = _fetch_raw_issues(project_id, status_id="open", sort="due_date")
        selected: list[tuple[date, dict]] = []
        for d in raw:
            due = _parse_date(d.get("due_date"))
            if due is None or not (today <= due <= end):
                continue
            status = d.get("status") or {}
            if _status_is_closed_dict(status, status.get("name", "")):
                continue
            selected.append((due, d))
        selected.sort(key=lambda item: item[0])
        return [_dict_to_task(d) for _, d in selected[:limit]]
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(
            f"Failed to get upcoming deadlines: {str(e)}"
        ) from e


# ------------------------------ T3 Carga -----------------------------------


@mcp.tool()
def get_workload(project_id: int) -> list[WorkloadEntry]:
    """
    Per-member workload: open/overdue counts plus estimated/spent hours.

    Fetches each member's issues in parallel (max 5 threads). Raw REST is
    used (same project_id + assigned_to_id filter semantics as
    get_member_tasks) because the wrapper drops due_date, which is required
    for the overdue count.

    Args:
        project_id: The numeric ID of the project

    Returns:
        Workload entry per project member

    Example:
        get_workload(project_id=1)
    """
    _require_id(project_id, "project_id")
    _check_project_allowed(project_id)
    try:
        members = get_project_members(project_id)
        today = date.today()

        def _one(member: MemberInfo) -> WorkloadEntry:
            raw = _fetch_raw_issues(
                project_id,
                status_id="*",
                extra={"assigned_to_id": member.id},
            )
            open_tasks = 0
            overdue = 0
            estimated = 0.0
            spent = 0.0
            for d in raw:
                status = d.get("status") or {}
                if _status_is_closed_dict(status, status.get("name", "")):
                    continue
                open_tasks += 1
                due = _parse_date(d.get("due_date"))
                if due is not None and due < today:
                    overdue += 1
                try:
                    estimated += float(d.get("estimated_hours") or 0)
                except (TypeError, ValueError):
                    pass
                try:
                    spent += float(d.get("spent_hours") or 0)
                except (TypeError, ValueError):
                    pass
            return WorkloadEntry(
                member=member,
                open_tasks=open_tasks,
                overdue_tasks=overdue,
                estimated_hours=estimated,
                spent_hours=spent,
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            return list(executor.map(_one, members))
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Failed to get workload: {str(e)}") from e


@mcp.tool()
def get_time_entries(
    project_id: Optional[int] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    user_id: Optional[int] = None,
    limit: int = 100,
) -> list[TimeEntryInfo]:
    """
    List time entries with optional project/date/user filters.

    Args:
        project_id: Filter by project (optional)
        from_date: Start date YYYY-MM-DD (optional)
        to_date: End date YYYY-MM-DD (optional)
        user_id: Filter by user ID (optional)
        limit: Maximum entries to return (default: 100)

    Returns:
        List of time entries

    Example:
        get_time_entries(project_id=1, from_date="2026-09-01")
    """
    if project_id is not None:
        _check_project_allowed(project_id)
    try:
        fd = _require_date(from_date, "from_date")
        td = _require_date(to_date, "to_date")
        effective = limit if limit is not None else GESPRO_DEFAULT_LIMIT
        if callable(getattr(redmine, "get_time_entries", None)):
            entries = redmine.get_time_entries(
                user_id=user_id,
                project_id=project_id,
                from_date=date.fromisoformat(fd) if fd else None,
                to_date=date.fromisoformat(td) if td else None,
                limit=effective,
            )
            return [
                TimeEntryInfo(
                    id=e.id,
                    issue_id=e.issue_id,
                    user=e.user_name or "",
                    hours=float(e.hours or 0),
                    activity=e.activity_name or "",
                    comments=e.comments,
                    spent_on=e.spent_on,
                )
                for e in list(entries)[:effective]
            ]
        params: dict[str, Any] = {"limit": effective}
        if project_id is not None:
            params["project_id"] = project_id
        if user_id is not None:
            params["user_id"] = user_id
        if fd:
            params["from"] = fd
        if td:
            params["to"] = td
        resp = _raw_get("/time_entries.json", params)
        result = []
        for t in resp.get("time_entries", []) or []:
            user = t.get("user") or {}
            activity = t.get("activity") or {}
            issue = t.get("issue") or {}
            result.append(
                TimeEntryInfo(
                    id=int(t.get("id", 0)),
                    issue_id=issue.get("id"),
                    user=str(user.get("name", "")),
                    hours=float(t.get("hours") or 0),
                    activity=str(activity.get("name", "")),
                    comments=t.get("comments"),
                    spent_on=t.get("spent_on"),
                )
            )
        return result[:effective]
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Failed to get time entries: {str(e)}") from e


# ------------------------ T4 Flujo y catalogos -----------------------------


@mcp.tool()
def get_issues_by_status(project_id: int) -> dict:
    """
    Aggregate issue counts of a project by status, tracker and priority.

    Paginates with search_issues (offset loop) up to 500 issues.

    Args:
        project_id: The numeric ID of the project

    Returns:
        Dict with by_status, by_tracker, by_priority counts and total

    Example:
        get_issues_by_status(project_id=1)
    """
    _require_id(project_id, "project_id")
    _check_project_allowed(project_id)
    try:
        page_limit = 100
        offset = 0
        all_tasks: list[TaskInfo] = []
        while True:
            page = search_issues(
                project_id=project_id, limit=page_limit, offset=offset
            )
            all_tasks.extend(page)
            if len(page) < page_limit or len(all_tasks) >= RAW_MAX_TOTAL:
                break
            offset += page_limit
        all_tasks = all_tasks[:RAW_MAX_TOTAL]
        by_status: dict[str, int] = {}
        by_tracker: dict[str, int] = {}
        by_priority: dict[str, int] = {}
        for t in all_tasks:
            by_status[t.status] = by_status.get(t.status, 0) + 1
            by_tracker[t.tracker] = by_tracker.get(t.tracker, 0) + 1
            by_priority[t.priority] = by_priority.get(t.priority, 0) + 1
        return {
            "by_status": by_status,
            "by_tracker": by_tracker,
            "by_priority": by_priority,
            "total": len(all_tasks),
        }
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Failed to aggregate issues: {str(e)}") from e


@mcp.tool()
def get_tracker_stats(project_id: int) -> list[TrackerStats]:
    """
    Per-tracker open/closed/total plus average close days (lead time).

    Args:
        project_id: The numeric ID of the project

    Returns:
        Stats per tracker; avg_close_days is None when no closed issues
        with parseable created_on/closed_on exist

    Example:
        get_tracker_stats(project_id=1)
    """
    _require_id(project_id, "project_id")
    _check_project_allowed(project_id)
    try:
        raw = _fetch_raw_issues(project_id, status_id="*")
        agg: dict[str, dict] = {}
        for d in raw:
            name = (d.get("tracker") or {}).get("name", "") or "Unknown"
            entry = agg.setdefault(
                name, {"open": 0, "closed": 0, "total": 0, "days": []}
            )
            entry["total"] += 1
            status = d.get("status") or {}
            if _status_is_closed_dict(status, status.get("name", "")):
                entry["closed"] += 1
                created = _parse_date(d.get("created_on"))
                closed = _parse_date(d.get("closed_on"))
                if created is not None and closed is not None:
                    delta = (closed - created).days
                    if delta >= 0:
                        entry["days"].append(delta)
            else:
                entry["open"] += 1
        result = []
        for name in sorted(agg):
            entry = agg[name]
            days = entry["days"]
            result.append(
                TrackerStats(
                    tracker=name,
                    open=entry["open"],
                    closed=entry["closed"],
                    total=entry["total"],
                    avg_close_days=(
                        sum(days) / len(days) if days else None
                    ),
                )
            )
        return result
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Failed to get tracker stats: {str(e)}") from e


@mcp.tool()
def get_trackers() -> list[dict]:
    """
    List available issue trackers (e.g. Bug, Feature).

    Returns:
        List of {id, name} dicts

    Example:
        get_trackers()
    """
    try:
        getter = getattr(redmine, "get_trackers", None)
        if callable(getter):
            return [
                {"id": t.get("id"), "name": t.get("name", "")}
                for t in (getter() or [])
                if isinstance(t, dict)
            ]
        resp = _raw_get("/trackers.json")
        return [
            {"id": t.get("id"), "name": t.get("name", "")}
            for t in (resp.get("trackers", []) or [])
        ]
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Failed to get trackers: {str(e)}") from e


@mcp.tool()
def get_issue_statuses() -> list[dict]:
    """
    List available issue statuses (e.g. New, In Progress, Closed).

    Returns:
        List of {id, name} dicts

    Example:
        get_issue_statuses()
    """
    try:
        getter = getattr(redmine, "get_issue_statuses", None)
        if callable(getter):
            return [
                {"id": s.get("id"), "name": s.get("name", "")}
                for s in (getter() or [])
                if isinstance(s, dict)
            ]
        resp = _raw_get("/issue_statuses.json")
        return [
            {"id": s.get("id"), "name": s.get("name", "")}
            for s in (resp.get("issue_statuses", []) or [])
        ]
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Failed to get issue statuses: {str(e)}") from e


@mcp.tool()
def get_priorities() -> list[dict]:
    """
    List available issue priorities (e.g. Low, Normal, Urgent).

    Returns:
        List of {id, name} dicts

    Example:
        get_priorities()
    """
    try:
        getter = getattr(redmine, "get_issue_priorities", None)
        if callable(getter):
            return [
                {"id": p.get("id"), "name": p.get("name", "")}
                for p in (getter() or [])
                if isinstance(p, dict)
            ]
        resp = _raw_get("/enumerations/issue_priorities.json")
        items = resp.get("issue_priorities", resp.get("enumerations", [])) or []
        return [
            {"id": p.get("id"), "name": p.get("name", "")} for p in items
        ]
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Failed to get priorities: {str(e)}") from e


@mcp.tool()
def get_user(user_id: int) -> MemberInfo:
    """
    Get user details including login and email.

    Args:
        user_id: The numeric ID of the user

    Returns:
        Member info with login and mail

    Example:
        get_user(user_id=1)
    """
    _require_id(user_id, "user_id")
    try:
        getter = getattr(redmine, "get_user", None)
        if callable(getter):
            u = getter(user_id)
            name = (u.full_name or "").strip() or (u.login or f"user {u.id}")
            return MemberInfo(
                id=u.id, name=name, login=u.login, mail=u.mail, roles=[]
            )
        resp = _raw_get(f"/users/{user_id}.json")
        u = resp.get("user", {})
        if not u:
            raise RuntimeError(f"User {user_id} not found")
        name = (
            f"{u.get('firstname', '')} {u.get('lastname', '')}".strip()
            or u.get("login", "")
        )
        return MemberInfo(
            id=int(u.get("id", user_id)),
            name=name,
            login=u.get("login"),
            mail=u.get("mail"),
            roles=[],
        )
    except ResourceNotFoundError:
        raise RuntimeError(f"User {user_id} not found") from None
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Failed to get user: {str(e)}") from e


# ----------------------------- T5 Escritura --------------------------------


@mcp.tool()
def create_issue(
    project_id: int,
    subject: str,
    description: str = "",
    tracker_id: Optional[int] = None,
    priority_id: Optional[int] = None,
    assigned_to_id: Optional[int] = None,
    due_date: Optional[str] = None,
) -> TaskInfo:
    """
    Create a new issue in a project.

    Args:
        project_id: The numeric ID of the project (required, > 0)
        subject: Issue subject (required, non-empty)
        description: Issue description (default: "")
        tracker_id: Tracker ID, see get_trackers (optional)
        priority_id: Priority ID, see get_priorities (optional)
        assigned_to_id: Assignee user ID (optional)
        due_date: Due date YYYY-MM-DD (optional)

    Returns:
        The created issue as TaskInfo

    Example:
        create_issue(project_id=1, subject="Fix login",
                     description="Steps...", due_date="2026-10-15")
    """
    _require_id(project_id, "project_id")
    _check_project_allowed(project_id)
    if not subject or not str(subject).strip():
        raise RuntimeError("Invalid subject: non-empty subject is required")
    try:
        due = _require_date(due_date, "due_date")
        payload: dict[str, Any] = {
            "issue": {
                "project_id": project_id,
                "subject": str(subject).strip(),
                "description": description or "",
            }
        }
        if tracker_id is not None:
            payload["issue"]["tracker_id"] = _require_id(
                tracker_id, "tracker_id"
            )
        if priority_id is not None:
            payload["issue"]["priority_id"] = _require_id(
                priority_id, "priority_id"
            )
        if assigned_to_id is not None:
            payload["issue"]["assigned_to_id"] = _require_id(
                assigned_to_id, "assigned_to_id"
            )
        if due is not None:
            payload["issue"]["due_date"] = due
        resp = _raw_post("/issues.json", payload)
        new_id = (resp.get("issue") or {}).get("id")
        if not new_id:
            raise RuntimeError("Create succeeded but no issue id was returned")
        return get_issue_details(int(new_id))
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Failed to create issue: {str(e)}") from e


@mcp.tool()
def update_issue(
    issue_id: int,
    status_id: Optional[int] = None,
    assigned_to_id: Optional[int] = None,
    done_ratio: Optional[int] = None,
    due_date: Optional[str] = None,
    subject: Optional[str] = None,
) -> TaskInfo:
    """
    Update fields of an existing issue.

    Args:
        issue_id: The numeric ID of the issue (required, > 0)
        status_id: New status ID, see get_issue_statuses (optional)
        assigned_to_id: New assignee user ID (optional)
        done_ratio: Progress 0-100 (optional)
        due_date: New due date YYYY-MM-DD (optional)
        subject: New subject (optional)

    Returns:
        The updated issue as TaskInfo

    Example:
        update_issue(issue_id=42, status_id=2, done_ratio=50)
    """
    _require_id(issue_id, "issue_id")
    try:
        fields: dict[str, Any] = {}
        if status_id is not None:
            fields["status_id"] = _require_id(status_id, "status_id")
        if assigned_to_id is not None:
            fields["assigned_to_id"] = _require_id(
                assigned_to_id, "assigned_to_id"
            )
        if done_ratio is not None:
            try:
                ratio = int(done_ratio)
            except (TypeError, ValueError):
                raise RuntimeError(
                    "Invalid done_ratio: expected int 0-100"
                ) from None
            if not 0 <= ratio <= 100:
                raise RuntimeError("Invalid done_ratio: expected int 0-100")
            fields["done_ratio"] = ratio
        if due_date is not None:
            fields["due_date"] = _require_date(due_date, "due_date")
        if subject is not None:
            if not str(subject).strip():
                raise RuntimeError("Invalid subject: must be non-empty")
            fields["subject"] = str(subject).strip()
        if not fields:
            raise RuntimeError("Nothing to update: provide at least one field")
        _raw_put(f"/issues/{issue_id}.json", {"issue": fields})
        return get_issue_details(issue_id)
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Failed to update issue: {str(e)}") from e


@mcp.tool()
def add_note(issue_id: int, notes: str) -> dict:
    """
    Add a journal note (comment) to an issue.

    Args:
        issue_id: The numeric ID of the issue (required, > 0)
        notes: Note text (required, non-empty)

    Returns:
        Dict with issue_id and notes_added flag

    Example:
        add_note(issue_id=42, notes="Daily: avance 50%, sin bloqueos")
    """
    _require_id(issue_id, "issue_id")
    if not notes or not str(notes).strip():
        raise RuntimeError("Invalid notes: non-empty text is required")
    try:
        _raw_put(
            f"/issues/{issue_id}.json",
            {"issue": {"notes": str(notes)}},
        )
        return {"issue_id": issue_id, "notes_added": True}
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Failed to add note: {str(e)}") from e


@mcp.tool()
def log_time(
    issue_id: int,
    hours: float,
    activity_id: Optional[int] = None,
    comments: str = "",
    spent_on: Optional[str] = None,
) -> dict:
    """
    Log spent time on an issue.

    Args:
        issue_id: The numeric ID of the issue (required, > 0)
        hours: Hours spent (required, > 0)
        activity_id: Activity ID (optional)
        comments: Comment for the entry (default: "")
        spent_on: Date YYYY-MM-DD (default: today)

    Returns:
        Dict with the created entry id, issue_id, hours and spent_on

    Example:
        log_time(issue_id=42, hours=2.5, comments="Revision de codigo")
    """
    _require_id(issue_id, "issue_id")
    try:
        h = float(hours)
    except (TypeError, ValueError):
        raise RuntimeError("Invalid hours: expected number > 0") from None
    if h <= 0:
        raise RuntimeError("Invalid hours: expected number > 0")
    try:
        day = _require_date(spent_on, "spent_on") or date.today().isoformat()
        entry: dict[str, Any] = {
            "issue_id": issue_id,
            "hours": h,
            "comments": comments or "",
            "spent_on": day,
        }
        if activity_id is not None:
            entry["activity_id"] = _require_id(activity_id, "activity_id")
        resp = _raw_post("/time_entries.json", {"time_entry": entry})
        new_id = (resp.get("time_entry") or {}).get("id")
        return {
            "id": new_id,
            "issue_id": issue_id,
            "hours": h,
            "spent_on": day,
            "comments": comments or "",
        }
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Failed to log time: {str(e)}") from e


if __name__ == "__main__":
    # Run the MCP server via stdio
    mcp.run(transport="stdio")
