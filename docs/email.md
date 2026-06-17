# Email transaccional — implementación genérica

> **Audiencia**: dev backend (Django) que implementa esto en el stack base.
> **Estado**: aprobado
> **Última revisión**: 2026-05-28
> **Alcance**: infraestructura genérica de email transaccional, reutilizable
> por cualquier proyecto sobre este backend. **NO incluye templates ni casos
> de uso específicos de ningún producto** — esos se agregan después por cada
> consumidor.

---

## 1. Resumen ejecutivo

Infraestructura de email transaccional con 3 pilares:

1. **Adapter pattern por proveedor**: el código de negocio no conoce al
   proveedor. Cambiar de Amazon SES a Resend / Postmark / Mailgun = cambiar
   1 variable de entorno + 1 archivo de adapter.
2. **Templates locales en repo** con **MJML + Jinja2**: HTML responsive
   testable, versionado, sin editores externos. Cada proyecto que consume
   este backend define sus propios templates.
3. **3 ambientes, mismo código**:
   - **Local** → Mailpit (Docker, captura emails localmente con web UI)
   - **Staging** → Amazon SES en sandbox
   - **Producción** → Amazon SES fuera de sandbox

Proveedor inicial: **Amazon SES** (~USD 0.10 / 1.000 emails). Diseño preparado
para swap a cualquier otro proveedor sin tocar código consumidor.

**Lo que esta doc NO define**:
- Templates concretos del producto final (los agrega cada proyecto).
- Eventos del dominio que disparan emails (los define cada consumidor).
- Estrategia de notificaciones multi-canal (push, SMS, inbox) — es otra capa
  encima de esta. Esto es solo email.

---

## 2. Decisiones (no re-discutir sin info nueva)

| Decisión | Por qué |
|----------|---------|
| Proveedor inicial = **Amazon SES** | Costo más bajo del mercado, alta deliverability, sin editor de templates propietario. |
| Templates en **MJML + Jinja2** | MJML genera HTML responsive sin pelear con `<table>` anidadas. Jinja2 da variables Python normales. Todo en repo, testable. |
| **Adapter pattern** (no API directa) | Provider-agnostic. Cambio de proveedor = 1 archivo. Permite testear sin enviar. |
| **Mailpit en local** | Captura emails sin enviar. Web UI en `localhost:8025`. Cero riesgo de mandar a usuarios reales por error. |
| **SNS webhook** para bounces/complaints | Obligatorio en SES — sin esto AWS suspende la cuenta. Auto-deshabilita destinatarios problemáticos. |
| **Tabla `EmailMessage`** para auditoría | Trazabilidad: qué se mandó, a quién, cuándo, qué pasó. Necesario para soporte y reportes. |
| **Tabla `EmailSuppression`** para bloqueados | Lista de bouncers/complainers/unsubs. Se consulta antes de cada envío. |
| **Envío asíncrono vía Celery** | Mandar emails dentro del request bloquea la API. Worker dedicado para envío + retry exponencial. |

---

## 3. Arquitectura en capas

```
┌──────────────────────────────────────────────────────────────┐
│  CONSUMIDORES (futuras apps de Django)                       │
│  → llaman a: notifications.services.send(...)                │
│  → pasan un template name y un dict de context               │
└────────────────────────┬─────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────────┐
│  CAPA DE SERVICIO  (apps/notifications/services/)            │
│  - send(to, template, context, ...)                          │
│  - render_template(template, context) → (subject, html)      │
│  - check_suppression(email) → bool                           │
│  - persist EmailMessage row                                  │
│  - enqueue Celery task                                       │
└────────────────────────┬─────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────────┐
│  ADAPTER (apps/notifications/adapters/)                      │
│  Protocol: EmailAdapter                                      │
│   .send(payload) → message_id                                │
│                                                              │
│  Implementaciones intercambiables:                           │
│  - SESAdapter (boto3) ← producción / staging                 │
│  - SMTPAdapter (Django built-in) ← local con Mailpit         │
│  - ConsoleAdapter ← tests                                    │
│  - (Resend, Postmark, etc. en el futuro)                     │
└────────────────────────┬─────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────────┐
│  PROVEEDOR ACTIVO                                            │
│  ENV=local      → Mailpit (SMTP local, sin entrega real)     │
│  ENV=staging    → AWS SES (sandbox)                          │
│  ENV=production → AWS SES (out-of-sandbox)                   │
└──────────────────────────────────────────────────────────────┘

         ┌─────────────────────────────────────┐
         │  SNS WEBHOOK (entrante de AWS)      │
         │  POST /api/v1/email-events/         │
         │  → marca EmailMessage como bounced  │
         │  → agrega a EmailSuppression        │
         └─────────────────────────────────────┘
```

**Regla de oro**: los módulos consumidores **solo** llaman a
`notifications.services.send(...)`. Nunca importan `boto3`, `django-ses`
ni un adapter directo. Esto es lo que hace barato el swap de proveedor.

---

## 4. Stack técnico

```
# requirements.txt (agregar al backend)
boto3==1.34.0              # cliente AWS para SES
jinja2==3.1.4              # render de templates
mjml-python==1.4.0         # MJML → HTML responsive
premailer==3.10.0          # inline CSS (algunos clientes de email lo necesitan)
beautifulsoup4==4.12.0     # generar text/plain desde HTML automáticamente
```

