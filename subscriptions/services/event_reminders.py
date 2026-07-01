"""
Aviso "tu sesión en vivo empieza pronto": ~30 min antes de cada sesión Zoom se
envía un correo a los miembros con acceso a esa sesión (plan activo donde el
contenido está programado hoy).

Una tarea Celery (``subscriptions.tasks.send_live_event_reminders``) corre cada
pocos minutos y busca las sesiones cuyo ``live_start`` cae dentro de la ventana de
aviso (por defecto 30 min). Dedupe: una clave en caché por (contenido, live_start)
evita reenviar a todo el mundo si la tarea corre varias veces dentro de la ventana.

Los destinatarios se toman del espejo local de suscripciones activas (igual que
los recordatorios de vencimiento), sin consultar la pasarela en cada envío.
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.core.mail import EmailMultiAlternatives
from django.db.models import Q
from django.utils import timezone

from ..models import CheckoutSession, ContentItem, ContentSchedule
from .member_auth import _BRAND, _SUBBRAND, _CREAM, _GOLD, _VIOLET, _from_email

# Minutos antes del inicio en que se avisa.
LEAD_MINUTES = getattr(settings, "LIVE_EVENT_REMINDER_MINUTES", 30)


def _content_url() -> str:
    base = getattr(settings, "FRONTEND_BASE_URL", "")
    return f"{base}/mi-contenido" if base else "/mi-contenido"


def _recipients(plan_ids: list[int]) -> set[str]:
    """Correos con suscripción ACTIVA en alguno de los planes dados (espejo local)."""
    out: set[str] = set()
    qs = CheckoutSession.objects.filter(
        status=CheckoutSession.Status.SUBSCRIBED, plan_id__in=plan_ids
    ).select_related("plan")
    for cs in qs:
        if not cs.email:
            continue
        # Por período: solo si el acceso sigue vigente. Recurrente: se confía en
        # el espejo local (igual criterio que los recordatorios de vencimiento).
        if cs.is_period_based and not cs.has_period_access:
            continue
        out.add(cs.email.strip())
    return out


def _event_html(title: str, hora: str, url: str) -> str:
    year = timezone.now().year
    return f"""\
<div style="background:{_CREAM};padding:32px 12px;font-family:Arial,Helvetica,sans-serif;">
  <table align="center" width="480" cellpadding="0" cellspacing="0" role="presentation"
         style="max-width:480px;margin:0 auto;background:#fff;border-radius:16px;overflow:hidden;border:1px solid #eadfce;">
    <tr><td bgcolor="{_VIOLET}" style="background:{_VIOLET};padding:26px 32px;text-align:center;">
      <div style="color:{_GOLD};font-size:11px;letter-spacing:3px;text-transform:uppercase;">{_BRAND}</div>
      <div style="color:#fff;font-size:20px;font-weight:bold;margin-top:6px;">{_SUBBRAND}</div>
    </td></tr>
    <tr><td style="padding:32px;text-align:center;">
      <h1 style="font-size:20px;margin:0 0 12px;color:{_VIOLET};">Tu sesión en vivo empieza pronto</h1>
      <p style="color:#6b6478;margin:0 0 8px;font-size:15px;line-height:1.6;">
        <strong>{title}</strong> comienza a las <strong>{hora}</strong>.</p>
      <p style="color:#6b6478;margin:0 0 22px;font-size:14px;">Entra desde tu área de miembros unos minutos antes. La sala abre 15 min antes del inicio.</p>
      <a href="{url}" style="display:inline-block;background:{_GOLD};color:{_VIOLET};text-decoration:none;font-weight:bold;
                 padding:13px 26px;border-radius:999px;font-size:15px;">Ir a mi contenido</a>
    </td></tr>
    <tr><td bgcolor="#f4f0f8" style="background:#f4f0f8;padding:18px 32px;text-align:center;color:#9a93a8;font-size:12px;">
      © {year} {_BRAND} · {_SUBBRAND}
    </td></tr>
  </table>
</div>"""


def _send_one(email: str, item: ContentItem, hora: str) -> None:
    url = _content_url()
    text = (
        f"{item.title} comienza a las {hora}.\n\n"
        f"Entra desde tu área de miembros: {url}\n"
        f"La sala abre 15 min antes del inicio.\n\n"
        f"{_BRAND} · {_SUBBRAND}"
    )
    msg = EmailMultiAlternatives(
        subject=f"Tu sesión en vivo empieza pronto · {_SUBBRAND}",
        body=text,
        from_email=_from_email(),
        to=[email],
    )
    msg.attach_alternative(_event_html(item.title, hora, url), "text/html")
    msg.send(fail_silently=False)


def send_live_event_reminders(lead_minutes: int = LEAD_MINUTES) -> int:
    """Avisa de las sesiones que empiezan en ~``lead_minutes``. Devuelve cuántos
    correos envió."""
    now = timezone.now()
    horizon = now + timedelta(minutes=lead_minutes)
    today = timezone.localdate()

    items = ContentItem.objects.filter(
        kind=ContentItem.Kind.ZOOM,
        is_published=True,
        live_start__isnull=False,
        live_start__gt=now,
        live_start__lte=horizon,
    )

    sent = 0
    for item in items:
        key = f"eventreminder:{item.id}:{item.live_start.isoformat()}"
        if cache.get(key):
            continue

        plan_ids = list(
            ContentSchedule.objects.filter(content_id=item.id, starts_at__lte=today)
            .filter(Q(ends_at__isnull=True) | Q(ends_at__gte=today))
            .values_list("plan_id", flat=True)
        )
        if not plan_ids:
            continue

        hora = timezone.localtime(item.live_start).strftime("%H:%M")
        for email in _recipients(plan_ids):
            try:
                _send_one(email, item, hora)
                sent += 1
            except Exception:
                # Un email que falle no frena al resto del lote.
                pass

        # Marca la sesión como avisada (no reenviar durante 6 h).
        cache.set(key, 1, 60 * 60 * 6)

    return sent
