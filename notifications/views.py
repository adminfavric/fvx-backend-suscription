"""Vistas HTTP del módulo de notificaciones.

- ``ses_webhook``: endpoint que SNS llama con eventos SES (bounce/complaint/delivery).
- ``MailTestView``: utilidad dev-only para probar el envío desde el showcase
  de componentes (gated por DEBUG + staff).

**Producción**: validar la firma del mensaje SNS con el cert público
(``SigningCertURL``) antes de procesar. Sin validación cualquiera puede
mandarte ``Bounce`` falsos y meter usuarios reales a la lista de supresión.
Ver TODO marcado abajo.
"""

import json
import urllib.request

from django.conf import settings
from django.http import HttpResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from rest_framework import serializers, status
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from notifications.services.email_events import handle_sns_message


@csrf_exempt
@require_POST
def ses_webhook(request):
    """``POST /api/v1/email-events/`` — endpoint para SNS."""
    try:
        envelope = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponseBadRequest("invalid json")

    msg_type = envelope.get("Type")

    # Al suscribir el endpoint al tópico SNS, AWS manda este evento una sola
    # vez. Hacemos GET al SubscribeURL para confirmar — sin esto la suscripción
    # queda en estado "PendingConfirmation" y nunca recibimos eventos reales.
    if msg_type == "SubscriptionConfirmation":
        subscribe_url = envelope.get("SubscribeURL")
        if subscribe_url:
            urllib.request.urlopen(subscribe_url, timeout=10).read()  # noqa: S310
        return HttpResponse("subscribed")

    if msg_type == "Notification":
        # TODO: validar la firma del mensaje SNS antes de procesarlo. Ver
        # https://docs.aws.amazon.com/sns/latest/dg/sns-verify-signature-of-message.html
        # Sin esto cualquiera puede mandar Bounce/Complaint falsos a este
        # endpoint y suprimir usuarios reales. Mitigación parcial: dejar el
        # path en una URL difícil de adivinar o detrás de un WAF.
        try:
            payload = json.loads(envelope["Message"])
        except (json.JSONDecodeError, KeyError):
            return HttpResponseBadRequest("invalid Message")
        handle_sns_message(payload)
        return HttpResponse("ok")

    return HttpResponse("ignored")


# ──────────────────────────────────────────────────────────────────────────────
# Mail test endpoint — DEV ONLY
# ──────────────────────────────────────────────────────────────────────────────


class MailTestSerializer(serializers.Serializer):
    to = serializers.EmailField()
    user_name = serializers.CharField(max_length=80, default="Tester")
    action_url = serializers.URLField(default="http://localhost:4200/")


class MailTestView(APIView):
    """``POST /api/v1/mail-test/`` — dispara un envío del template ``_example``.

    Diseñada para el showcase de componentes (``/components`` del frontend).
    Solo accesible cuando ``DEBUG=True`` Y el usuario es staff — en
    producción el endpoint devuelve 404. No expongas esto a prod nunca: es
    un loop trivial de spam si llega a estar abierto.
    """

    permission_classes = [IsAdminUser]

    def post(self, request):
        # Doble candado: además del IsAdminUser, exigimos DEBUG. Esto evita
        # que un staff en prod arme un loop de spam por accidente.
        if not settings.DEBUG:
            return Response(
                {"detail": "Endpoint deshabilitado en producción."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = MailTestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Import lazy: el módulo notifications.services tira de Jinja+MJML al
        # importarse, no lo queremos en el path de cada request.
        from notifications.services.email import send

        record = send(
            to=data["to"],
            template="_example",
            context={
                "user_name": data["user_name"],
                "action_url": data["action_url"],
            },
            tags={"source": "components-showcase"},
            user=request.user,
            sync=True,
        )

        return Response(
            {
                "status": record.status,
                "provider": record.provider,
                "provider_message_id": record.provider_message_id,
                "subject": record.subject,
                "sent_at": record.sent_at.isoformat() if record.sent_at else None,
                "error_message": record.error_message or None,
                # Sugerencia al cliente para que abra Mailpit y vea el resultado.
                # URL configurable: si el deployer mapea Mailpit a otro puerto
                # (multi-stack, instalaciones lado-a-lado), `MAILPIT_URL` en
                # `.env` lo controla. Default = puerto estándar 8025.
                "mailpit_url": getattr(
                    settings,
                    "MAILPIT_URL",
                    "http://localhost:8025/",
                ),
            },
            status=status.HTTP_200_OK,
        )
