"""API pública del módulo de email.

**Esta es la única superficie que los consumidores deben tocar**. Nunca
importes ``boto3``, un adapter directo, ni Jinja2 desde fuera del paquete
``notifications``. Si algo te falta acá, pídelo como input adicional —
mantener este shape estable es lo que permite cambiar de proveedor o de
motor de templates sin reescribir consumers.

Uso típico:

    from notifications.services import email as mail
    mail.send(
        to=user.email,
        template="welcome",
        context={"user_name": user.first_name, "action_url": link},
        related=user,
        tags={"campaign": "onboarding"},
        user=user,
    )

Por default ``sync=False`` para no bloquear el request — cuando Celery esté
wired la task se encolará. Mientras tanto el fallback es ``sync=True``
automático para no romper consumers (ver lógica abajo).
"""

from pathlib import Path
from typing import Any

import premailer
from django.apps import apps
from django.conf import settings
from django.utils import timezone
from jinja2 import Environment, FileSystemLoader, select_autoescape
from mjml import mjml2html

from notifications.adapters import (
    EmailPayload,
    EmailSendError,
    get_email_adapter,
)
from notifications.filters import FILTERS

# Directorio raíz de templates. Los proyectos consumidores pueden agregar
# templates extra acá (o exponerlos via Django app templates en el futuro).
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


def _build_jinja_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "mjml.j2"]),
    )
    env.filters.update(FILTERS)
    return env


_JINJA = _build_jinja_env()


def render_email(template: str, context: dict[str, Any]) -> tuple[str, str]:
    """Renderiza ``email/<template>.mjml.j2`` → ``(subject, html_inlineado)``.

    El subject viene de un archivo separado ``email/<template>.subject.j2``
    para mantenerlo simple (1 línea) — Jinja en el HTML para el cuerpo
    completo, Jinja "puro" para el subject.

    Pipeline:
    1. Render Jinja del MJML → MJML expandido con valores.
    2. ``mjml_to_html()`` → HTML responsive con tables anidadas.
    3. ``premailer.transform()`` → inlines CSS (necesario para Gmail/Outlook).
    """
    mjml_src = _JINJA.get_template(f"email/{template}.mjml.j2").render(**context)
    # mjml2html (mjml-python 1.x): retorna HTML string directo.
    html = mjml2html(mjml_src)
    html = premailer.transform(html, remove_classes=False)
    subject = _JINJA.get_template(f"email/{template}.subject.j2").render(**context).strip()
    return subject, html


def is_suppressed(email: str) -> bool:
    """¿La dirección está en la lista de supresión?"""
    EmailSuppression = apps.get_model("notifications", "EmailSuppression")
    return EmailSuppression.objects.filter(email__iexact=email).exists()


def send(
    *,
    to: str,
    template: str,
    context: dict[str, Any],
    related: Any | None = None,
    tags: dict | None = None,
    reply_to: list[str] | None = None,
    user=None,
    sync: bool | None = None,
):
    """API pública para enviar un email transaccional.

    Args:
        to: dirección destino (1 destinatario por send — multi-cast no soportado).
        template: nombre del template sin extensión. Ej. ``"welcome"`` resuelve
            a ``email/welcome.mjml.j2`` + ``email/welcome.subject.j2``.
        context: dict pasado tal cual a Jinja.
        related: objeto opaco al que se asocia el email (para auditoría).
            Se persiste solo ``type(related).__name__`` y ``related.pk``.
        tags: dict de etiquetas que viajan al proveedor (SES EmailTags / Resend tags).
        reply_to: lista de direcciones Reply-To.
        user: ``User`` opcional dueño del envío (FK ``EmailMessage.to_user``).
        sync: si True envía inmediatamente; si False encola Celery; si None
            (default) usa Celery si está disponible, sync de lo contrario.

    Returns:
        ``EmailMessage`` row creado (siempre, incluso si fue supressed o falló
        — el caller puede consultar ``.status`` para reaccionar).
    """
    EmailMessage = apps.get_model("notifications", "EmailMessage")

    subject, html = render_email(template, context)

    record = EmailMessage.objects.create(
        to_address=to,
        to_user=user,
        template_name=template,
        subject=subject,
        context_snapshot=_safe_context(context),
        tags=tags or {},
        related_object_type=type(related).__name__ if related else "",
        related_object_id=str(getattr(related, "pk", "")) if related else "",
        provider=settings.NOTIFICATIONS_EMAIL_ADAPTER,
        status=EmailMessage.Status.PENDING,
    )

    # Supresión: cortocircuito ANTES de pegarle al proveedor.
    if is_suppressed(to):
        record.status = EmailMessage.Status.SUPPRESSED
        record.error_message = "Email en lista de supresión"
        record.save(update_fields=["status", "error_message"])
        return record

    effective_sync = _resolve_sync(sync)
    if effective_sync:
        _do_send(record.pk, html, subject, reply_to or [])
        # `_do_send` re-fetcha + actualiza el row; refrescamos el objeto
        # en memoria para que el caller vea SENT / FAILED / DELIVERED en
        # vez del PENDING inicial.
        record.refresh_from_db()
    else:
        # Lazy import — la task vive en notifications.tasks (Celery).
        from notifications.tasks import send_email_task

        send_email_task.delay(record.pk, html, subject, reply_to or [])

    return record


