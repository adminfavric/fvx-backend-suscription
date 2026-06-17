"""Auditoría de cada email que la plataforma intenta enviar.

Cada llamada a ``notifications.services.email.send()`` crea una fila acá
antes de invocar al adapter. La fila va por los estados PENDING → SENT →
DELIVERED, o termina en BOUNCED / COMPLAINED / FAILED / SUPPRESSED.

El webhook SNS (``views.ses_webhook``) actualiza la fila con los eventos
que reporta SES (Bounce / Complaint / Delivery).
"""

from django.conf import settings
from django.db import models

from api.models.base import TimeStampedModel


class EmailMessage(TimeStampedModel):
    """Cada email que se intenta mandar — inmutable tras estado terminal."""

    # TimeStampedModel uppercase-iza CharField/TextField por default. Para
    # contenido textual de email (asunto, mensaje de error, bounce details,
    # template names en snake_case) eso destruye la información — explícitamente
    # excluimos todos los text fields aquí.
    UPPERCASE_EXCLUDE_FIELDS = [
        "template_name",
        "subject",
        "provider",
        "provider_message_id",
        "bounce_type",
        "bounce_subtype",
        "error_message",
        "related_object_type",
        "related_object_id",
    ]

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
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="emails_received",
    )

    template_name = models.CharField(max_length=80, db_index=True)
    subject = models.CharField(max_length=255)
    # Snapshot saneado del context — útil para soporte ("¿qué decía el email?")
    # sin guardar PII completa ni el HTML inflado (eso controlable con flag).
    context_snapshot = models.JSONField(default=dict, blank=True)

    provider = models.CharField(max_length=20)  # ses, smtp, console, etc.
    provider_message_id = models.CharField(
        max_length=255,
        blank=True,
        db_index=True,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    bounced_at = models.DateTimeField(null=True, blank=True)
    bounce_type = models.CharField(max_length=40, blank=True)
    bounce_subtype = models.CharField(max_length=80, blank=True)
    complained_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)

    # Vínculo opaco al objeto de negocio que generó el email.
    # Lo usamos como FK polimórfico ligero — el consumidor lo lee/escribe
    # como strings, no necesita ContentType.
    related_object_type = models.CharField(max_length=80, blank=True, db_index=True)
    related_object_id = models.CharField(max_length=80, blank=True, db_index=True)

    tags = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["to_address", "-created"]),
            models.Index(fields=["status", "-created"]),
            models.Index(fields=["related_object_type", "related_object_id"]),
        ]
        ordering = ["-created"]

    def __str__(self) -> str:
        return f"{self.template_name} → {self.to_address} [{self.status}]"
