"""Tasks Celery de suscripciones (autodescubiertas por ``core.celery``)."""

from celery import shared_task

from .services.event_reminders import send_live_event_reminders
from .services.reminders import send_expiry_reminders


@shared_task(name="subscriptions.tasks.send_expiry_reminders")
def expiry_reminders_task() -> int:
    """Envía los recordatorios de vencimiento de membresías por período.
    Programada a diario por Celery beat (ver migración 0016)."""
    return send_expiry_reminders()


@shared_task(name="subscriptions.tasks.send_live_event_reminders")
def live_event_reminders_task() -> int:
    """Avisa por correo ~30 min antes de cada sesión Zoom a los miembros con
    acceso. Programada cada 5 min por Celery beat (ver migración 0017)."""
    return send_live_event_reminders()