> Mantén las versiones pineadas. Si `mjml-python` da problemas en producción
> (es wrapper Node), alternativa: precompilar MJML en build time con la CLI
> oficial y commitear los `.html` resultantes.

---

## 5. Estructura de archivos

Todo el código vive en una nueva app Django `notifications`:

```
backend/
└── apps/
    └── notifications/
        ├── __init__.py
        ├── apps.py
        ├── adapters/
        │   ├── __init__.py
        │   ├── base.py                   # Protocol EmailAdapter
        │   ├── ses.py                    # SESAdapter
        │   ├── smtp.py                   # SMTPAdapter (Mailpit + cualquier SMTP)
        │   └── console.py                # ConsoleAdapter (tests)
        ├── services/
        │   ├── __init__.py
        │   ├── email.py                  # send(), render_template()
        │   └── email_events.py           # handle_sns_message()
        ├── models/
        │   ├── __init__.py
        │   ├── email_message.py          # EmailMessage
        │   └── email_suppression.py      # EmailSuppression
        ├── tasks.py                      # Celery: send_email_task
        ├── views.py                      # webhook SNS
        ├── urls.py
        ├── admin.py
        ├── filters.py                    # helpers Jinja (opcionales)
        ├── templates/
        │   └── email/
        │       ├── _layout.mjml.j2       # layout base que extienden los consumidores
        │       └── _example.mjml.j2      # ejemplo de referencia (no se usa en prod)
        ├── migrations/
        └── tests/
            ├── test_send.py
            ├── test_adapters.py
            ├── test_suppression.py
            └── test_webhook.py
```

Registrar en `INSTALLED_APPS`:

```python
# settings/base.py
INSTALLED_APPS = [
    # ... otros ...
    "apps.notifications",
]
```

---

## 6. Configuración por ambiente

### `settings/base.py`

```python
import os

# Adapter a usar internamente — define qué implementación recibe los envíos
NOTIFICATIONS_EMAIL_ADAPTER = os.environ.get(
    "NOTIFICATIONS_EMAIL_ADAPTER", "smtp"     # smtp | ses | console
)

# Datos del remitente
DEFAULT_FROM_EMAIL = os.environ.get(
    "DEFAULT_FROM_EMAIL", "no-reply@local.test"
)
SERVER_EMAIL = os.environ.get("SERVER_EMAIL", DEFAULT_FROM_EMAIL)

# SMTP (para Mailpit local o cualquier SMTP genérico)
EMAIL_HOST = os.environ.get("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "1025"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "false").lower() == "true"

# SES (solo si NOTIFICATIONS_EMAIL_ADAPTER=ses)
AWS_SES_ACCESS_KEY_ID = os.environ.get("AWS_SES_ACCESS_KEY_ID", "")
AWS_SES_SECRET_ACCESS_KEY = os.environ.get("AWS_SES_SECRET_ACCESS_KEY", "")
AWS_SES_REGION_NAME = os.environ.get("AWS_SES_REGION_NAME", "us-east-1")
AWS_SES_CONFIGURATION_SET = os.environ.get("AWS_SES_CONFIGURATION_SET", "")

# Auditoría
NOTIFICATIONS_PERSIST_BODY = os.environ.get(
    "NOTIFICATIONS_PERSIST_BODY", "false"
).lower() == "true"   # default off (peso y privacidad)
```

### `.env.local` (con Mailpit)

```bash
NOTIFICATIONS_EMAIL_ADAPTER=smtp
EMAIL_HOST=localhost
EMAIL_PORT=1025
EMAIL_USE_TLS=false
DEFAULT_FROM_EMAIL=no-reply@local.test
```

### `.env.staging`

```bash
NOTIFICATIONS_EMAIL_ADAPTER=ses
AWS_SES_ACCESS_KEY_ID=AKIA...
AWS_SES_SECRET_ACCESS_KEY=...
AWS_SES_REGION_NAME=us-east-1
AWS_SES_CONFIGURATION_SET=main
DEFAULT_FROM_EMAIL=no-reply@staging.example.com
```

### `.env.production`

```bash
NOTIFICATIONS_EMAIL_ADAPTER=ses
AWS_SES_ACCESS_KEY_ID=AKIA...
AWS_SES_SECRET_ACCESS_KEY=...
AWS_SES_REGION_NAME=us-east-1
AWS_SES_CONFIGURATION_SET=main
DEFAULT_FROM_EMAIL=no-reply@example.com
```

---

## 7. El adapter pattern

### `apps/notifications/adapters/base.py`

```python
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class EmailPayload:
    """Payload neutral que cada adapter sabe cómo enviar."""
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
    """
    Contrato que TODO adapter cumple. Cambiar de proveedor =
    implementar este protocolo + cambiar NOTIFICATIONS_EMAIL_ADAPTER.
    """

    def send(self, payload: EmailPayload) -> str:
        """
        Envía el email. Retorna el message_id del proveedor.
        Levanta EmailSendError en caso de fallo permanente.
        """
        ...


class EmailSendError(Exception):
    """Error al enviar. Si .is_transient → Celery reintenta."""
    def __init__(self, message: str, *, is_transient: bool = False):
        super().__init__(message)
        self.is_transient = is_transient
```

