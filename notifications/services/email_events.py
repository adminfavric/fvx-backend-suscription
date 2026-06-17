"""Procesamiento de eventos de SES recibidos vía SNS.

Eventos posibles: ``Send`` / ``Delivery`` / ``Bounce`` / ``Complaint`` / ``Reject``.
Formato oficial: https://docs.aws.amazon.com/ses/latest/dg/notification-contents.html

Política:

- **Bounce permanente** → marca ``EmailMessage`` como BOUNCED y agrega cada
  destinatario rebotado a ``EmailSuppression``.
- **Bounce transitorio** → marca como BOUNCED pero NO suprime (puede ser
  buzón lleno temporalmente, etc.).
- **Complaint** → marca como COMPLAINED y suprime al usuario (lo marcó como
  spam — no le mandes más nunca).
- **Delivery** → marca como DELIVERED (el MTA destino lo aceptó).
- Otros (``Send``, ``Reject``) → ignorados; nuestra propia transición a SENT
  ocurrió antes del envío al proveedor.
"""

from django.apps import apps
from django.utils.dateparse import parse_datetime


def handle_sns_message(payload: dict) -> None:
    """Procesa un mensaje SNS decodificado (ya parseado a dict)."""
    EmailMessage = apps.get_model("notifications", "EmailMessage")
    EmailSuppression = apps.get_model("notifications", "EmailSuppression")

    # SES expone tanto el formato "notification" (eventos legacy) como el
    # "eventType" más nuevo de configuration sets. Probamos ambos.
    event_type = payload.get("eventType") or payload.get("notificationType")
    mail = payload.get("mail", {})
    message_id = mail.get("messageId")
    if not message_id:
        return

    try:
        record = EmailMessage.objects.get(provider_message_id=message_id)
    except EmailMessage.DoesNotExist:
        # Email no nuestro o ya purgado por housekeeping — ignorar.
        return

    if event_type == "Bounce":
        _handle_bounce(record, payload["bounce"], EmailMessage, EmailSuppression)
    elif event_type == "Complaint":
        _handle_complaint(record, payload["complaint"], EmailMessage, EmailSuppression)
    elif event_type == "Delivery":
        _handle_delivery(record, payload["delivery"], EmailMessage)
    # Send / Reject / otros: no-op.


def _handle_bounce(record, bounce: dict, EmailMessage, EmailSuppression) -> None:
    record.status = EmailMessage.Status.BOUNCED
    record.bounce_type = bounce.get("bounceType", "")
    record.bounce_subtype = bounce.get("bounceSubType", "")
    record.bounced_at = parse_datetime(bounce.get("timestamp", "")) or None
    record.save(
        update_fields=[
            "status",
            "bounce_type",
            "bounce_subtype",
            "bounced_at",
        ]
    )

    if record.bounce_type == "Permanent":
        for r in bounce.get("bouncedRecipients", []):
            email = r.get("emailAddress")
            if not email:
                continue
            EmailSuppression.objects.get_or_create(
                email=email,
                defaults={
                    "reason": EmailSuppression.Reason.BOUNCE_PERMANENT,
                    "detail": record.bounce_subtype,
                },
            )


def _handle_complaint(record, complaint: dict, EmailMessage, EmailSuppression) -> None:
    record.status = EmailMessage.Status.COMPLAINED
    record.complained_at = parse_datetime(complaint.get("timestamp", "")) or None
    record.save(update_fields=["status", "complained_at"])

    for r in complaint.get("complainedRecipients", []):
        email = r.get("emailAddress")
        if not email:
            continue
        EmailSuppression.objects.get_or_create(
            email=email,
            defaults={"reason": EmailSuppression.Reason.COMPLAINT},
        )


def _handle_delivery(record, delivery: dict, EmailMessage) -> None:
    record.status = EmailMessage.Status.DELIVERED
    record.delivered_at = parse_datetime(delivery.get("timestamp", "")) or None
    record.save(update_fields=["status", "delivered_at"])
