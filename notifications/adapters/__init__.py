"""Factory que escoge el adapter activo según ``settings.NOTIFICATIONS_EMAIL_ADAPTER``.

Para agregar un proveedor nuevo (Resend / Postmark / Mailgun / etc):

1. Crear ``notifications/adapters/<name>.py`` implementando ``EmailAdapter``.
2. Agregarlo a ``_ADAPTERS`` abajo.
3. Setear ``NOTIFICATIONS_EMAIL_ADAPTER=<name>`` en el ``.env``.

Cero cambios en consumidores ni en templates.
"""

from django.conf import settings

from .base import EmailAdapter, EmailPayload, EmailSendError
from .console import ConsoleAdapter
from .ses import SESAdapter
from .smtp import SMTPAdapter

_ADAPTERS: dict[str, type] = {
    "ses": SESAdapter,
    "smtp": SMTPAdapter,
    "console": ConsoleAdapter,
}

_instance: EmailAdapter | None = None


def get_email_adapter() -> EmailAdapter:
    """Devuelve el adapter activo. Singleton por proceso."""
    global _instance
    if _instance is None:
        name = settings.NOTIFICATIONS_EMAIL_ADAPTER
        if name not in _ADAPTERS:
            raise ValueError(
                f"Adapter desconocido: {name}. Opciones: {list(_ADAPTERS)}",
            )
        _instance = _ADAPTERS[name]()
    return _instance


def reset_email_adapter() -> None:
    """Resetea el singleton — solo para tests que cambian la setting."""
    global _instance
    _instance = None


__all__ = [
    "EmailAdapter",
    "EmailPayload",
    "EmailSendError",
    "get_email_adapter",
    "reset_email_adapter",
]