### `apps/notifications/adapters/ses.py`

```python
import boto3
from botocore.exceptions import ClientError
from django.conf import settings

from .base import EmailPayload, EmailSendError


class SESAdapter:
    """Adapter para Amazon SES vía boto3 SES v2."""

    def __init__(self):
        self.client = boto3.client(
            "sesv2",
            region_name=settings.AWS_SES_REGION_NAME,
            aws_access_key_id=settings.AWS_SES_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SES_SECRET_ACCESS_KEY,
        )

    def send(self, payload: EmailPayload) -> str:
        from_email = payload.from_email or settings.DEFAULT_FROM_EMAIL
        body_content = {"Html": {"Data": payload.html, "Charset": "UTF-8"}}
        if payload.text:
            body_content["Text"] = {"Data": payload.text, "Charset": "UTF-8"}

        request = {
            "FromEmailAddress": from_email,
            "Destination": {"ToAddresses": [payload.to]},
            "Content": {
                "Simple": {
                    "Subject": {"Data": payload.subject, "Charset": "UTF-8"},
                    "Body": body_content,
                }
            },
        }
        if payload.reply_to:
            request["ReplyToAddresses"] = payload.reply_to
        config_set = payload.configuration_set or settings.AWS_SES_CONFIGURATION_SET
        if config_set:
            request["ConfigurationSetName"] = config_set
        if payload.tags:
            request["EmailTags"] = [
                {"Name": k, "Value": str(v)} for k, v in payload.tags.items()
            ]

        try:
            response = self.client.send_email(**request)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            transient = code in {"Throttling", "ServiceUnavailable", "RequestTimeout"}
            raise EmailSendError(str(e), is_transient=transient) from e

        return response["MessageId"]
```

### `apps/notifications/adapters/smtp.py`

```python
import uuid

from django.core.mail import EmailMultiAlternatives, get_connection

from .base import EmailPayload, EmailSendError


class SMTPAdapter:
    """
    Adapter genérico SMTP. Sirve para:
    - Mailpit local (sin entrega real)
    - Cualquier proveedor SMTP (Postmark, Mailgun SMTP, etc.)
    Usa el backend SMTP nativo de Django.
    """

    def send(self, payload: EmailPayload) -> str:
        msg = EmailMultiAlternatives(
            subject=payload.subject,
            body=payload.text or _html_to_text(payload.html),
            from_email=payload.from_email,
            to=[payload.to],
            reply_to=payload.reply_to or None,
            headers=payload.headers or None,
            connection=get_connection(
                "django.core.mail.backends.smtp.EmailBackend"
            ),
        )
        msg.attach_alternative(payload.html, "text/html")
        try:
            sent = msg.send(fail_silently=False)
        except Exception as e:
            raise EmailSendError(str(e), is_transient=True) from e
        if sent == 0:
            raise EmailSendError("send() returned 0", is_transient=True)
        return msg.extra_headers.get("Message-ID") or f"local-{uuid.uuid4()}"


def _html_to_text(html: str) -> str:
    from bs4 import BeautifulSoup
    return BeautifulSoup(html, "html.parser").get_text(separator="\n").strip()
```

### `apps/notifications/adapters/console.py`

```python
from .base import EmailPayload


class ConsoleAdapter:
    """Para tests y debugging. Imprime el email en stdout y lo acumula."""

    def __init__(self):
        self.sent: list[EmailPayload] = []

    def send(self, payload: EmailPayload) -> str:
        print(
            f"\n──── EMAIL ────\n"
            f"To: {payload.to}\n"
            f"Subject: {payload.subject}\n"
            f"Tags: {payload.tags}\n"
            f"────\n"
            f"{payload.html[:300]}...\n"
        )
        self.sent.append(payload)
        return f"console-{len(self.sent)}"
```

### Factory que escoge según settings

```python
# apps/notifications/adapters/__init__.py

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
    """Singleton del adapter activo según settings."""
    global _instance
    if _instance is None:
        name = settings.NOTIFICATIONS_EMAIL_ADAPTER
        if name not in _ADAPTERS:
            raise ValueError(
                f"Adapter desconocido: {name}. "
                f"Opciones: {list(_ADAPTERS)}"
            )
        _instance = _ADAPTERS[name]()
    return _instance


def reset_email_adapter() -> None:
    """Para tests que cambian settings.NOTIFICATIONS_EMAIL_ADAPTER."""
    global _instance
    _instance = None


__all__ = [
    "EmailAdapter", "EmailPayload", "EmailSendError",
    "get_email_adapter", "reset_email_adapter",
]
```

**Cómo agregar un proveedor nuevo mañana** (ej. Resend):

1. Crear `apps/notifications/adapters/resend.py` implementando el protocolo `EmailAdapter`.
2. Registrarlo en `_ADAPTERS = {..., "resend": ResendAdapter}`.
3. `NOTIFICATIONS_EMAIL_ADAPTER=resend` en `.env`.
4. Cero cambios en código consumidor. Cero cambios en templates.

---

## 8. Templates MJML + Jinja2

### Layout base (genérico, lo extienden los proyectos consumidores)

