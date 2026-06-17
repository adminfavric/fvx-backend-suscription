"""
Sync a local ``Plan`` to its Flow.cl counterpart.

Called from the admin on save. Creates the Flow plan the first time and edits it
afterwards (Flow only allows editing ``trial_period_days`` once the plan has
subscribers, so other edits may be rejected — the error is surfaced, not hidden).
"""

from __future__ import annotations

from django.utils import timezone

from .flow import FlowError, get_flow_client

# Fields owned by Flow — refreshed from Flow on import. Presentation fields
# (tagline, description, features, icon, featured, is_public) are NOT here:
# they live locally and survive re-imports.
_FLOW_OWNED = (
    "name", "amount", "currency", "interval", "interval_count",
    "trial_period_days", "days_until_due", "periods_number",
    "charges_retries_number",
)


def _flow_params(plan) -> dict:
    params = {
        "planId": plan.flow_plan_id,
        "name": plan.name,
        "amount": plan.amount,
        "currency": plan.currency,
        "interval": plan.interval,
        "interval_count": plan.interval_count,
        "trial_period_days": plan.trial_period_days,
        "days_until_due": plan.days_until_due,
        "charges_retries_number": plan.charges_retries_number,
    }
    if plan.periods_number:
        params["periods_number"] = plan.periods_number
    return params


def sync_plan_to_flow(plan) -> dict:
    """
    Push ``plan`` to Flow. Returns the Flow plan payload.

    Raises ``FlowError`` if the plan is not ready (no amount) or the API rejects
    the call. On success, updates the plan's sync bookkeeping fields.
    """
    if not plan.amount:
        raise FlowError("Plan has no amount yet (draft) — set a price before syncing to Flow.")

    flow = get_flow_client()
    params = _flow_params(plan)

    # Create on first sync; edit if Flow already knows this planId.
    try:
        flow.get_plan(plan.flow_plan_id)
        exists = True
    except FlowError:
        exists = False

    try:
        result = flow.edit_plan(plan.flow_plan_id, **params) if exists else flow.create_plan(**params)
    except FlowError as exc:
        plan.last_sync_error = str(exc)
        plan.save(update_fields=["last_sync_error", "modified"])
        raise

    plan.flow_synced_at = timezone.now()
    plan.flow_status = result.get("status")
    plan.last_sync_error = ""
    plan.save(update_fields=["flow_synced_at", "flow_status", "last_sync_error", "modified"])
    return result


def _flow_fields_from_payload(fp: dict) -> dict:
    """Map a Flow plan payload to local Flow-owned model fields."""
    return {
        "name": fp.get("name") or fp.get("planId"),
        "amount": fp.get("amount"),
        "currency": fp.get("currency") or "CLP",
        "interval": fp.get("interval") or 3,
        "interval_count": fp.get("interval_count") or 1,
        "trial_period_days": fp.get("trial_period_days") or 0,
        "days_until_due": fp.get("days_until_due") or 3,
        "periods_number": fp.get("periods_number") or None,
        "charges_retries_number": fp.get("charges_retries_number") or 3,
    }


def import_plans_from_flow() -> dict:
    """
    Pull every plan from Flow into local ``Plan`` rows, linked by
    ``flow_plan_id``. El admin es un **espejo de Flow**: se importan TODOS los
    planes (activos e inactivos) para que la lista del admin muestre lo mismo que
    Flow. Los campos Flow-owned (precio, interval, status…) se refrescan; el
    enriquecimiento local (tagline, descripción, features, icon, image_url,
    featured, is_public, order) se preserva en filas existentes. Las filas nuevas
    entran como no-públicas (``is_public=False``) para enriquecerlas antes de
    publicarlas en el sitio.

    Returns ``{"created": int, "updated": int}``.
    """
    from ..models import Plan

    flow = get_flow_client()
    created = updated = 0
    start = 0
    while True:
        resp = flow.list_plans(start=start, limit=100)
        rows = resp.get("data", []) or []
        for fp in rows:
            plan_id = fp.get("planId")
            if not plan_id:
                continue
            status = fp.get("status")
            fields = _flow_fields_from_payload(fp)
            plan = Plan.objects.filter(flow_plan_id=plan_id).first()
            if plan:
                # Refrescar campos Flow-owned + estado. Si Flow lo marcó eliminado
                # (status 0), se refleja localmente para ocultarlo del sitio, pero
                # NO se borra la fila (conserva el enriquecimiento).
                for key, value in fields.items():
                    setattr(plan, key, value)
                plan.flow_status = status
                plan.is_active = status == 1
                plan.flow_synced_at = timezone.now()
                plan.save()
                updated += 1
            else:
                # Espejo completo de Flow: se crean filas para TODOS los planes
                # (activos e inactivos). Las inactivas (status 0) entran no
                # públicas y no aparecen en el sitio, pero sí en el admin.
                Plan.objects.create(
                    flow_plan_id=plan_id,
                    is_public=False,
                    is_active=status == 1,
                    flow_status=status,
                    flow_synced_at=timezone.now(),
                    **fields,
                )
                created += 1
        total = resp.get("total", 0)
        start += 100
        if start >= total or not rows:
            break
    return {"created": created, "updated": updated}
