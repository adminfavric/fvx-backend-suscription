"""
Subscription plans (memberships).

A ``Plan`` is the local source of truth for each membership shown on the public
site *and* the mirror of a Flow.cl subscription plan. The display fields
(``tagline``, ``description``, ``features``…) drive the membership cards; the
Flow fields (``amount``, ``interval``…) are pushed to Flow via ``/plans/create``
so customers can subscribe and be charged automatically.

A plan can exist as a *draft* (no ``amount`` yet → card shows "Valor por
confirmar", not purchasable). It is only synced to Flow once it has an amount.
See ``subscriptions/services/flow.py`` for the API client and
``subscriptions/admin.py`` for the sync-on-save behaviour.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from api.models.base import BaseModelGeneric, TimeStampedModel


class PlanInterval(models.IntegerChoices):
    """Flow ``interval`` codes (frequency of the recurring charge)."""

    DAILY = 1, _("Daily")
    WEEKLY = 2, _("Weekly")
    MONTHLY = 3, _("Monthly")
    YEARLY = 4, _("Yearly")


class PaymentProvider(models.TextChoices):
    """Origen/pasarela que respalda una suscripción.

    - ``FLOW`` / ``PAYPAL``: cobro AUTOMÁTICO recurrente (el acceso se verifica en
      vivo contra la pasarela).
    - ``MANUAL`` / ``IMPORTED`` / ``FLOW_ONE_TIME``: acceso POR PERÍODO (sin cobro
      automático). Valen mientras ``access_until >= hoy``; se renuevan extendiendo
      esa fecha al confirmar cada pago. Ver ``PERIOD_PROVIDERS``.
    """

    FLOW = "flow", _("Flow (tarjeta, recurrente)")
    PAYPAL = "paypal", _("PayPal (recurrente)")
    MANUAL = "manual", _("Manual / transferencia")
    IMPORTED = "imported", _("Importado")
    FLOW_ONE_TIME = "flow_mensual", _("Flow mensual (pago único)")


# Proveedores cuyo acceso se rige por ``access_until`` (no por la pasarela en vivo).
PERIOD_PROVIDERS = (
    PaymentProvider.MANUAL,
    PaymentProvider.IMPORTED,
    PaymentProvider.FLOW_ONE_TIME,
)


# PayPal billing-cycle ``interval_unit`` por cada ``PlanInterval`` de Flow.
PAYPAL_INTERVAL_UNIT = {
    PlanInterval.DAILY: "DAY",
    PlanInterval.WEEKLY: "WEEK",
    PlanInterval.MONTHLY: "MONTH",
    PlanInterval.YEARLY: "YEAR",
}


class Plan(BaseModelGeneric, TimeStampedModel):
    """
    A membership / subscription plan. ``name``, ``slug``, ``uuid`` and
    ``is_active`` come from ``BaseModelGeneric``. Not uppercased: the display
    copy is shown verbatim on the public site.
    """

    uuid_prefix = "PLN"

    # ── Flow plan identity ────────────────────────────────────────────────
    flow_plan_id = models.CharField(
        _("Flow plan id"),
        max_length=120,
        unique=True,
        blank=True,
        help_text=_(
            "Stable identifier sent to Flow as planId (no spaces). "
            "Auto-derived from the slug on first save; do not change once synced."
        ),
    )

    # ── Pricing / billing (sent to Flow) ──────────────────────────────────
    amount = models.PositiveIntegerField(
        _("amount"),
        null=True,
        blank=True,
        help_text=_("Charge per period (CLP, whole pesos). Empty = draft / 'Valor por confirmar'."),
    )
    currency = models.CharField(_("currency"), max_length=3, default="CLP")
    interval = models.IntegerField(
        _("interval"),
        choices=PlanInterval.choices,
        default=PlanInterval.MONTHLY,
        help_text=_("Billing frequency."),
    )
    interval_count = models.PositiveIntegerField(
        _("interval count"),
        default=1,
        validators=[MinValueValidator(1)],
        help_text=_("Interval multiplier (e.g. interval=weekly + count=2 = fortnightly)."),
    )
    trial_period_days = models.PositiveIntegerField(_("trial period (days)"), default=0)
    days_until_due = models.PositiveIntegerField(_("days until due"), default=3)
    periods_number = models.PositiveIntegerField(
        _("number of periods"),
        null=True,
        blank=True,
        help_text=_("Total periods the plan lasts. Empty = open-ended."),
    )
    charges_retries_number = models.PositiveIntegerField(_("charge retries"), default=3)

    # ── Membership presentation (public site) ─────────────────────────────
    tagline = models.CharField(
        _("tagline"),
        max_length=255,
        blank=True,
        help_text=_("Short subtitle, e.g. 'Sesión mensual · curso anual'."),
    )
    description = models.TextField(_("description"), blank=True)
    cadence = models.CharField(
        _("cadence"),
        max_length=120,
        blank=True,
        help_text=_("Human-readable cadence chip, e.g. 'Sesión mensual (curso anual)'."),
    )
    recorded = models.BooleanField(
        _("recorded"),
        default=False,
        help_text=_("Whether sessions are recorded (vs live-only)."),
    )
    features = models.JSONField(
        _("features"),
        default=list,
        blank=True,
        help_text=_("List of benefit strings shown with a check mark."),
    )
    icon = models.CharField(
        _("icon"),
        max_length=60,
        blank=True,
        help_text=_("Material icon name, e.g. 'auto_awesome'."),
    )
    image_url = models.URLField(
        _("image URL"),
        max_length=500,
        blank=True,
        help_text=_("Imagen opcional para la card (enriquecimiento local, no se envía a Flow)."),
    )
    featured = models.BooleanField(_("featured"), default=False, help_text=_("Highlight as 'Destacada'."))
    is_public = models.BooleanField(
        _("public"),
        default=True,
        help_text=_("Show on the public memberships page."),
    )
    order = models.PositiveIntegerField(_("display order"), default=0)

    # ── Flow sync state (read-only, managed by the sync) ──────────────────
    flow_synced_at = models.DateTimeField(_("last synced to Flow"), null=True, blank=True)
    flow_status = models.IntegerField(
        _("Flow status"),
        null=True,
        blank=True,
        help_text=_("Status returned by Flow: 1 active, 0 deleted."),
    )
    last_sync_error = models.TextField(_("last sync error"), blank=True)

    # ── PayPal (alternativa internacional en USD) ─────────────────────────
    paypal_enabled = models.BooleanField(
        _("PayPal enabled"),
        default=True,
        help_text=_("Ofrecer PayPal (USD) como alternativa internacional en este plan."),
    )
    paypal_amount = models.DecimalField(
        _("PayPal amount (USD)"),
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_(
            "Precio en USD a cobrar por PayPal. Vacío = se convierte automáticamente "
            "desde el precio CLP usando PAYPAL_CLP_PER_USD."
        ),
    )
    paypal_currency = models.CharField(_("PayPal currency"), max_length=3, default="USD")
    paypal_product_id = models.CharField(
        _("PayPal product id"), max_length=120, blank=True,
        help_text=_("Producto de catálogo en PayPal (creado en el primer sync)."),
    )
    paypal_plan_id = models.CharField(
        _("PayPal plan id"), max_length=120, blank=True,
        help_text=_("Billing plan en PayPal (P-…). Creado en el primer sync."),
    )
    paypal_synced_at = models.DateTimeField(_("last synced to PayPal"), null=True, blank=True)
    paypal_status = models.CharField(
        _("PayPal status"), max_length=20, blank=True,
        help_text=_("Estado del billing plan en PayPal: ACTIVE / INACTIVE."),
    )
    paypal_last_sync_error = models.TextField(_("PayPal last sync error"), blank=True)

    class Meta:
        verbose_name = _("plan")
        verbose_name_plural = _("plans")
        ordering = ["order", "name"]

    def __str__(self) -> str:
        return self.name

    @property
    def is_synced(self) -> bool:
        return self.flow_synced_at is not None

    @property
    def is_purchasable(self) -> bool:
        """Has a price and is live in Flow."""
        return bool(self.amount) and self.is_synced and self.is_active

    @property
    def paypal_price_usd(self) -> Decimal | None:
        """
        Precio efectivo en USD para PayPal: el override ``paypal_amount`` si está
        definido; si no, el precio CLP convertido con ``PAYPAL_CLP_PER_USD``.
        ``None`` si el plan no tiene precio CLP (draft).
        """
        if self.paypal_amount is not None:
            return self.paypal_amount
        if not self.amount:
            return None
        rate = getattr(settings, "PAYPAL_CLP_PER_USD", 950) or 950
        return (Decimal(self.amount) / Decimal(rate)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    @property
    def is_paypal_purchasable(self) -> bool:
        """Ofrecible por PayPal: habilitado, sincronizado y con precio USD."""
        return (
            self.paypal_enabled
            and bool(self.paypal_plan_id)
            and self.is_active
            and self.paypal_price_usd is not None
        )

    def save(self, *args, **kwargs):
        # BaseModelGeneric.save() assigns the slug from name on first save.
        super().save(*args, **kwargs)
        if not self.flow_plan_id and self.slug:
            # Derive a stable Flow planId once; persist without re-running checks.
            Plan.objects.filter(pk=self.pk).update(flow_plan_id=slugify(self.slug))
            self.flow_plan_id = slugify(self.slug)


class CheckoutSession(TimeStampedModel):
    """
    Rastrea un intento de suscripción pública a través del redirect de la pasarela.
    ``provider`` distingue Flow (registro de tarjeta → ``subscription/create``) de
    PayPal (aprobación de la suscripción → ``billing/subscriptions``). Los campos
    ``flow_*`` solo aplican a Flow; en PayPal quedan vacíos y el id de la
    suscripción de PayPal (``I-…``) se guarda igualmente en ``subscription_id``.
    """

    class Status(models.TextChoices):
        PENDING_CARD = "pending_card", _("Pending card")
        SUBSCRIBED = "subscribed", _("Subscribed")
        FAILED = "failed", _("Failed")

    provider = models.CharField(
        _("provider"),
        max_length=20,
        choices=PaymentProvider.choices,
        default=PaymentProvider.FLOW,
        db_index=True,
        help_text=_("Pasarela que respalda esta suscripción (Flow o PayPal)."),
    )
    plan = models.ForeignKey("Plan", on_delete=models.PROTECT, related_name="checkout_sessions")
    name = models.CharField(_("name"), max_length=255)
    email = models.EmailField(_("email"))
    # Solo Flow: cliente y token de registro de tarjeta.
    flow_customer_id = models.CharField(_("Flow customer id"), max_length=120, blank=True)
    register_token = models.CharField(
        _("Flow register token"), max_length=120, unique=True, null=True, blank=True
    )
    status = models.CharField(
        _("status"), max_length=20, choices=Status.choices, default=Status.PENDING_CARD
    )
    # Id de la suscripción en la pasarela (Flow ``subscriptionId`` o PayPal ``I-…``).
    subscription_id = models.CharField(_("subscription id"), max_length=120, blank=True)
    error = models.TextField(_("error"), blank=True)

    # ── Acceso por período (manual / importado / pago único) ──────────────
    # Para proveedores sin cobro automático, el acceso vale mientras
    # ``access_until >= hoy``. Vacío = sin fecha (no da acceso por sí solo).
    access_until = models.DateField(
        _("access until"), null=True, blank=True,
        help_text=_("Acceso válido hasta esta fecha (membresías por período: manual/transferencia/importado)."),
    )
    origin_note = models.CharField(
        _("origin / note"), max_length=255, blank=True,
        help_text=_("De dónde viene el alta o referencia del pago (transferencia, comprobante, plataforma origen)."),
    )
    # ── Link de pago de Flow (cobro por link, pago único que habilita N meses) ──
    period_months = models.PositiveIntegerField(
        _("period months"), default=1,
        help_text=_("Meses de acceso que habilita el pago del link (se suman a access_until al confirmar)."),
    )
    payment_url = models.CharField(
        _("payment URL"), max_length=600, blank=True,
        help_text=_("Link de pago de Flow generado para enviar al cliente."),
    )

    class Meta:
        verbose_name = _("checkout session")
        verbose_name_plural = _("checkout sessions")
        ordering = ["-created"]

    def __str__(self) -> str:
        return f"[{self.provider}] {self.email} → {self.plan_id} ({self.status})"

    @property
    def is_period_based(self) -> bool:
        """True si el acceso se rige por ``access_until`` (no por la pasarela)."""
        return self.provider in PERIOD_PROVIDERS

    @property
    def has_period_access(self) -> bool:
        """True si es por período y la fecha de acceso sigue vigente hoy."""
        return bool(self.access_until and self.access_until >= timezone.localdate())


class ContentItem(TimeStampedModel):
    """
    Pieza de contenido de la BIBLIOTECA (video/audio/PDF/imagen/texto/Zoom/enlace).
    Es **independiente del plan**: se asigna a uno o varios planes mediante
    ``ContentSchedule`` (la "Programación"). El archivo se sube vía
    ``/api/v1/uploads/`` (``file_url``); los links externos (YouTube/Zoom) van en
    ``external_url``.
    """

    class Kind(models.TextChoices):
        VIDEO = "video", _("Video")
        AUDIO = "audio", _("Audio")
        PDF = "pdf", _("PDF / documento")
        TEXT = "text", _("Texto")
        IMAGE = "image", _("Imagen")
        ZOOM = "zoom", _("Sesión Zoom (en vivo)")
        LINK = "link", _("Enlace")

    title = models.CharField(_("title"), max_length=255)
    kind = models.CharField(_("kind"), max_length=10, choices=Kind.choices, default=Kind.VIDEO)
    text = models.TextField(_("text / description"), blank=True)
    file_url = models.URLField(_("file URL"), max_length=600, blank=True, help_text=_("Archivo subido (video/audio/PDF/imagen)."))
    external_url = models.URLField(_("external URL"), max_length=600, blank=True, help_text=_("Link externo (YouTube/Vimeo/Zoom)."))
    image_url = models.URLField(_("cover image URL"), max_length=600, blank=True, help_text=_("Portada para la tarjeta de la biblioteca."))
    order = models.PositiveIntegerField(_("display order"), default=0)
    is_published = models.BooleanField(_("published"), default=True, help_text=_("Si está desactivado, no se muestra a los miembros."))

    # ── Sesión en vivo (Zoom) — solo para kind == ZOOM ────────────────────
    # El embed se gestiona con el Meeting SDK de Zoom: el número de la reunión y
    # el passcode viven SOLO en el servidor y NUNCA se envían al miembro como un
    # link. El backend entrega una firma de vida corta (ver services/zoom.py)
    # únicamente si el miembro tiene el plan activo y estamos dentro de la franja
    # horaria. Así no hay un enlace reenviable y el acceso lo decide el servidor.
    zoom_meeting_number = models.CharField(
        _("Zoom meeting number"), max_length=64, blank=True,
        help_text=_("ID numérico de la reunión Zoom (Meeting ID, sin espacios). Solo tipo 'zoom'."),
    )
    zoom_passcode = models.CharField(
        _("Zoom passcode"), max_length=64, blank=True,
        help_text=_("Clave de la reunión. Se guarda solo en el servidor; el miembro nunca ve el link."),
    )
    live_start = models.DateTimeField(
        _("live start"), null=True, blank=True,
        help_text=_("Inicio de la sesión en vivo. El acceso se abre unos minutos antes."),
    )
    live_end = models.DateTimeField(
        _("live end"), null=True, blank=True,
        help_text=_("Fin de la sesión. Vacío = se usa una duración por defecto desde el inicio."),
    )

    class Meta:
        verbose_name = _("content item")
        verbose_name_plural = _("content items")
        ordering = ["order", "-created"]

    def __str__(self) -> str:
        return f"{self.title} ({self.get_kind_display()})"

    # ── Franja de acceso a la sala en vivo ────────────────────────────────
    @property
    def live_opens_at(self):
        """Momento en que se habilita el acceso (unos minutos antes del inicio).
        ``None`` si la sesión no tiene hora de inicio (acceso siempre abierto)."""
        if not self.live_start:
            return None
        early = getattr(settings, "ZOOM_LIVE_OPEN_BEFORE_MIN", 15)
        return self.live_start - timedelta(minutes=early)

    @property
    def live_closes_at(self):
        """Momento en que se cierra el acceso. Usa ``live_end`` o, si está vacío,
        ``live_start`` + duración por defecto. ``None`` si no hay hora de inicio."""
        if self.live_end:
            return self.live_end
        if not self.live_start:
            return None
        dur = getattr(settings, "ZOOM_DEFAULT_DURATION_MIN", 240)
        return self.live_start + timedelta(minutes=dur)

    def is_live_open(self, now=None) -> bool:
        """True si AHORA el miembro puede entrar a la sala (dentro de la franja).
        Sin ``live_start`` se considera siempre abierta (mientras esté programada)."""
        now = now or timezone.now()
        opens, closes = self.live_opens_at, self.live_closes_at
        if opens and now < opens:
            return False
        if closes and now > closes:
            return False
        return True


class ContentSchedule(TimeStampedModel):
    """
    **Programación** = el hub que vincula una pieza de ``ContentItem`` con un
    ``Plan`` durante un rango de fechas. Un mismo contenido puede estar en varios
    planes (varias filas). ``ends_at`` vacío = "sin fin" (hasta que se elimine).
    El miembro ve el contenido cuya programación está vigente hoy.
    """

    content = models.ForeignKey("ContentItem", on_delete=models.CASCADE, related_name="schedules")
    plan = models.ForeignKey("Plan", on_delete=models.CASCADE, related_name="content_schedules")
    starts_at = models.DateField(_("starts at"), default=timezone.localdate, help_text=_("Desde cuándo el contenido está disponible en este plan."))
    ends_at = models.DateField(_("ends at"), null=True, blank=True, help_text=_("Hasta cuándo. Vacío = sin fin."))

    class Meta:
        verbose_name = _("content schedule")
        verbose_name_plural = _("content schedules")
        ordering = ["plan", "-starts_at"]
        unique_together = [("content", "plan")]

    def __str__(self) -> str:
        return f"{self.content_id} → {self.plan_id}"


class CompMembership(TimeStampedModel):
    """
    Acceso de **cortesía / staff**: un correo que puede entrar al área de miembros
    y ver el contenido de las membresías **sin** una suscripción real.

    Vive aparte de ``CheckoutSession``: NO cuenta como suscripción, no aparece en
    ``/admin/subscriptions`` ni en las métricas del dashboard, y no se cobra. Se
    gestiona desde el admin de Django. Útil para el equipo, invitados o pruebas.
    """

    email = models.EmailField(_("email"), unique=True)
    full_name = models.CharField(_("full name"), max_length=255, blank=True)
    all_plans = models.BooleanField(
        _("all plans"), default=True,
        help_text=_("Acceso a TODAS las membresías activas. Desmárcalo para limitar a planes concretos."),
    )
    plans = models.ManyToManyField(
        "Plan", blank=True, related_name="comp_members",
        help_text=_("Si 'all plans' está desmarcado, solo estas membresías."),
    )
    is_active = models.BooleanField(_("active"), default=True)
    note = models.CharField(_("note"), max_length=255, blank=True)

    class Meta:
        verbose_name = _("complimentary access")
        verbose_name_plural = _("complimentary access")
        ordering = ["email"]

    def __str__(self) -> str:
        return f"{self.email} (cortesía)"

    def plan_ids(self) -> list[int]:
        """IDs de planes a los que da acceso (vacío si está inactivo)."""
        if not self.is_active:
            return []
        if self.all_plans:
            return list(Plan.objects.filter(is_active=True).values_list("id", flat=True))
        return list(self.plans.values_list("id", flat=True))


class Event(BaseModelGeneric, TimeStampedModel):
    """
    Evento especial de **compra única** (estilo Tiendup): talleres, encuentros.
    A diferencia de ``Plan`` (suscripción recurrente), el pago es one-time vía
    Flow ``payment/create``. ``name``/``slug``/``uuid``/``is_active`` vienen de
    ``BaseModelGeneric``.
    """

    uuid_prefix = "EVT"

    subtitle = models.CharField(_("subtitle"), max_length=255, blank=True)
    description = models.TextField(_("description"), blank=True)
    date = models.DateTimeField(_("date"), null=True, blank=True, help_text=_("Fecha del evento. Vacío = próximamente."))
    price = models.PositiveIntegerField(
        _("price (CLP)"), null=True, blank=True,
        help_text=_("Precio de compra única en CLP. Vacío = 'Valor por confirmar' (no comprable)."),
    )
    currency = models.CharField(_("currency"), max_length=3, default="CLP")
    icon = models.CharField(_("icon"), max_length=60, blank=True, help_text=_("Material icon, p. ej. 'wb_sunny'."))
    image_url = models.URLField(_("image URL"), max_length=600, blank=True)
    is_public = models.BooleanField(_("public"), default=True)
    order = models.PositiveIntegerField(_("display order"), default=0)

    class Meta:
        verbose_name = _("event")
        verbose_name_plural = _("events")
        ordering = ["order", "date", "name"]

    def __str__(self) -> str:
        return self.name

    @property
    def is_purchasable(self) -> bool:
        return bool(self.price) and self.is_active


class EventOrder(TimeStampedModel):
    """Compra única de un ``Event`` vía Flow (rastrea el pago one-time)."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Pendiente")
        PAID = "paid", _("Pagada")
        FAILED = "failed", _("Rechazada")

    event = models.ForeignKey("Event", on_delete=models.PROTECT, related_name="orders")
    name = models.CharField(_("name"), max_length=255)
    email = models.EmailField(_("email"))
    commerce_order = models.CharField(_("commerce order"), max_length=80, unique=True)
    amount = models.PositiveIntegerField(_("amount"))
    flow_token = models.CharField(_("Flow token"), max_length=120, blank=True)
    flow_order = models.CharField(_("Flow order"), max_length=60, blank=True)
    status = models.CharField(_("status"), max_length=10, choices=Status.choices, default=Status.PENDING)

    class Meta:
        verbose_name = _("event order")
        verbose_name_plural = _("event orders")
        ordering = ["-created"]

    def __str__(self) -> str:
        return f"{self.email} → {self.event_id} ({self.status})"


