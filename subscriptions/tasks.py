"""Tasks Celery de suscripciones (autodescubiertas por ``core.celery``)."""

from celery import shared_task

from .services.reminders import send_expiry_reminders


@shared_task(name="subscriptions.tasks.send_expiry_reminders")
def expiry_reminders_task() -> int:
    """Envía los recordatorios de vencimiento de membresías por período.
    Programada a diario por Celery beat (ver migración 0016)."""
    return send_expiry_reminders()
