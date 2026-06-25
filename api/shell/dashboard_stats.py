"""
Agregación de métricas para el dashboard (``GET /api/v1/stats/``).

Devuelve dos bloques:

- ``items``  → tarjetas KPI (``app-stat-card``) con los números clave del negocio
  (miembros activos, pagos pendientes, planes, ingreso recurrente, clientes…).
- *breakdowns* (``plans`` / ``by_status`` / ``by_provider``) → datos estructurados
  para los gráficos y la tabla de planes del panel.

Siga `docs/dashboard-stats.md` para añadir nuevas tarjetas sin tocar el contrato JSON.
"""

from __future__ import annotations

from typing import Any, Callable, List

from django.db.models import Count, Q, Sum
from django.utils import timezone

from subscriptions.models import (
    PERIOD_PROVIDERS,
    CheckoutSession,
    PaymentProvider,
    Plan,
    PlanInterval,
)

# Tonos y variantes válidos en el front: ``StatCardComponent`` / ``stat-card.model.ts``
# (incl. ``split``, ``split-solid`` para banda de icono).

_INTERVAL_LABELS: dict[int, str] = {
    PlanInterval.DAILY: "Diario",
    PlanInterval.WEEKLY: "Semanal",
    PlanInterval.MONTHLY: "Mensual",
    PlanInterval.YEARLY: "Anual",
}

# Etiqueta corta y legible por pasarela (para el desglose por proveedor).
_PROVIDER_LABELS: dict[str, str] = {
    PaymentProvider.FLOW: "Flow",
    PaymentProvider.PAYPAL: "PayPal",
    PaymentProvider.MANUAL: "Manual / transferencia",
    PaymentProvider.IMPORTED: "Importado",
    PaymentProvider.FLOW_ONE_TIME: "Flow mensual",
}

# Pasarelas con cobro automático recurrente (cuentan para el ingreso recurrente).
_RECURRING_PROVIDERS = (PaymentProvider.FLOW, PaymentProvider.PAYPAL)


