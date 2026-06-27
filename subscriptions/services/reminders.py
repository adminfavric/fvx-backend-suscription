"""
Recordatorios de vencimiento de membresías POR PERÍODO (mensualidad por link,
manual, importadas). Cada día, una tarea Celery (``subscriptions.tasks``) llama a
``send_expiry_reminders()``, que busca las suscripciones activas cuyo
``access_until`` está a 3 días, 1 día o vence hoy, y envía un correo de aviso al
miembro para que renueve. Las recurrentes (Flow/PayPal) se cobran solas, así que
no entran aquí.

Dedupe: una clave en caché por (suscripción, fecha, hito) evita reenvíos si la
tarea corre más de una vez el mismo día.
"""

from __future__ import annotations

from django.conf import settings
from django.core.cache import cache
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone

from ..models import CheckoutSession, PERIOD_PROVIDERS
from .member_auth import _BRAND, _SUBBRAND, _CREAM, _GOLD, _VIOLET, _from_email

# Días antes del vencimiento en que se avisa (0 = vence hoy).
REMINDER_DAYS = (3, 1, 0)


def _renew_url(cs: CheckoutSession) -> str:
    base = getattr(settings, "FRONTEND_BASE_URL", "")
    slug = cs.plan.slug if cs.plan_id else ""
    return f"{base}/membresias/{slug}" if slug else f"{base}/acceso"


def _reminder_copy(days_left: int, plan_name: str) -> tuple[str, str]:
    """Devuelve (asunto, frase principal) según cuánto falta."""
    if days_left <= 0:
        return (
            f"Tu acceso a {plan_name} vence hoy",
            f"Tu acceso a <strong>{plan_name}</strong> vence <strong>hoy</strong>.",
        )
    unidad = "día" if days_left == 1 else "días"
    return (
        f"Tu acceso a {plan_name} vence en {days_left} {unidad}",
        f"Tu acceso a <strong>{plan_name}</strong> vence en <strong>{days_left} {unidad}</strong>.",
    )


def _reminder_html(frase: str, fecha: str, url: str) -> str:
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
      <h1 style="font-size:20px;margin:0 0 12px;color:{_VIOLET};">Tu membresía está por vencer</h1>
      <p style="color:#6b6478;margin:0 0 8px;font-size:15px;line-height:1.6;">{frase}</p>
      <p style="color:#6b6478;margin:0 0 22px;font-size:14px;">Vence el <strong>{fecha}</strong>. Renueva para no perder el acceso a tu contenido y sesiones en vivo.</p>
      <a href="{url}" style="display:inline-block;background:{_GOLD};color:{_VIOLET};text-decoration:none;font-weight:bold;
                 padding:13px 26px;border-radius:999px;font-size:15px;">Renovar mi membresía</a>
    </td></tr>
    <tr><td bgcolor="#f4f0f8" style="background:#f4f0f8;padding:18px 32px;text-align:center;color:#9a93a8;font-size:12px;">
      © {year} {_BRAND} · {_SUBBRAND}
    </td></tr>
  </table>
</div>"""


def _send_one(cs: CheckoutSession, days_left: int) -> None:
    plan_name = cs.plan.name if cs.plan_id else "tu membresía"
    fecha = cs.access_until.strftime("%d-%m-%Y") if cs.access_until else ""
    subject, frase = _reminder_copy(days_left, plan_name)
    url = _renew_url(cs)
    text = (
        f"{frase}\n\nVence el {fecha}. Renueva tu membresía aquí: {url}\n\n"
        f"{_BRAND} · {_SUBBRAND}"
    ).replace("<strong>", "").replace("</strong>", "")
    msg = EmailMultiAlternatives(
        subject=f"{subject} · {_SUBBRAND}",
        body=text,
        from_email=_from_email(),
        to=[cs.email.strip()],
    )
    msg.attach_alternative(_reminder_html(frase, fecha, url), "text/html")
    msg.send(fail_silently=False)


def send_expiry_reminders() -> int:
    """Envía los recordatorios pendientes de hoy. Devuelve cuántos envió."""
    today = timezone.localdate()
    qs = (
        CheckoutSession.objects.filter(
            status=CheckoutSession.Status.SUBSCRIBED,
            provider__in=PERIOD_PROVIDERS,
            access_until__isnull=False,
        )
        .select_related("plan")
    )
    sent = 0
    for cs in qs:
        days_left = (cs.access_until - today).days
        if days_left not in REMINDER_DAYS:
            continue
        key = f"expreminder:{cs.id}:{cs.access_until.isoformat()}:{days_left}"
        if cache.get(key):
            continue
        try:
            _send_one(cs, days_left)
            cache.set(key, 1, 60 * 60 * 24 * 10)  # no reenviar el mismo hito (10 días)
            sent += 1
        except Exception:
            # No frenar el lote por un email que falle; el próximo run reintenta.
            pass
    return sent
