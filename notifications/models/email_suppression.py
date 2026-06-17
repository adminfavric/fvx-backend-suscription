"""Lista negra de direcciones a las que NO debemos volver a mandar.

Se consulta dentro de ``services.email.send()`` antes de invocar al adapter.
Se pueblen automáticamente desde:

- **Webhook SNS de SES**: bounces permanentes y complaints (los marca como
  ``BOUNCE_PERMANENT`` / ``COMPLAINT``).
- **UI del usuario** (futuro): un link de unsubscribe en footers de emails
  no críticos → ``UNSUBSCRIBE``.
- **Manual**: un admin agrega un email problemático → ``MANUAL``.
"""

from django.db import models

from api.models.base import TimeStampedModel


class EmailSuppression(TimeStampedModel):
    """Direcciones a las que NO mandamos más email."""

    # Ver nota en EmailMessage.UPPERCASE_EXCLUDE_FIELDS: el `detail` y `notes`
    # son texto libre que perdería contenido si se uppercase-iza.
    UPPERCASE_EXCLUDE_FIELDS = ["detail", "notes"]

    class Reason(models.TextChoices):
        BOUNCE_PERMANENT = "BOUNCE_PERMANENT", "Rebote permanente"
        COMPLAINT = "COMPLAINT", "Marcó como spam"
        UNSUBSCRIBE = "UNSUBSCRIBE", "Se desuscribió"
        MANUAL = "MANUAL", "Bloqueo manual"

    email = models.EmailField(unique=True, db_index=True)
    reason = models.CharField(max_length=20, choices=Reason.choices)
    detail = models.CharField(max_length=200, blank=True)  # ej. "MailboxFull"
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created"]
        verbose_name = "Email suprimido"
        verbose_name_plural = "Emails suprimidos"

    def __str__(self) -> str:
        return f"{self.email} ({self.reason})"