def _stat(
    stat_id: str,
    value: int | float | str,
    *,
    label: str,
    label_key: str,
    icon: str = "insights",
    tone: str = "primary",
    variant: str = "default",
    description: str | None = None,
    prefix: str | None = None,
    suffix: str | None = None,
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
    if prefix:
        row["prefix"] = prefix
    if suffix:
        row["suffix"] = suffix
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


def _active_member_q() -> Q:
    """
    Membresía vigente: ``status=subscribed`` y, para las de período
    (manual/importado/pago único), con ``access_until`` aún válido hoy.
    Las recurrentes (Flow/PayPal) no usan ``access_until`` (queda ``null``).
    """
    today = timezone.localdate()
    return Q(status=CheckoutSession.Status.SUBSCRIBED) & (
        Q(access_until__isnull=True) | Q(access_until__gte=today)
    )


def _business_stats() -> List[dict[str, Any]]:
    """KPIs de negocio: miembros, pagos pendientes, planes, ingreso, clientes."""
    sessions = CheckoutSession.objects.all()
    active_q = _active_member_q()

    active_members = sessions.filter(active_q).count()
    pending_payments = sessions.filter(status=CheckoutSession.Status.PENDING_CARD).count()
    failed_payments = sessions.filter(status=CheckoutSession.Status.FAILED).count()
    active_plans = Plan.objects.filter(is_active=True).count()
    total_customers = sessions.values("email").distinct().count()
    # Accesos por período vigentes (manual / transferencia / importado / pago único).
    manual_members = sessions.filter(active_q, provider__in=PERIOD_PROVIDERS).count()

    # Ingreso recurrente estimado: suma del precio de los planes de las membresías
    # activas con cobro automático (Flow + PayPal), en CLP.
    recurring_revenue = (
        sessions.filter(active_q, provider__in=_RECURRING_PROVIDERS).aggregate(
            total=Sum("plan__amount")
        )["total"]
        or 0
    )

    # Altas del mes en curso (miembros que se suscribieron este mes).
    today = timezone.localdate()
    new_this_month = sessions.filter(
        active_q, created__year=today.year, created__month=today.month
    ).count()

    # Estilo UNIFORME y profesional: todas las tarjetas usan ``variant="default"``
    # (tarjeta blanca limpia) e ícono con superficie ``soft``; el color (``tone``)
    # solo tiñe el ícono según el significado de cada métrica. Descripciones en
    # español. El ingreso recurrente se muestra como moneda ($ … CLP).
    return [
        _stat(
            "active_members",
            active_members,
            label="Miembros activos",
            label_key="dashboard.stats.activeMembers",
            icon="groups",
            tone="primary",
            variant="default",
            icon_surface="soft",
            description="Membresías al día (suscritas y dentro del período de acceso).",
        ),
        _stat(
            "recurring_revenue",
            recurring_revenue,
            label="Ingreso recurrente",
            label_key="dashboard.stats.recurringRevenue",
            icon="payments",
            tone="success",
            variant="default",
            icon_surface="soft",
            prefix="$",
            suffix=" CLP",
            description="Suma del precio de los planes con cobro automático activo.",
        ),
        _stat(
            "new_this_month",
            new_this_month,
            label="Nuevos este mes",
            label_key="dashboard.stats.newThisMonth",
            icon="person_add",
            tone="info",
            variant="default",
            icon_surface="soft",
            description="Miembros que se sumaron este mes.",
        ),
        _stat(
            "manual_members",
            manual_members,
            label="Accesos manuales",
            label_key="dashboard.stats.manualMembers",
            icon="volunteer_activism",
            tone="primary",
            variant="default",
            icon_surface="soft",
            description="Accesos por transferencia / manual / importados vigentes.",
        ),
        _stat(
            "pending_payments",
            pending_payments,
            label="Pagos pendientes",
            label_key="dashboard.stats.pendingPayments",
            icon="hourglass_top",
            tone="warning",
            variant="default",
            icon_surface="soft",
            description="Checkouts esperando tarjeta o confirmación.",
        ),
        _stat(
            "failed_payments",
            failed_payments,
            label="Pagos fallidos",
            label_key="dashboard.stats.failedPayments",
            icon="error_outline",
            tone="danger",
            variant="default",
            icon_surface="soft",
            description="Checkouts que terminaron con error.",
        ),
        _stat(
            "active_plans",
            active_plans,
            label="Planes activos",
            label_key="dashboard.stats.activePlans",
            icon="workspace_premium",
            tone="info",
            variant="default",
            icon_surface="soft",
            description="Planes disponibles para suscripción.",
        ),
        _stat(
            "total_customers",
            total_customers,
            label="Clientes",
            label_key="dashboard.stats.totalCustomers",
            icon="person",
            tone="neutral",
            variant="default",
            icon_surface="soft",
            description="Personas únicas en todos los checkouts.",
        ),
    ]


# Añada aquí callables que devuelvan listas de dicts (cada dict es un KPI).
STAT_SECTIONS: List[Callable[[], List[dict[str, Any]]]] = [
    _business_stats,
]


def get_dashboard_stats() -> List[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for section in STAT_SECTIONS:
        out.extend(section())
    return out


def _plans_breakdown() -> List[dict[str, Any]]:
    """Una fila por plan con sus miembros activos y pagos pendientes."""
    today = timezone.localdate()
    active_related = Q(
        checkout_sessions__status=CheckoutSession.Status.SUBSCRIBED
    ) & (
        Q(checkout_sessions__access_until__isnull=True)
        | Q(checkout_sessions__access_until__gte=today)
    )
    pending_related = Q(
        checkout_sessions__status=CheckoutSession.Status.PENDING_CARD
    )

    plans = (
        Plan.objects.annotate(
            subscribers=Count("checkout_sessions", filter=active_related, distinct=True),
            pending=Count("checkout_sessions", filter=pending_related, distinct=True),
        )
        .order_by("-subscribers", "name")
    )

    rows: list[dict[str, Any]] = []
    for plan in plans:
        rows.append(
            {
                "id": plan.id,
                "name": plan.name,
                "amount": plan.amount,
                "currency": plan.currency,
                "interval_label": _INTERVAL_LABELS.get(plan.interval, ""),
                "is_active": plan.is_active,
                "subscribers": plan.subscribers,
                "pending": plan.pending,
            }
        )
    return rows


def _status_breakdown() -> List[dict[str, Any]]:
    """Conteo de checkouts por estado (suscrito / pendiente / fallido)."""
    sessions = CheckoutSession.objects.all()
    return [
        {
            "key": "subscribed",
            "label": "Suscritos",
            "value": sessions.filter(status=CheckoutSession.Status.SUBSCRIBED).count(),
            "tone": "success",
        },
        {
            "key": "pending_card",
            "label": "Pendientes",
            "value": sessions.filter(status=CheckoutSession.Status.PENDING_CARD).count(),
            "tone": "warning",
        },
        {
            "key": "failed",
            "label": "Fallidos",
            "value": sessions.filter(status=CheckoutSession.Status.FAILED).count(),
            "tone": "danger",
        },
    ]


def _provider_breakdown() -> List[dict[str, Any]]:
    """Pagos activos por pasarela / origen: cantidad (``value``) y monto asociado
    (``amount`` = suma del precio de los planes, CLP)."""
    active_q = _active_member_q()
    grouped = (
        CheckoutSession.objects.filter(active_q)
        .values("provider")
        .annotate(total=Count("id"), amount=Sum("plan__amount"))
        .order_by("-total")
    )
    return [
        {
            "key": row["provider"],
            "label": _PROVIDER_LABELS.get(row["provider"], row["provider"]),
            "value": row["total"],
            "amount": row["amount"] or 0,
        }
        for row in grouped
    ]


def get_dashboard_breakdowns() -> dict[str, Any]:
    """Bloques estructurados (gráficos + tabla de planes) del panel."""
    return {
        "plans": _plans_breakdown(),
        "by_status": _status_breakdown(),
        "by_provider": _provider_breakdown(),
    }
