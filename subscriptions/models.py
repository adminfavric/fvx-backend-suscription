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

    def save(self, *args, **kwargs):
        # BaseModelGeneric.save() assigns the slug from name on first save.
        super().save(*args, **kwargs)
        if not self.flow_plan_id and self.slug:
            # Derive a stable Flow planId once; persist without re-running checks.
            Plan.objects.filter(pk=self.pk).update(flow_plan_id=slugify(self.slug))
            self.flow_plan_id = slugify(self.slug)


class CheckoutSession(TimeStampedModel):
    """
    Tracks one public subscription attempt across the Flow card-registration
    redirect. Created on checkout start (after ``customer/register``); completed
    when Flow returns and we create the subscription.
    """

    class Status(models.TextChoices):
        PENDING_CARD = "pending_card", _("Pending card")
        SUBSCRIBED = "subscribed", _("Subscribed")
        FAILED = "failed", _("Failed")

    plan = models.ForeignKey("Plan", on_delete=models.PROTECT, related_name="checkout_sessions")
    name = models.CharField(_("name"), max_length=255)
    email = models.EmailField(_("email"))
    flow_customer_id = models.CharField(_("Flow customer id"), max_length=120)
    register_token = models.CharField(_("Flow register token"), max_length=120, unique=True)
    status = models.CharField(
        _("status"), max_length=20, choices=Status.choices, default=Status.PENDING_CARD
    )
    subscription_id = models.CharField(_("Flow subscription id"), max_length=120, blank=True)
    error = models.TextField(_("error"), blank=True)

    class Meta:
        verbose_name = _("checkout session")
        verbose_name_plural = _("checkout sessions")
        ordering = ["-created"]

    def __str__(self) -> str:
        return f"{self.email} → {self.plan_id} ({self.status})"


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

    class Meta:
        verbose_name = _("content item")
        verbose_name_plural = _("content items")
        ordering = ["order", "-created"]

    def __str__(self) -> str:
        return f"{self.title} ({self.get_kind_display()})"


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

    class Meta:
        verbose_name = _("lead")
        verbose_name_plural = _("leads")
        ordering = ["-created"]

    def __str__(self) -> str:
        return f"[{self.kind}] {self.email}"
