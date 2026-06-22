"""
Sincroniza un ``Plan`` local con su contraparte en PayPal (billing plan en USD).

Análogo a ``sync.py`` (Flow) pero para PayPal: PayPal exige primero un *product*
de catálogo y luego un *billing plan* que referencia ese producto con los
``billing_cycles`` (frecuencia + precio USD) y ``payment_preferences``.

Llamado desde el admin al guardar (cuando ``paypal_enabled`` y hay precio). Crea
el producto + plan la primera vez; en sincronizaciones posteriores actualiza el
precio (``update-pricing-schemes``) y el estado (activate/deactivate). PayPal
cobra en USD: el monto se toma de ``Plan.paypal_price_usd`` (override o conversión
del precio CLP). El precio CLP de Flow no se toca.
"""

from __future__ import annotations

from django.utils import timezone

from ..models import PAYPAL_INTERVAL_UNIT, PlanInterval
from .paypal import PayPalError, get_paypal_client


def _billing_cycles(plan, price: str) -> list[dict]:
    """Construye los billing_cycles de PayPal a partir del plan local.

    Si el plan tiene período de prueba (``trial_period_days``), se antepone un
    ciclo TRIAL gratuito en días. El ciclo regular usa la frecuencia del plan
    (interval/interval_count) y ``total_cycles=0`` (indefinido) salvo que el plan
    fije ``periods_number``.
    """
    cycles: list[dict] = []
    sequence = 1
    if plan.trial_period_days:
        cycles.append({
            "tenure_type": "TRIAL",
            "sequence": sequence,
            "total_cycles": 1,
            "frequency": {"interval_unit": "DAY", "interval_count": plan.trial_period_days},
            "pricing_scheme": {"fixed_price": {"value": "0", "currency_code": plan.paypal_currency}},
        })
        sequence += 1

    interval_unit = PAYPAL_INTERVAL_UNIT.get(plan.interval, "MONTH")
    cycles.append({
        "tenure_type": "REGULAR",
        "sequence": sequence,
        # 0 = indefinido (se cobra hasta que se cancele).
        "total_cycles": plan.periods_number or 0,
        "frequency": {"interval_unit": interval_unit, "interval_count": plan.interval_count or 1},
        "pricing_scheme": {
            "fixed_price": {"value": price, "currency_code": plan.paypal_currency}
        },
    })
    return cycles


def _payment_preferences(plan) -> dict:
    return {
        "auto_bill_outstanding": True,
        "setup_fee": {"value": "0", "currency_code": plan.paypal_currency},
        "setup_fee_failure_action": "CONTINUE",
        "payment_failure_threshold": plan.charges_retries_number or 3,
    }


def sync_plan_to_paypal(plan) -> dict:
    """
    Crea/actualiza el billing plan de PayPal para ``plan``. Devuelve el payload del
    plan de PayPal. Lanza ``PayPalError`` si no está listo (sin precio USD) o si la
    API lo rechaza. Persiste los ids y el estado de sync en el modelo.
    """
    price = plan.paypal_price_usd
    if price is None:
        raise PayPalError("El plan no tiene precio (CLP ni USD) — define un valor antes de sincronizar a PayPal.")
    price_str = f"{price:.2f}"

    pp = get_paypal_client()

    try:
        if not plan.paypal_product_id:
            product = pp.create_product(
                name=plan.name,
                description=(plan.tagline or plan.name)[:256],
                type="SERVICE",
                category="EDUCATIONAL_AND_TEXTBOOKS",
            )
            plan.paypal_product_id = product.get("id", "")

        if plan.paypal_plan_id:
            # Ya existe: actualizar precio y estado (PayPal no permite cambiar la
            # frecuencia de un plan creado; el precio sí vía pricing-schemes).
            result = _resync_existing(pp, plan, price_str)
        else:
            created = pp.create_plan(
                product_id=plan.paypal_product_id,
                name=plan.name[:127],
                description=(plan.tagline or plan.name)[:127],
                status="ACTIVE",
                billing_cycles=_billing_cycles(plan, price_str),
                payment_preferences=_payment_preferences(plan),
            )
            plan.paypal_plan_id = created.get("id", "")
            result = created
    except PayPalError as exc:
        plan.paypal_last_sync_error = str(exc)
        plan.save(update_fields=["paypal_product_id", "paypal_plan_id", "paypal_last_sync_error", "modified"])
        raise

    plan.paypal_synced_at = timezone.now()
    plan.paypal_status = result.get("status") or "ACTIVE"
    plan.paypal_last_sync_error = ""
    plan.save(update_fields=[
        "paypal_product_id", "paypal_plan_id", "paypal_synced_at",
        "paypal_status", "paypal_last_sync_error", "modified",
    ])
    return result


def _resync_existing(pp, plan, price_str: str) -> dict:
    """Actualiza el precio del ciclo REGULAR y refleja el estado activo/inactivo."""
    current = pp.get_plan(plan.paypal_plan_id)
    # El sequence del ciclo regular depende de si hay trial (1 o 2).
    regular_seq = 2 if plan.trial_period_days else 1
    pp.update_plan_pricing(
        plan.paypal_plan_id,
        pricing_schemes=[{
            "billing_cycle_sequence": regular_seq,
            "pricing_scheme": {
                "fixed_price": {"value": price_str, "currency_code": plan.paypal_currency}
            },
        }],
    )
    # Alinear estado con is_active del plan local.
    desired = "ACTIVE" if plan.is_active else "INACTIVE"
    if current.get("status") != desired:
        if desired == "ACTIVE":
            pp.activate_plan(plan.paypal_plan_id)
        else:
            pp.deactivate_plan(plan.paypal_plan_id)
    return {"id": plan.paypal_plan_id, "status": desired}
