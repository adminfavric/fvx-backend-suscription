"""
Ingesta de RESPUESTAS por correo (bandeja del admin, vía IMAP).

Cuando una clienta responde un correo enviado desde el panel (masivo, individual
o respuesta), su mensaje llega a la casilla del admin (Gmail). Esta tarea revisa
esa casilla cada pocos minutos y guarda como ``Lead`` (kind="email") SOLO los
correos cuyos remitentes son clientes/leads conocidos — el resto de la bandeja se
ignora por completo y no se modifica (se usa BODY.PEEK: no marca leído).

Config (reusa el SMTP ya configurado):
  · EMAIL_IMAP_HOST (default "imap.gmail.com"; en Gmail requiere IMAP habilitado)
  · EMAIL_HOST_USER / EMAIL_HOST_PASSWORD (la misma contraseña de aplicación)

Dedupe por ``Message-ID`` (guardado en ``Lead.raw.message_id``). Como cursor se
cachea el último UID procesado; sin cursor se mira solo los últimos días.
"""

from __future__ import annotations

import email
import email.header
import email.utils
import imaplib
import logging
import re
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from ..models import CheckoutSession, CompMembership, Lead

logger = logging.getLogger(__name__)

_UID_CACHE_KEY = "inboundmail:lastuid"
_FIRST_RUN_DAYS = 3          # sin cursor: mirar solo los últimos N días
_MAX_BODY_CHARS = 6000       # tope del cuerpo guardado
_MAX_PER_RUN = 80            # tope de mensajes procesados por corrida


def _decode(value: str | None) -> str:
    """Decodifica un header MIME (=?utf-8?...?=) a texto plano."""
    if not value:
        return ""
    parts = []
    for chunk, enc in email.header.decode_header(value):
        if isinstance(chunk, bytes):
            parts.append(chunk.decode(enc or "utf-8", errors="replace"))
        else:
            parts.append(chunk)
    return "".join(parts).strip()


def _body_text(msg: email.message.Message) -> str:
    """Extrae el cuerpo como texto plano (text/plain; fallback: html sin tags)."""
    plain, html = "", ""
    for part in msg.walk():
        ctype = part.get_content_type()
        if part.get_content_disposition() == "attachment":
            continue
        if ctype not in ("text/plain", "text/html"):
            continue
        try:
            payload = part.get_payload(decode=True) or b""
            text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        except Exception:
            continue
        if ctype == "text/plain" and not plain:
            plain = text
        elif ctype == "text/html" and not html:
            html = text
    text = plain or re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style).*?</\1>", "", html))
    return _strip_quoted(text)[:_MAX_BODY_CHARS].strip()


def _strip_quoted(text: str) -> str:
    """Recorta la cola citada de la respuesta ("El ... escribió:" / líneas '>')."""
    out = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(">"):
            break
        if re.match(r"^(El|On) .{4,80}(escribió|wrote):\s*$", s):
            break
        out.append(line.rstrip())
    # sin líneas vacías repetidas al final
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def _known_sender(sender: str) -> bool:
    """¿El remitente es un cliente/lead conocido? (suscripciones, cortesías o
    mensajes previos del sitio). El resto de la bandeja no se ingesta."""
    return (
        CheckoutSession.objects.filter(email__iexact=sender).exists()
        or Lead.objects.filter(email__iexact=sender).exclude(kind=Lead.Kind.EMAIL).exists()
        or CompMembership.objects.filter(email__iexact=sender).exists()
    )


def fetch_inbound_replies() -> int:
    """Revisa la casilla y guarda las respuestas nuevas. Devuelve cuántas guardó."""
    host = getattr(settings, "EMAIL_IMAP_HOST", "") or "imap.gmail.com"
    user = getattr(settings, "EMAIL_HOST_USER", "")
    password = getattr(settings, "EMAIL_HOST_PASSWORD", "")
    if not (user and password) or getattr(settings, "EMAIL_HOST", "") in ("mailpit", "localhost", ""):
        return 0  # sin correo real configurado: nada que hacer

    own = user.strip().lower()
    saved = 0
    try:
        imap = imaplib.IMAP4_SSL(host, timeout=25)
        imap.login(user, password)
        imap.select("INBOX", readonly=True)

        last_uid = cache.get(_UID_CACHE_KEY)
        if last_uid:
            typ, data = imap.uid("search", None, f"UID {int(last_uid) + 1}:*")
        else:
            since = (timezone.localdate() - timedelta(days=_FIRST_RUN_DAYS)).strftime("%d-%b-%Y")
            typ, data = imap.uid("search", None, f"(SINCE {since})")
        uids = (data[0] or b"").split() if typ == "OK" else []
        # El search "UID n:*" devuelve el último aunque sea <= last_uid: filtrar.
        uids = [u for u in uids if not last_uid or int(u) > int(last_uid)]

        for uid in uids[:_MAX_PER_RUN]:
            typ, msg_data = imap.uid("fetch", uid, "(BODY.PEEK[])")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            msg = email.message_from_bytes(msg_data[0][1])

            mid = (msg.get("Message-ID") or "").strip()
            from_name, from_email = email.utils.parseaddr(msg.get("From") or "")
            sender = (from_email or "").strip().lower()
            if not sender or sender == own:
                continue
            if mid and Lead.objects.filter(kind=Lead.Kind.EMAIL, raw__message_id=mid).exists():
                continue
            if not _known_sender(sender):
                continue

            body = _body_text(msg)
            if not body:
                continue
            Lead.objects.create(
                kind=Lead.Kind.EMAIL,
                source="gmail",
                name=_decode(from_name),
                email=sender,
                subject=_decode(msg.get("Subject"))[:255],
                message=body,
                raw={
                    "message_id": mid,
                    "date": _decode(msg.get("Date")),
                    "in_reply_to": (msg.get("In-Reply-To") or "").strip(),
                },
            )
            saved += 1

        if uids:
            cache.set(_UID_CACHE_KEY, int(uids[-1]), None)
        imap.logout()
    except Exception as exc:  # red/credenciales: se reintenta en la próxima corrida
        logger.warning("inbound_mail: no se pudo revisar la casilla: %s", exc)
    return saved
