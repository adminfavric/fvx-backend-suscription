"""Adapter para Amazon SES — proveedor de producción recomendado por docs/email.md.

Usa boto3 SES v2 (``sesv2``) que es la API moderna con soporte completo de
configuration sets, tags y validación de payloads.

Requiere las env vars:
- ``AWS_SES_ACCESS_KEY_ID``
- ``AWS_SES_SECRET_ACCESS_KEY``
- ``AWS_SES_REGION_NAME`` (default ``us-east-1``)
- ``AWS_SES_CONFIGURATION_SET`` (opcional pero recomendado para bounces/SNS)
"""

import boto3
from botocore.exceptions import ClientError
from django.conf import settings

from .base import EmailPayload, EmailSendError


# Errores transitorios — el caller (Celery task) puede reintentar.
_TRANSIENT_ERROR_CODES = {
    "Throttling",
    "ServiceUnavailable",
    "RequestTimeout",
    "InternalFailure",
}


class SESAdapter:
    """Adapter SES v2 vía boto3."""

    def __init__(self) -> None:
        self.client = boto3.client(
            "sesv2",
            region_name=settings.AWS_SES_REGION_NAME,
            aws_access_key_id=settings.AWS_SES_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SES_SECRET_ACCESS_KEY,
        )

    def send(self, payload: EmailPayload) -> str:
        from_email = payload.from_email or settings.DEFAULT_FROM_EMAIL

        body_content: dict = {
            "Html": {"Data": payload.html, "Charset": "UTF-8"},
        }
        if payload.text:
            body_content["Text"] = {"Data": payload.text, "Charset": "UTF-8"}

        request: dict = {
            "FromEmailAddress": from_email,
            "Destination": {"ToAddresses": [payload.to]},
            "Content": {
                "Simple": {
                    "Subject": {"Data": payload.subject, "Charset": "UTF-8"},
                    "Body": body_content,
                },
            },
        }
        if payload.reply_to:
            request["ReplyToAddresses"] = payload.reply_to

        config_set = payload.configuration_set or settings.AWS_SES_CONFIGURATION_SET
        if config_set:
            request["ConfigurationSetName"] = config_set
        if payload.tags:
            # Tags se mandan como EmailTags (key/value, strings).
            request["EmailTags"] = [{"Name": k, "Value": str(v)} for k, v in payload.tags.items()]

        try:
            response = self.client.send_email(**request)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            raise EmailSendError(
                f"SES error: {code} — {e}",
                is_transient=code in _TRANSIENT_ERROR_CODES,
            ) from e
        except Exception as e:  # noqa: BLE001
            # Errores de red, DNS, etc. — generalmente transientes.
            raise EmailSendError(str(e), is_transient=True) from e

        return response["MessageId"]