def default_launch_tiers() -> list:
    """Valor inicial de ``LaunchSchedule.tiers`` (el calendario que hoy está
    quemado en el componente). El admin lo edita; esto solo siembra el singleton."""
    return [
        {
            "name": "BÁSICO",
            "badge": "",
            "featured": False,
            "items": [
                {"title": "Taller Alkymia Solar para Principiantes", "when": "Domingo 28 · 03:00 PM"},
            ],
        },
        {
            "name": "PREMIUM",
            "badge": "",
            "featured": False,
            "items": [
                {"title": "Taller de Sanación del Árbol Genealógico", "when": "Domingo 28 · 10:00 AM"},
                {"title": "Taller Alkymia Solar para Principiantes", "when": "Domingo 28 · 03:00 PM"},
                {"title": "Podcast + Conversatorio (tema sorpresa)", "when": "Lunes 29 · 10:00 AM"},
            ],
        },
        {
            "name": "ORO",
            "badge": "Acceso completo",
            "featured": True,
            "items": [
                {"title": "Taller de Sanación del Árbol Genealógico", "when": "Domingo 28 · 10:00 AM"},
                {"title": "Taller Alkymia Solar para Principiantes", "when": "Domingo 28 · 03:00 PM"},
                {"title": "Podcast + Conversatorio (tema sorpresa)", "when": "Lunes 29 · 10:00 AM"},
                {"title": "Escuelas", "when": "Fechas por definir"},
            ],
        },
    ]


