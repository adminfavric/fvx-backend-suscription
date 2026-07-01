"""
Correos masivos a miembros: envía un mensaje (asunto + HTML del editor) a todos
los suscriptores ACTIVOS de los planes elegidos (o de todos, si no se elige
ninguno). Los destinatarios salen del espejo local de suscripciones (igual
criterio que los recordatorios): por período solo si el acceso sigue vigente;
recurrentes se incluyen mientras figuren suscritos.

El HTML del editor se envuelve en la plantilla de marca para que el correo llegue
con el mismo estilo (cabecera violeta + dorado) que el resto de los envíos.
"""

from __future__ import annotations

from django.core.mail import EmailMultiAlternatives
from django.utils import timezone
from django.utils.html import strip_tags

from ..models import CheckoutSession
from .member_auth import _BRAND, _SUBBRAND, _CREAM, _GOLD, _VIOLET, _from_email


def active_member_emails(plan_ids: list[int] | None = None) -> list[str]:
    """Correos con suscripción ACTIVA. ``plan_ids`` vacío/None = todos los planes."""
    qs = CheckoutSession.objects.filter(status=CheckoutSession.Status.SUBSCRIBED)
    if plan_ids:
        qs = qs.filter(plan_id__in=plan_ids)
    out: set[str] = set()
    for cs in qs.select_related("plan"):
        if not cs.email:
            continue
        if cs.is_period_based and not cs.has_period_access:
            continue
        out.add(cs.email.strip())
    return sorted(out)


def _wrap_html(inner_html: str) -> str:
    """Envuelve el contenido del editor en la plantilla de marca."""
    year = timezone.now().year
    return f"""\
<div style="background:{_CREAM};padding:32px 12px;font-family:Arial,Helvetica,sans-serif;">
  <table align="center" width="560" cellpadding="0" cellspacing="0" role="presentation"
         style="max-width:560px;margin:0 auto;background:#fff;border-radius:16px;overflow:hidden;border:1px solid #eadfce;">
    <tr><td bgcolor="{_VIOLET}" style="background:{_VIOLET};padding:26px 32px;text-align:center;">
      <div style="color:{_GOLD};font-size:11px;letter-spacing:3px;text-transform:uppercase;">{_BRAND}</div>
      <div style="color:#fff;font-size:20px;font-weight:bold;margin-top:6px;">{_SUBBRAND}</div>
    </td></tr>
    <tr><td style="padding:32px;color:#3a3346;font-size:15px;line-height:1.7;">
      {inner_html}
    </td></tr>
    <tr><td bgcolor="#f4f0f8" style="background:#f4f0f8;padding:18px 32px;text-align:center;color:#9a93a8;font-size:12px;">
      © {year} {_BRAND} · {_SUBBRAND}
    </td></tr>
  </table>
</div>"""


def send_broadcast(subject: str, inner_html: str, recipients: list[str]) -> int:
    """Envía el mensaje a cada destinatario (uno a uno, sin exponer la lista en
    copia). Devuelve cuántos se enviaron correctamente."""
    html = _wrap_html(inner_html)
    text = strip_tags(inner_html)
    sent = 0
    for email in recipients:
        try:
            msg = EmailMultiAlternatives(
                subject=f"{subject} · {_SUBBRAND}",
                body=text,
                from_email=_from_email(),
                to=[email],
            )
            msg.attach_alternative(html, "text/html")
            msg.send(fail_silently=False)
            sent += 1
        except Exception:
            # Un email que falle no frena al resto del lote.
            pass
    return sent
