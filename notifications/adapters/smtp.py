"""Adapter SMTP genérico — sirve para Mailpit local y cualquier proveedor SMTP.

Usa el backend SMTP nativo de Django, así heredamos toda la lógica de
conexiones, TLS, autenticación y manejo de errores que ya está probada.
"""

import uuid

from django.core.mail import EmailMultiAlternatives, get_connection

from .base import EmailPayload, EmailSendError


class SMTPAdapter:
    """Adapter SMTP — Mailpit local, Postmark SMTP, Mailgun SMTP, etc."""

    def send(self, payload: EmailPayload) -> str:
        msg = EmailMultiAlternatives(
            subject=payload.subject,
            body=payload.text or _html_to_text(payload.html),
            from_email=payload.from_email,
            to=[payload.to],
            reply_to=payload.reply_to or None,
            headers=payload.headers or None,
            connection=get_connection(
                "django.core.mail.backends.smtp.EmailBackend",
            ),
        )
        msg.attach_alternative(payload.html, "text/html")
        try:
            sent = msg.send(fail_silently=False)
        except Exception as e:  # noqa: BLE001 — el smtp puede tirar cualquier cosa
            raise EmailSendError(str(e), is_transient=True) from e
        if sent == 0:
            raise EmailSendError("smtp send() returned 0", is_transient=True)
        # Django SMTP no expone el Message-ID generado; sintetizamos uno local
        # para que `EmailMessage.provider_message_id` quede poblado.
        return msg.extra_headers.get("Message-ID") or f"smtp-{uuid.uuid4()}"


def _html_to_text(html: str) -> str:
    """Fallback HTML → texto plano (clientes que no soporten HTML)."""
    from bs4 import BeautifulSoup

    return BeautifulSoup(html, "html.parser").get_text(separator="\n").strip()