```mjml
{# apps/notifications/templates/email/_layout.mjml.j2 #}
<mjml>
  <mj-head>
    <mj-title>{% block title %}{{ subject }}{% endblock %}</mj-title>
    <mj-preview>{% block preview %}{% endblock %}</mj-preview>
    <mj-attributes>
      <mj-all font-family="Helvetica, Arial, sans-serif" />
      <mj-text color="#202020" font-size="14px" line-height="1.55" />
      <mj-button background-color="#2563eb" color="#ffffff"
                  font-weight="600" border-radius="6px" />
    </mj-attributes>
    <mj-style>
      .footer-link { color: #5f6975; text-decoration: none; }
    </mj-style>
  </mj-head>
  <mj-body background-color="#f4f5f7">
    <mj-section background-color="#ffffff" padding="24px">
      <mj-column>
        {% block header %}
          <mj-text font-size="18px" font-weight="600">
            {{ app_name|default('Notification') }}
          </mj-text>
          <mj-divider border-color="#e5e7eb" border-width="1px" padding="8px 0" />
        {% endblock %}
      </mj-column>
    </mj-section>

    <mj-section background-color="#ffffff" padding="0 24px 24px">
      <mj-column>
        {% block content %}{% endblock %}
      </mj-column>
    </mj-section>

    <mj-section background-color="#f4f5f7" padding="16px">
      <mj-column>
        <mj-text align="center" color="#5f6975" font-size="11px">
          {% block footer %}
            Mensaje automático. No respondas a este email.
          {% endblock %}
        </mj-text>
      </mj-column>
    </mj-section>
  </mj-body>
</mjml>
```

### Ejemplo de template concreto (referencia, no se usa en producción)

```mjml
{# apps/notifications/templates/email/_example.mjml.j2 #}
{% extends "email/_layout.mjml.j2" %}

{% block preview %}Ejemplo de email — {{ user_name }}{% endblock %}

{% block content %}
  <mj-text font-size="16px" font-weight="600">
    Hola {{ user_name }},
  </mj-text>
  <mj-text>
    Este es un template de ejemplo. Reemplázalo por uno propio del proyecto
    consumidor cuando lo necesites.
  </mj-text>
  <mj-button href="{{ action_url }}">Ver más</mj-button>
{% endblock %}
```

```jinja
{# apps/notifications/templates/email/_example.subject.j2 #}
Ejemplo para {{ user_name }}
```

### Helpers Jinja (opcionales)

Por default ninguno. Cada proyecto consumidor agrega sus propios filtros en
`filters.py` si los necesita. Plantilla mínima:

```python
# apps/notifications/filters.py
FILTERS = {
    # Cada proyecto define los suyos.
    # Ejemplo: "money": lambda v: f"${v:,.0f}",
}
```

**Cómo agregar un template nuevo**:

1. Crear `apps/notifications/templates/email/<nombre>.mjml.j2` (cuerpo HTML).
2. Crear `apps/notifications/templates/email/<nombre>.subject.j2` (asunto).
3. (Opcional) `<nombre>.txt.j2` para versión plana.
4. Llamar `send(template="<nombre>", context={...})` desde el consumidor.

---

## 9. El servicio público — API que llaman los consumidores

```python
# apps/notifications/services/email.py
from pathlib import Path
from typing import Any

import premailer
from django.conf import settings
from django.utils import timezone
from jinja2 import Environment, FileSystemLoader, select_autoescape
from mjml import mjml_to_html

from apps.notifications.adapters import (
    EmailPayload, EmailSendError, get_email_adapter,
)
from apps.notifications.filters import FILTERS
from apps.notifications.models import EmailMessage, EmailSuppression

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


def _build_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "mjml.j2"]),
    )
    env.filters.update(FILTERS)
    return env


_JINJA = _build_env()


def render_email(template: str, context: dict[str, Any]) -> tuple[str, str]:
    """Renderiza email/<template>.mjml.j2 → (subject, html_inlineado)."""
    mjml_src = _JINJA.get_template(f"email/{template}.mjml.j2").render(**context)
    html = mjml_to_html(mjml_src).html
    html = premailer.transform(html, remove_classes=False)
    subject = _JINJA.get_template(f"email/{template}.subject.j2").render(**context).strip()
    return subject, html


def is_suppressed(email: str) -> bool:
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
    sync: bool = False,
) -> EmailMessage:
    """
    API pública que usan los consumidores.

    Args:
        to: dirección destino.
        template: nombre del template (sin extensión). Ej. "welcome".
        context: dict pasado a Jinja2.
        related: objeto opaco al que se asocia este email (para auditoría).
        tags: dict de tags que se pasan al proveedor.
        reply_to: lista de Reply-To.
        user: User opcional al que pertenece este envío.
        sync: si True envía inmediatamente; si False (default) encola Celery.

    Returns:
        EmailMessage row creado.
    """
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

    if is_suppressed(to):
        record.status = EmailMessage.Status.SUPPRESSED
        record.error_message = "Email en lista de supresión"
        record.save(update_fields=["status", "error_message"])
        return record

    if sync:
        _do_send(record.pk, html, subject, reply_to or [])
    else:
        from apps.notifications.tasks import send_email_task
        send_email_task.delay(record.pk, html, subject, reply_to or [])

    return record


def _do_send(message_pk, html, subject, reply_to):
    """Envío real — llamado por la task Celery o por sync=True."""
    record = EmailMessage.objects.get(pk=message_pk)
    payload = EmailPayload(
        to=record.to_address,
        subject=subject,
        html=html,
        reply_to=reply_to,
        tags=record.tags,
        configuration_set=settings.AWS_SES_CONFIGURATION_SET or None,
    )
    try:
        message_id = get_email_adapter().send(payload)
    except EmailSendError as e:
        record.status = EmailMessage.Status.FAILED
        record.error_message = str(e)
        record.save(update_fields=["status", "error_message"])
        if e.is_transient:
            raise   # Celery reintenta
        return
    record.provider_message_id = message_id
    record.status = EmailMessage.Status.SENT
    record.sent_at = timezone.now()
    record.save(update_fields=["provider_message_id", "status", "sent_at"])


def _safe_context(context: dict) -> dict:
    """Sanitiza el snapshot que guardamos (quita objetos no serializables)."""
    out = {}
    for k, v in context.items():
        if hasattr(v, "pk"):
            out[k] = {"_model": type(v).__name__, "pk": str(v.pk)}
        elif isinstance(v, (str, int, float, bool, type(None))):
            out[k] = v
        else:
            out[k] = str(v)[:200]
    return out
```

