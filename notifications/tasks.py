"""Tasks Celery del módulo de notificaciones.

**Placeholder hasta que se configure Celery en este backend** (no está en
``requirements.txt`` aún). Mientras tanto ``services.email.send()`` cae al
modo síncrono automáticamente — ver ``_resolve_sync()`` en ``services/email.py``.

Cuando se agregue Celery (Sprint 3 de ``docs/email.md``):

1. Agregar ``celery==5.x`` y ``django-celery-beat`` a ``requirements.txt``.
2. Crear ``core/celery.py`` con la app Celery + autodiscover_tasks().
3. Setear ``CELERY_BROKER_URL`` en el ``.env`` (Redis ya está disponible).
4. La task de abajo empieza a funcionar sin más cambios.
"""

try:
    from celery import shared_task
except ImportError:
    # Celery no instalado — definimos un stub para que los imports no rompan.
    def shared_task(*args, **kwargs):  # type: ignore[no-redef]
        def decorator(func):
            return func

        if args and callable(args[0]):
            return args[0]
        return decorator


from notifications.adapters import EmailSendError
from notifications.services.email import _do_send


@shared_task(
    bind=True,
    autoretry_for=(EmailSendError,),
    retry_backoff=True,  # 1s, 2s, 4s, 8s...
    retry_jitter=True,
    max_retries=5,
)
def send_email_task(
    self,  # noqa: ARG001 — Celery requiere bind=True
    message_pk: int,
    html: str,
    subject: str,
    reply_to: list[str],
) -> None:
    """Envío asíncrono de un email previamente persistido como ``EmailMessage``.

    Si el adapter levanta ``EmailSendError(is_transient=True)``, Celery reintenta
    con backoff exponencial hasta 5 veces.
    """
    _do_send(message_pk, html, subject, reply_to)
