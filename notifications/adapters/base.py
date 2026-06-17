"""Contrato base que todo adapter de email cumple.

Ver ``docs/email.md`` §7 — el patrón es provider-agnostic: cambiar de SES a
Resend / Postmark / Mailgun = implementar este protocolo + cambiar la env
``NOTIFICATIONS_EMAIL_ADAPTER``. Cero cambios en los consumidores ni en los
templates.
"""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class EmailPayload:
    """Payload neutral que cada adapter sabe cómo enviar al proveedor real."""

    to: str
    subject: str
    html: str
    text: str | None = None
    reply_to: list[str] = field(default_factory=list)
    headers: dict = field(default_factory=dict)
    tags: dict = field(default_factory=dict)
    configuration_set: str | None = None
    from_email: str | None = None  # override del DEFAULT_FROM_EMAIL


class EmailAdapter(Protocol):
    """Contrato que TODO adapter cumple."""

    def send(self, payload: EmailPayload) -> str:
        """Envía el email; retorna el ``message_id`` del proveedor.

        Levanta :class:`EmailSendError` ante cualquier fallo. Si el error es
        ``is_transient=True`` la task Celery (cuando exista) reintenta con
        backoff. Permanentes (credenciales inválidas, payload mal armado) no
        se reintentan.
        """
        ...


class EmailSendError(Exception):
    """Error al enviar. Si ``is_transient`` es True el caller debería reintentar."""

    def __init__(self, message: str, *, is_transient: bool = False) -> None:
        super().__init__(message)
        self.is_transient = is_transient