---

## 10. Modelos para auditoría

### `apps/notifications/models/email_message.py`

```python
from django.conf import settings
from django.db import models


class EmailMessage(models.Model):
    """Cada email que la plataforma intenta enviar. Inmutable tras estado terminal."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pendiente"
        SENT = "SENT", "Enviado al proveedor"
        DELIVERED = "DELIVERED", "Entregado al MTA destino"
        BOUNCED = "BOUNCED", "Rebotó"
        COMPLAINED = "COMPLAINED", "Marcado como spam"
        FAILED = "FAILED", "Error al enviar"
        SUPPRESSED = "SUPPRESSED", "Destinatario en lista de supresión"

    to_address = models.EmailField(db_index=True)
    to_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="emails_received")

    template_name = models.CharField(max_length=80, db_index=True)
    subject = models.CharField(max_length=255)
    context_snapshot = models.JSONField(default=dict, blank=True)

    provider = models.CharField(max_length=20)  # ses, smtp, console, etc.
    provider_message_id = models.CharField(max_length=255, blank=True, db_index=True)

    status = models.CharField(
        max_length=20, choices=Status.choices,
        default=Status.PENDING, db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    bounced_at = models.DateTimeField(null=True, blank=True)
    bounce_type = models.CharField(max_length=40, blank=True)
    bounce_subtype = models.CharField(max_length=80, blank=True)
    complained_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)

    # Vínculo opaco a la entidad que generó este email
    related_object_type = models.CharField(max_length=80, blank=True, db_index=True)
    related_object_id = models.CharField(max_length=80, blank=True, db_index=True)

    tags = models.JSONField(default=dict, blank=True)

    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["to_address", "-created"]),
            models.Index(fields=["status", "-created"]),
            models.Index(fields=["related_object_type", "related_object_id"]),
        ]
        ordering = ["-created"]
```

> Si el stack base tiene una clase `BaseModelGeneric` con uuid/slug/is_active,
> heredar de ella en lugar de `models.Model`. Idem para `TimeStampedModel`.

### `apps/notifications/models/email_suppression.py`

```python
from django.db import models


class EmailSuppression(models.Model):
    """Direcciones que NO debemos enviar más (rebotes, complaints, unsubs)."""

    class Reason(models.TextChoices):
        BOUNCE_PERMANENT = "BOUNCE_PERMANENT", "Rebote permanente"
        COMPLAINT = "COMPLAINT", "Marcó como spam"
        UNSUBSCRIBE = "UNSUBSCRIBE", "Se desuscribió"
        MANUAL = "MANUAL", "Bloqueo manual"

    email = models.EmailField(unique=True, db_index=True)
    reason = models.CharField(max_length=20, choices=Reason.choices)
    detail = models.CharField(max_length=200, blank=True)   # ej. "MailboxFull"
    notes = models.TextField(blank=True)

    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created"]
```

---

## 11. Celery task de envío (async + retry)

```python
# apps/notifications/tasks.py
from celery import shared_task

from apps.notifications.adapters import EmailSendError
from apps.notifications.services.email import _do_send


@shared_task(
    bind=True,
    autoretry_for=(EmailSendError,),
    retry_backoff=True,       # 1s, 2s, 4s, 8s...
    retry_jitter=True,
    max_retries=5,
)
def send_email_task(self, message_pk: str, html: str, subject: str, reply_to: list[str]):
    _do_send(message_pk, html, subject, reply_to)
```

---

## 12. Webhook SNS (bounces, complaints, deliveries)

### `apps/notifications/views.py`