class LaunchSchedule(TimeStampedModel):
    """
    Bloque de campaña editable que se muestra ANTES de las membresías: mensaje de
    bienvenida + "Próximas actividades" (calendario de iniciación por nivel).

    Es un **singleton** (solo existe la fila ``pk=1``, igual que ``UiSettings``):
    el admin edita aquí lo que quiere que se vea en el sitio, sin tocar código.
    El frontend lo consume por ``GET /public/launch-schedule/`` y, si ``enabled``
    es falso, no muestra el bloque (útil cuando la plataforma ya esté poblada).
    Las actividades por nivel viven en ``tiers`` (JSON: lista de columnas, cada
    una con ``name``/``badge``/``featured``/``items:[{title, when}]``).
    """

    enabled = models.BooleanField(
        _("enabled"), default=True,
        help_text=_("Mostrar el bloque de bienvenida + próximas actividades en el sitio."),
    )
    intro_title = models.CharField(
        _("intro title"), max_length=255,
        default="Estamos preparando tu espacio con mucho cariño",
    )
    intro_body = models.TextField(
        _("intro body"),
        default=(
            "Este es un espacio donde podrás acceder al nutritivo contenido que estamos "
            "creando para ti: videos, libros, talleres y nuestros encuentros por Zoom "
            "dedicados especialmente a nuestra comunidad.\n\n"
            "Ya tenemos las primeras fechas confirmadas. Si aún no ves nada en tu panel "
            "de suscripción, ¡no te preocupes! Aquí abajo te compartimos el calendario "
            "de iniciación."
        ),
        help_text=_("Párrafos de bienvenida. Separa cada párrafo con una línea en blanco."),
    )
    gift_note = models.TextField(
        _("gift note"), blank=True,
        default=(
            "Y como agradecimiento por tu confianza y tu espera, quienes se hayan "
            "registrado antes del 25 de junio recibirán un regalo sorpresa. 🎁"
        ),
        help_text=_("Aviso del regalo (recuadro dorado). Vacío = no se muestra el recuadro."),
    )
    timezone_label = models.CharField(
        _("timezone label"), max_length=80, default="Horarios de Chile · GMT-3",
    )
    heading = models.CharField(
        _("schedule heading"), max_length=120, default="Próximas actividades",
    )
    tiers = models.JSONField(
        _("tiers"), default=default_launch_tiers, blank=True,
        help_text=_(
            "Columnas por nivel. Lista de objetos: "
            "{\"name\", \"badge\", \"featured\", \"items\":[{\"title\", \"when\"}]}."
        ),
    )
    signature = models.CharField(
        _("signature"), max_length=120, default="Grupo Alkymia",
    )

    class Meta:
        verbose_name = _("launch schedule")
        verbose_name_plural = _("launch schedule")

    def __str__(self) -> str:
        return "Launch schedule (próximas actividades)"

    def save(self, *args, **kwargs):
        # Singleton: siempre la misma fila.
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "LaunchSchedule":
        """Devuelve el singleton, creándolo con los valores por defecto si falta."""
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj


