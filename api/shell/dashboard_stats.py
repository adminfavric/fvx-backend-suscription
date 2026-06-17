"""
Agregación de métricas para el dashboard (``GET /api/v1/stats/``).

Siga `docs/dashboard-stats.md` para añadir nuevas tarjetas sin tocar el contrato JSON.
"""

from __future__ import annotations

from typing import Any, Callable, List

from django.contrib.auth import get_user_model

from ..choices import ROLE_ADMIN, ROLE_EDITOR, ROLE_VIEWER

User = get_user_model()

# Tonos y variantes válidos en el front: ``StatCardComponent`` / ``stat-card.model.ts``
# (incl. ``split``, ``split-solid`` para banda de icono).


def _stat(
    stat_id: str,
    value: int | float,
    *,
    label: str,
    label_key: str,
    icon: str = "insights",
    tone: str = "primary",
    variant: str = "default",
    description: str | None = None,
    trend: str | None = None,
    trend_value: str | None = None,
    trend_label: str | None = None,
    icon_position: str | None = None,
    icon_surface: str | None = None,
    progress: int | float | None = None,
) -> dict[str, Any]:
    # ``label``/``description`` son texto por defecto (en); i18n en el SPA vía ``label_key``.
    row: dict[str, Any] = {
        "id": stat_id,
        "value": value,
        "label": label,
        "label_key": label_key,
        "icon": icon,
        "tone": tone,
        "variant": variant,
    }
    if description:
        row["description"] = description
    if trend is not None:
        row["trend"] = trend
    if trend_value is not None:
        row["trend_value"] = trend_value
    if trend_label is not None:
        row["trend_label"] = trend_label
    if icon_position:
        row["icon_position"] = icon_position
    if icon_surface:
        row["icon_surface"] = icon_surface
    if progress is not None:
        row["progress"] = progress
    return row


def _user_directory_stats() -> List[dict[str, Any]]:
    """
    Conteos sobre ``User`` (rol vive en el propio modelo tras el refactor).
    Puede ajustar filtros según su negocio (p. ej. excluir staff, etc.).
    """
    users_active = User.objects.filter(is_active=True)
    return [
        _stat(
            "users_active",
            users_active.count(),
            label="Active users",
            label_key="dashboard.stats.usersActive",
            icon="person",
            tone="primary",
            description="User accounts with is_active=True",
        ),
        _stat(
            "users_role_admin",
            users_active.filter(role=ROLE_ADMIN).count(),
            label="Role: Admin",
            label_key="dashboard.stats.roleAdmin",
            icon="admin_panel_settings",
            tone="success",
        ),
        _stat(
            "users_role_editor",
            users_active.filter(role=ROLE_EDITOR).count(),
            label="Role: Editor",
            label_key="dashboard.stats.roleEditor",
            icon="edit",
            tone="info",
        ),
        _stat(
            "users_role_viewer",
            users_active.filter(role=ROLE_VIEWER).count(),
            label="Role: Viewer",
            label_key="dashboard.stats.roleViewer",
            icon="visibility",
            tone="neutral",
        ),
    ]


# Añada aquí callables que devuelvan listas de dicts (cada dict es un KPI).
STAT_SECTIONS: List[Callable[[], List[dict[str, Any]]]] = [
    _user_directory_stats,
]


def get_dashboard_stats() -> List[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for section in STAT_SECTIONS:
        out.extend(section())
    return out