```python
import json
import urllib.request

from django.http import HttpResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.notifications.services.email_events import handle_sns_message


@csrf_exempt
@require_POST
def ses_webhook(request):
    """Endpoint para AWS SNS. URL: /api/v1/email-events/"""
    try:
        envelope = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponseBadRequest("invalid json")

    msg_type = envelope.get("Type")

    if msg_type == "SubscriptionConfirmation":
        # Al dar de alta el endpoint, SNS manda este tipo. Confirmamos
        # haciendo GET al SubscribeURL.
        urllib.request.urlopen(envelope["SubscribeURL"], timeout=10).read()
        return HttpResponse("subscribed")

    if msg_type == "Notification":
        # TODO: validar firma SNS con cert público (envelope["SigningCertURL"])
        # https://docs.aws.amazon.com/sns/latest/dg/sns-verify-signature-of-message.html
        try:
            payload = json.loads(envelope["Message"])
        except json.JSONDecodeError:
            return HttpResponseBadRequest("invalid Message")
        handle_sns_message(payload)
        return HttpResponse("ok")

    return HttpResponse("ignored")
```

### `apps/notifications/services/email_events.py`

```python
from django.utils.dateparse import parse_datetime

from apps.notifications.models import EmailMessage, EmailSuppression


def handle_sns_message(payload: dict) -> None:
    """
    Procesa un evento SES (Bounce / Complaint / Delivery).
    Formato: https://docs.aws.amazon.com/ses/latest/dg/notification-contents.html
    """
    event_type = payload.get("eventType") or payload.get("notificationType")
    mail = payload.get("mail", {})
    message_id = mail.get("messageId")
    if not message_id:
        return

    try:
        record = EmailMessage.objects.get(provider_message_id=message_id)
    except EmailMessage.DoesNotExist:
        return   # email fuera del sistema o ya purgado

    if event_type == "Bounce":
        bounce = payload["bounce"]
        record.status = EmailMessage.Status.BOUNCED
        record.bounce_type = bounce.get("bounceType", "")
        record.bounce_subtype = bounce.get("bounceSubType", "")
        record.bounced_at = parse_datetime(bounce.get("timestamp", "")) or None
        record.save(update_fields=[
            "status", "bounce_type", "bounce_subtype", "bounced_at"])

        if record.bounce_type == "Permanent":
            for r in bounce.get("bouncedRecipients", []):
                EmailSuppression.objects.get_or_create(
                    email=r["emailAddress"],
                    defaults={
                        "reason": EmailSuppression.Reason.BOUNCE_PERMANENT,
                        "detail": record.bounce_subtype,
                    },
                )

    elif event_type == "Complaint":
        complaint = payload["complaint"]
        record.status = EmailMessage.Status.COMPLAINED
        record.complained_at = parse_datetime(complaint.get("timestamp", "")) or None
        record.save(update_fields=["status", "complained_at"])
        for r in complaint.get("complainedRecipients", []):
            EmailSuppression.objects.get_or_create(
                email=r["emailAddress"],
                defaults={"reason": EmailSuppression.Reason.COMPLAINT},
            )

    elif event_type == "Delivery":
        delivery = payload["delivery"]
        record.status = EmailMessage.Status.DELIVERED
        record.delivered_at = parse_datetime(delivery.get("timestamp", "")) or None
        record.save(update_fields=["status", "delivered_at"])
```

### URL

```python
# apps/notifications/urls.py
from django.urls import path
from .views import ses_webhook

urlpatterns = [
    path("email-events/", ses_webhook, name="ses-webhook"),
]
```

```python
# en el urls.py principal del backend, agregar:
path("api/v1/", include("apps.notifications.urls")),
```

---

## 13. Setup Mailpit (local)

### `docker-compose.yml` (agregar servicio)

```yaml
services:
  mailpit:
    image: axllent/mailpit:latest
    container_name: mailpit
    restart: unless-stopped
    ports:
      - "1025:1025"   # SMTP
      - "8025:8025"   # Web UI
    environment:
      MP_MAX_MESSAGES: 5000
      MP_DATA_FILE: /data/mailpit.db
    volumes:
      - mailpit_data:/data

volumes:
  mailpit_data:
```

### Flujo de desarrollo

```bash
# 1. Levantar Mailpit
docker-compose up -d mailpit

# 2. Confirmar que las settings apuntan a localhost:1025
cat .env | grep EMAIL_HOST

# 3. Disparar un email de prueba desde shell
python manage.py shell
>>> from apps.notifications.services.email import send
>>> send(to="test@local", template="_example",
...      context={"user_name": "Juan", "action_url": "http://x"},
...      sync=True)

# 4. Abrir Mailpit en el navegador
open http://localhost:8025
# Verás el email completo: HTML renderizado, headers, source.
```

---

## 14. Setup Amazon SES — paso a paso

### 14.1 Crear cuenta AWS y abrir SES