class Lead(TimeStampedModel):
    """
    Captura de contactos del sitio público: newsletter, formulario de contacto e
    inscripciones a eventos/maratón. Reemplaza la antigua escritura a Firebase
    Realtime DB. El payload completo se guarda en ``raw`` por si el formulario
    envía campos extra.
    """

    class Kind(models.TextChoices):
        NEWSLETTER = "newsletter", _("Newsletter")
        CONTACT = "contact", _("Contact")
        MARATON = "maraton", _("Maratón / event")

    kind = models.CharField(_("kind"), max_length=20, choices=Kind.choices, default=Kind.NEWSLETTER)
    source = models.CharField(_("source"), max_length=60, blank=True, help_text=_("Page/origin, e.g. 'home'."))
    name = models.CharField(_("name"), max_length=255, blank=True)
    email = models.EmailField(_("email"))
    phone = models.CharField(_("phone"), max_length=40, blank=True)
    country = models.CharField(_("country"), max_length=80, blank=True)
    subject = models.CharField(_("subject"), max_length=255, blank=True)
    message = models.TextField(_("message"), blank=True)
    raw = models.JSONField(_("raw payload"), default=dict, blank=True)
    # Gestión en el panel: marcar como leído / respondido (no afecta al sitio).
    is_read = models.BooleanField(_("read"), default=False)
    is_replied = models.BooleanField(_("replied"), default=False)

    class Meta:
        verbose_name = _("lead")
        verbose_name_plural = _("leads")
        ordering = ["-created"]

    def __str__(self) -> str:
        return f"[{self.kind}] {self.email}"
