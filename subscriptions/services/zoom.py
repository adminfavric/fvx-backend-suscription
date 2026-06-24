"""
Firma para el Zoom Meeting SDK (sesiones en vivo embebidas en el sitio).

El miembro NO recibe un link de Zoom: recibe una **firma JWT de vida corta** que
solo sirve para unirse a UNA reunión concreta desde el SDK embebido en
``/sala/:id``. La firma se emite (ver ``views.MemberZoomSignatureView``)
únicamente si el miembro tiene el plan activo y estamos dentro de la franja
horaria de la sesión. Así no hay un enlace reenviable: el acceso lo decide el
servidor en el momento de entrar.

Formato de la firma: ver developer.zoom.us → Meeting SDK → "Generate the SDK JWT".
Es un JWT HS256 firmado con el SDK Secret; se construye con la librería estándar
para no añadir dependencias.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from django.conf import settings


class ZoomConfigError(RuntimeError):
    """Faltan credenciales del Meeting SDK (ZOOM_SDK_KEY / ZOOM_SDK_SECRET)."""


def _b64url(raw: bytes) -> str:
    """base64url sin padding (formato de los segmentos JWT)."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _encode_segment(data: dict) -> str:
    return _b64url(json.dumps(data, separators=(",", ":")).encode("utf-8"))


def meeting_signature(
    meeting_number: str,
    role: int = 0,
    expire_seconds: int = 60 * 60 * 2,
) -> dict:
    """
    Devuelve ``{"signature", "sdkKey"}`` para unirse a ``meeting_number``.

    ``role``: 0 = asistente, 1 = host. ``expire_seconds`` = vida de la firma
    (máx. 48 h por Zoom; usamos 2 h). Lanza ``ZoomConfigError`` si faltan las
    credenciales del Meeting SDK.
    """
    sdk_key = getattr(settings, "ZOOM_SDK_KEY", "")
    sdk_secret = getattr(settings, "ZOOM_SDK_SECRET", "")
    if not (sdk_key and sdk_secret):
        raise ZoomConfigError("ZOOM_SDK_KEY / ZOOM_SDK_SECRET no configurados.")

    iat = int(time.time()) - 30  # margen de reloj
    exp = iat + expire_seconds
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "appKey": sdk_key,
        "sdkKey": sdk_key,
        "mn": str(meeting_number),
        "role": role,
        "iat": iat,
        "exp": exp,
        "tokenExp": exp,
    }
    signing_input = f"{_encode_segment(header)}.{_encode_segment(payload)}"
    sig = hmac.new(
        sdk_secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256
    ).digest()
    return {"signature": f"{signing_input}.{_b64url(sig)}", "sdkKey": sdk_key}