1. Acceder a [console.aws.amazon.com](https://console.aws.amazon.com).
2. Seleccionar región: **us-east-1** (más barata y mayor capacidad).
3. SES → **Verified identities** → **Create identity**:
   - Tipo: **Domain**
   - Dominio: `tu-dominio.com`
   - **Use a custom MAIL FROM domain**: `mail.tu-dominio.com` (recomendado)
   - **Easy DKIM**: yes (AWS genera 3 CNAMEs)

### 14.2 Configurar DNS

Agregar al DNS de tu dominio (Cloudflare / Route53 / Namecheap / etc):

```
# DKIM (3 registros que te da AWS, copia/pega)
abc123._domainkey.tu-dominio.com  CNAME  abc123.dkim.amazonses.com
def456._domainkey.tu-dominio.com  CNAME  def456.dkim.amazonses.com
ghi789._domainkey.tu-dominio.com  CNAME  ghi789.dkim.amazonses.com

# MAIL FROM
mail.tu-dominio.com               MX     10 feedback-smtp.us-east-1.amazonses.com
mail.tu-dominio.com               TXT    "v=spf1 include:amazonses.com ~all"

# SPF del dominio principal
tu-dominio.com                    TXT    "v=spf1 include:amazonses.com ~all"

# DMARC (recomendado, política suave al inicio)
_dmarc.tu-dominio.com             TXT    "v=DMARC1; p=none; rua=mailto:dmarc@tu-dominio.com"
```

Esperar ~10-30 min. AWS marca el identity como "Verified".

### 14.3 Salir del sandbox

Por default toda cuenta SES nueva está en **sandbox**:

| Cosa | Sandbox | Producción |
|---|---|---|
| Destinatarios | Solo emails verificados manualmente | Cualquier email |
| Límite diario | 200 emails/24h | Empieza ~50k, crece automáticamente |
| Límite/segundo | 1 email/s | Empieza ~14/s, crece |

**Cómo salir**:

1. SES → **Account dashboard** → banner "Your account is in the sandbox" → **Request production access**.
2. Llenar el formulario:
   - **Mail type**: Transactional
   - **Website URL**: tu sitio
   - **Use case description**: describir el producto y los emails que envías. Ejemplo genérico:
     > "SaaS B2B. Enviamos emails transaccionales: confirmaciones de cuenta, restablecimiento de contraseña, notificaciones de eventos del sistema solicitadas por usuarios registrados. Volumen estimado año 1: ~50.000 emails/mes."
   - **Process for handling bounces / complaints**: "SNS topic con webhook a `/api/v1/email-events/`. Auto-deshabilitamos destinatarios al primer hard bounce o complaint. Lista de supresión persistida en BD y consultada antes de cada envío."
   - **Process for handling unsubscribes**: "Link unsubscribe en footers de emails no críticos."
   - Aceptar Acceptable Use Policy.
3. Enviar. AWS responde en **24-48h hábiles**.

### 14.4 Configuration set + tópico SNS

Mientras esperas el approval, dejas listo el resto:

1. SES → **Configuration sets** → **Create**: nombre `main`, reputation tracking on, event publishing → SNS.
2. **SNS** → **Topics** → **Create topic**: `ses-events`.
3. SES configuration set → event publishing → seleccionar tópico `ses-events` y los eventos: `Send`, `Delivery`, `Bounce`, `Complaint`, `Reject`.
4. SNS → tópico → **Create subscription**:
   - Protocol: **HTTPS**
   - Endpoint: `https://api.tu-dominio.com/api/v1/email-events/`
5. SNS le pegará al endpoint con `SubscriptionConfirmation` y el webhook hace GET al `SubscribeURL` automáticamente (ya implementado en `views.py`).

### 14.5 IAM user para boto3

1. **IAM** → **Users** → **Add user**: `backend-ses`.
2. **Attach policies** → Create inline policy:
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [{
       "Effect": "Allow",
       "Action": [
         "ses:SendEmail",
         "ses:SendRawEmail",
         "ses:GetSendQuota"
       ],
       "Resource": "*"
     }]
   }
   ```
3. **Security credentials** → **Create access key** → tipo "Application running outside AWS" → guardar en secret manager / `.env` de producción.

---

## 15. Testing

### Tests unitarios — con ConsoleAdapter

```python
# apps/notifications/tests/test_send.py
from django.test import TestCase, override_settings

from apps.notifications.adapters import reset_email_adapter, get_email_adapter
from apps.notifications.models import EmailSuppression
from apps.notifications.services.email import send


@override_settings(NOTIFICATIONS_EMAIL_ADAPTER="console")
class SendEmailTests(TestCase):
    def setUp(self):
        reset_email_adapter()

    def test_send_example(self):
        record = send(
            to="user@example.com",
            template="_example",
            context={"user_name": "Juan", "action_url": "http://x"},
            sync=True,
        )
        self.assertEqual(record.status, "SENT")
        adapter = get_email_adapter()
        self.assertEqual(len(adapter.sent), 1)
        self.assertIn("Juan", adapter.sent[0].subject)

    def test_email_suprimido_no_se_envia(self):
        EmailSuppression.objects.create(
            email="bad@x", reason=EmailSuppression.Reason.BOUNCE_PERMANENT)
        record = send(to="bad@x", template="_example",
                      context={"user_name": "x", "action_url": "x"},
                      sync=True)
        self.assertEqual(record.status, "SUPPRESSED")
```

### Test del webhook SNS

```python
# apps/notifications/tests/test_webhook.py
import json

from django.test import Client, TestCase

from apps.notifications.models import EmailMessage, EmailSuppression


class SnsWebhookTests(TestCase):
    def test_bounce_marca_supresion(self):
        EmailMessage.objects.create(
            to_address="bouncer@x",
            provider="ses",
            provider_message_id="msg-1",
            template_name="x", subject="x",
            status=EmailMessage.Status.SENT,
        )
        envelope = {
            "Type": "Notification",
            "Message": json.dumps({
                "notificationType": "Bounce",
                "mail": {"messageId": "msg-1"},
                "bounce": {
                    "bounceType": "Permanent",
                    "bounceSubType": "General",
                    "timestamp": "2026-05-28T12:00:00Z",
                    "bouncedRecipients": [{"emailAddress": "bouncer@x"}],
                },
            }),
        }
        Client().post(
            "/api/v1/email-events/",
            data=json.dumps(envelope),
            content_type="application/json",
        )
        self.assertTrue(
            EmailSuppression.objects.filter(email="bouncer@x").exists()
        )