def _do_send(message_pk, html: str, subject: str, reply_to: list[str]) -> None:
    """Envío real — llamado por la task Celery o por ``sync=True``."""
    EmailMessage = apps.get_model("notifications", "EmailMessage")
    record = EmailMessage.objects.get(pk=message_pk)
    payload = EmailPayload(
        to=record.to_address,
        subject=subject,
        html=html,
        reply_to=reply_to,
        tags=record.tags,
        configuration_set=getattr(settings, "AWS_SES_CONFIGURATION_SET", "") or None,
    )
    try:
        message_id = get_email_adapter().send(payload)
    except EmailSendError as e:
        record.status = EmailMessage.Status.FAILED
        record.error_message = str(e)
        record.save(update_fields=["status", "error_message"])
        if e.is_transient:
            # Re-raise para que Celery reintente; en modo sync el caller
            # decide qué hacer.
            raise
        return

    record.provider_message_id = message_id
    record.status = EmailMessage.Status.SENT
    record.sent_at = timezone.now()
    record.save(update_fields=["provider_message_id", "status", "sent_at"])


def _resolve_sync(explicit: bool | None) -> bool:
    """Política de async vs sync.

    - Si el caller pasó ``sync`` explícito → se respeta.
    - Si Celery NO está instalado (caso actual) → sync forzado, con warning
      una sola vez por proceso para no spamear logs.
    """
    if explicit is not None:
        return explicit
    if not _celery_available():
        _warn_no_celery_once()
        return True
    return False


_celery_warned = False


def _celery_available() -> bool:
    try:
        import celery  # noqa: F401
    except ImportError:
        return False
    return getattr(settings, "CELERY_BROKER_URL", None) is not None


def _warn_no_celery_once() -> None:
    global _celery_warned
    if _celery_warned:
        return
    _celery_warned = True
    import logging

    logging.getLogger(__name__).info(
        "[notifications] Celery no configurado: send() corre en modo SÍNCRONO "
        "por default. Setear sync=False solo cuando CELERY_BROKER_URL esté disponible.",
    )


def _safe_context(context: dict) -> dict:
    """Sanitiza el snapshot que persistimos en ``context_snapshot``.

    Reduce objetos Django a ``{_model, pk}`` para evitar guardar PII completa
    o serializaciones gigantes. Strings largos se truncan.
    """
    out: dict = {}
    for k, v in context.items():
        if hasattr(v, "pk") and hasattr(v, "_meta"):
            out[k] = {"_model": type(v).__name__, "pk": str(v.pk)}
        elif isinstance(v, (str, int, float, bool, type(None))):
            out[k] = v
        elif isinstance(v, (list, tuple)):
            out[k] = [str(x)[:80] for x in v[:10]]
        elif isinstance(v, dict):
            out[k] = {kk: str(vv)[:80] for kk, vv in list(v.items())[:10]}
        else:
            out[k] = str(v)[:200]
    return out
