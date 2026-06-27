"""
Login sin contraseña para miembros (suscriptores) del sitio público.

Flujo:
1. ``request_code(email)`` genera un código de 6 dígitos, lo guarda en caché
   (TTL corto) y lo envía por email.
2. ``verify_code(email, code)`` valida el código y, si es correcto, devuelve un
   token firmado (``issue_token``) que el frontend guarda y envía como Bearer.
3. ``email_from_token(token)`` valida el token en cada request a endpoints de
   miembro y devuelve el email (la identidad del miembro).

No se crean usuarios Django: la identidad del miembro es su email verificado, y
el acceso al contenido se determina por sus suscripciones activas en Flow/local.
"""

from __future__ import annotations

import secrets
from email.utils import formataddr, parseaddr

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone

CODE_TTL_SECONDS = 600          # 10 minutos
TOKEN_MAX_AGE_SECONDS = 60 * 60 * 24 * 30  # 30 días
_SALT = "member-auth"

# Marca (Experiencias Lita Donoso · Alkymia Solar)
_BRAND = "Experiencias Lita Donoso"
_SUBBRAND = "Alkymia Solar"
_VIOLET = "#2e1a52"
_GOLD = "#d9a441"
_CREAM = "#faf6ef"


def _code_key(email: str) -> str:
    return f"membercode:{email.strip().lower()}"


def _session_key(email: str) -> str:
    return f"membersession:{email.strip().lower()}"


def _from_email() -> str:
    """Remitente con nombre de marca (ej. 'Experiencias Lita Donoso <addr>').
    Toma la dirección de ``DEFAULT_FROM_EMAIL`` y le antepone el nombre visible."""
    raw = getattr(settings, "DEFAULT_FROM_EMAIL", "") or ""
    addr = parseaddr(raw)[1] or raw
    return formataddr((_BRAND, addr)) if addr else raw


def _code_email_html(code: str) -> str:
    """HTML email-safe (tablas + estilos inline, sin gradientes) para el código."""
    year = timezone.now().year
    return f"""\
<div style="background:{_CREAM};padding:32px 12px;font-family:Arial,Helvetica,sans-serif;">
  <table align="center" width="480" cellpadding="0" cellspacing="0" role="presentation"
         style="max-width:480px;margin:0 auto;background:#ffffff;border-radius:16px;overflow:hidden;border:1px solid #eadfce;">
    <tr>
      <td bgcolor="{_VIOLET}" style="background:{_VIOLET};padding:28px 32px;text-align:center;">
        <div style="color:{_GOLD};font-size:11px;letter-spacing:3px;text-transform:uppercase;">{_BRAND}</div>
        <div style="color:#ffffff;font-size:22px;font-weight:bold;margin-top:6px;">{_SUBBRAND}</div>
      </td>
    </tr>
    <tr>
      <td style="padding:34px 32px;text-align:center;">
        <h1 style="font-size:20px;margin:0 0 8px;color:{_VIOLET};">Tu código de acceso</h1>
        <p style="color:#6b6478;margin:0 0 24px;font-size:15px;line-height:1.5;">
          Úsalo para entrar a tu contenido de miembro.
        </p>
        <div style="display:inline-block;background:{_CREAM};border:1px dashed {_GOLD};border-radius:12px;
                    padding:16px 26px;font-size:32px;font-weight:bold;letter-spacing:10px;color:{_VIOLET};">
          {code}
        </div>
        <p style="color:#9a93a8;margin:24px 0 0;font-size:13px;line-height:1.5;">
          Vence en 10 minutos. Si no lo solicitaste, ignora este correo.
        </p>
      </td>
    </tr>
    <tr>
      <td bgcolor="#f4f0f8" style="background:#f4f0f8;padding:18px 32px;text-align:center;color:#9a93a8;font-size:12px;">
        © {year} {_BRAND} · {_SUBBRAND}
      </td>
    </tr>
  </table>
</div>"""


def request_code(email: str) -> None:
    """Genera y envía por email un código de acceso de 6 dígitos (texto + HTML)."""
    code = f"{secrets.randbelow(1_000_000):06d}"
    cache.set(_code_key(email), code, CODE_TTL_SECONDS)
    text = (
        f"Tu código de acceso es: {code}\n\n"
        f"Vence en 10 minutos. Si no lo solicitaste, ignora este correo.\n\n"
        f"{_BRAND} · {_SUBBRAND}"
    )
    msg = EmailMultiAlternatives(
        subject=f"Tu código de acceso · {_SUBBRAND}",
        body=text,
        from_email=_from_email(),
        to=[email.strip()],
    )
    msg.attach_alternative(_code_email_html(code), "text/html")
    msg.send(fail_silently=False)


def verify_code(email: str, code: str) -> bool:
    """True si el código coincide; lo invalida tras un intento exitoso."""
    key = _code_key(email)
    expected = cache.get(key)
    if expected and secrets.compare_digest(str(expected), str(code).strip()):
        cache.delete(key)
        return True
    return False


def issue_token(email: str) -> str:
    """
    Emite un token de sesión. SESIÓN ÚNICA: cada login genera un ``sid`` nuevo y
    lo guarda como la única sesión válida del correo, invalidando los tokens
    anteriores (otra pestaña/dispositivo con el mismo correo queda fuera). Así
    compartir el código se vuelve impráctico: el último que entra expulsa al resto.
    """
    email = email.strip().lower()
    sid = secrets.token_hex(16)
    cache.set(_session_key(email), sid, TOKEN_MAX_AGE_SECONDS)
    return signing.dumps({"email": email, "sid": sid}, salt=_SALT)


def email_from_token(token: str) -> str | None:
    # Solo es válido el último login: si el ``sid`` no coincide con la sesión
    # vigente del correo, el token quedó invalidado por un login posterior.
    return identity_from_token(token)[0]


def identity_from_token(token: str) -> tuple[str | None, str | None]:
    """Devuelve ``(email, sid)`` del token si es la sesión vigente del correo;
    si no, ``(None, None)``. El ``sid`` identifica el login concreto (dispositivo)
    y se usa para el candado de entrada única en vivo a Zoom."""
    try:
        data = signing.loads(token, salt=_SALT, max_age=TOKEN_MAX_AGE_SECONDS)
    except signing.BadSignature:
        return None, None
    email = data.get("email")
    sid = data.get("sid")
    if not email or not sid or cache.get(_session_key(email)) != sid:
        return None, None
    return email, sid


def logout(email: str) -> None:
    """Invalida la sesión activa del correo (cierra sesión en todos lados)."""
    cache.delete(_session_key(email))