```

---

## 16. Cómo cambiar de proveedor (procedimiento)

Ejemplo: migrar de SES a Resend.

1. Crear `apps/notifications/adapters/resend.py`:
   ```python
   import resend
   from django.conf import settings
   from .base import EmailPayload, EmailSendError

   class ResendAdapter:
       def __init__(self):
           resend.api_key = settings.RESEND_API_KEY

       def send(self, payload: EmailPayload) -> str:
           try:
               r = resend.Emails.send({
                   "from": payload.from_email or settings.DEFAULT_FROM_EMAIL,
                   "to": [payload.to],
                   "subject": payload.subject,
                   "html": payload.html,
                   "reply_to": payload.reply_to or None,
                   "tags": [{"name": k, "value": str(v)}
                            for k, v in payload.tags.items()],
               })
           except Exception as e:
               raise EmailSendError(str(e), is_transient=True) from e
           return r["id"]
   ```

2. Registrar en factory:
   ```python
   # adapters/__init__.py
   from .resend import ResendAdapter
   _ADAPTERS["resend"] = ResendAdapter
   ```

3. Cambiar `.env`:
   ```bash
   NOTIFICATIONS_EMAIL_ADAPTER=resend
   RESEND_API_KEY=re_...
   ```

4. Reemplazar el webhook SNS por el webhook de Resend
   (`apps/notifications/services/email_events.py` gana un `handle_resend_event`).

**Cero cambios** en consumidores. **Cero cambios** en templates.
**Cero migraciones** de BD. **Cero downtime** (cambio en un release normal).

---

## 17. Checklist de implementación

### Sprint 1 — Infraestructura base
- [ ] Crear app `apps/notifications/`
- [ ] Agregar packages a `requirements.txt`
- [ ] Crear modelos `EmailMessage` y `EmailSuppression` + migraciones
- [ ] Implementar `adapters/base.py`, `adapters/smtp.py`, `adapters/console.py`
- [ ] Crear factory `adapters/__init__.py` con `get_email_adapter()`
- [ ] Implementar `services/email.py` con `send()` y `render_email()`
- [ ] Crear `_layout.mjml.j2` base y `_example.mjml.j2` de referencia
- [ ] Configurar settings.py por ambiente
- [ ] Agregar Mailpit a `docker-compose.yml`
- [ ] Test: enviar email de prueba a Mailpit desde `manage.py shell`

### Sprint 2 — SES + bounces
- [ ] Implementar `adapters/ses.py`
- [ ] Crear cuenta AWS, verificar dominio, configurar DNS
- [ ] Solicitar salida de sandbox (24-48h)
- [ ] Crear IAM user con permisos mínimos
- [ ] Crear configuration set con SNS publishing
- [ ] Implementar `views.py:ses_webhook` y `services/email_events.py`
- [ ] Suscribir tópico SNS al endpoint y confirmar
- [ ] Tests unitarios y del webhook

### Sprint 3 — Async + observabilidad
- [ ] Celery task `send_email_task` con retry y backoff
- [ ] Logs estructurados en cada envío (success/failure)
- [ ] Dashboard básico en Django admin: filtros por estado, búsqueda por email
- [ ] (Opcional) Métricas Prometheus: emails sent/bounced/failed por minuto

---

## 18. Cosas que NO hacer

- ❌ **No llamar a `boto3` o adapters directamente** desde otras apps. Solo via `notifications.services.send(...)`.
- ❌ **No persistir el HTML completo** en `EmailMessage` por default. Pesa mucho. Activable con flag `NOTIFICATIONS_PERSIST_BODY=true` por ambiente si se necesita.
- ❌ **No mandar emails dentro de transacciones DB largas**. Encolar la task DESPUÉS de `commit`, así si el commit falla no se manda email "fantasma" (usar `transaction.on_commit(...)`).
- ❌ **No mandar emails sin verificar suppression list**. Se hace dentro de `send()`, no lo desactives.
- ❌ **No expongas el webhook SNS sin verificar la firma** en producción. AWS publica certs públicos para validar; sin validación cualquiera puede mandar `Bounce` falsos. Hay librerías (`sns-message-validator`) que lo hacen.
- ❌ **No re-uses message_ids** entre envíos. Cada `send()` genera uno nuevo.

---

## 19. Referencias

- [Amazon SES Developer Guide](https://docs.aws.amazon.com/ses/latest/dg/)
- [SES sending limits y reputation](https://docs.aws.amazon.com/ses/latest/dg/manage-sending-quotas.html)
- [SNS event payload format](https://docs.aws.amazon.com/ses/latest/dg/notification-contents.html)
- [SNS signature verification](https://docs.aws.amazon.com/sns/latest/dg/sns-verify-signature-of-message.html)
- [MJML docs](https://documentation.mjml.io/)
- [Mailpit](https://github.com/axllent/mailpit)
