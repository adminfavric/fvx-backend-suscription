"""Django admin for subscription plans, with Flow.cl sync on save."""

from django.contrib import admin, messages
from django.utils.translation import gettext_lazy as _

from .models import (
    CheckoutSession,
    CompMembership,
    ContentItem,
    ContentSchedule,
    Event,
    EventOrder,
    LaunchSchedule,
    Lead,
    Plan,
)
from .services import (
    FlowError,
    PayPalError,
    import_plans_from_flow,
    sync_plan_to_flow,
    sync_plan_to_paypal,
)


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "flow_plan_id",
        "amount",
        "interval",
        "is_public",
        "featured",
        "is_active",
        "synced",
        "paypal",
        "modified",
    ]
    list_filter = ["is_active", "is_public", "featured", "interval", "paypal_enabled"]
    search_fields = ["name", "slug", "flow_plan_id", "paypal_plan_id", "uuid"]
    ordering = ["order", "name"]
    actions = ["action_sync_to_flow", "action_sync_to_paypal", "action_import_from_flow"]

    fieldsets = (
        (_("Membership (public site)"), {
            "fields": ("name", "tagline", "description", "cadence", "recorded",
                       "features", "icon", "image_url", "featured", "is_public", "order", "is_active"),
        }),
        (_("Pricing & billing (Flow)"), {
            "fields": ("amount", "currency", "interval", "interval_count",
                       "trial_period_days", "days_until_due", "periods_number",
                       "charges_retries_number"),
        }),
        (_("PayPal (international, USD)"), {
            "fields": ("paypal_enabled", "paypal_amount", "paypal_currency",
                       "paypal_plan_id", "paypal_product_id", "paypal_synced_at",
                       "paypal_status", "paypal_last_sync_error"),
            "description": _(
                "PayPal es la alternativa internacional (USD). Si dejas el monto USD "
                "vacío, se convierte desde el precio CLP con PAYPAL_CLP_PER_USD."
            ),
        }),
        (_("Flow sync (read-only)"), {
            "fields": ("flow_plan_id", "flow_synced_at", "flow_status",
                       "last_sync_error", "slug", "uuid", "created", "modified"),
        }),
    )
    readonly_fields = [
        "flow_plan_id", "flow_synced_at", "flow_status", "last_sync_error",
        "paypal_plan_id", "paypal_product_id", "paypal_synced_at", "paypal_status",
        "paypal_last_sync_error", "slug", "uuid", "created", "modified",
    ]

    @admin.display(description=_("Flow"), boolean=True)
    def synced(self, obj: Plan) -> bool:
        return obj.is_synced

    @admin.display(description=_("PayPal"), boolean=True)
    def paypal(self, obj: Plan) -> bool:
        return bool(obj.paypal_plan_id and obj.paypal_enabled)

    def save_model(self, request, obj: Plan, form, change):
        super().save_model(request, obj, form, change)
        # Drafts (no amount) stay local until priced.
        if not obj.amount:
            self.message_user(
                request,
                _("Saved as draft. Set an amount to publish it to Flow."),
                level=messages.INFO,
            )
            return
        try:
            sync_plan_to_flow(obj)
            self.message_user(request, _("Plan synced to Flow."), level=messages.SUCCESS)
        except FlowError as exc:
            self.message_user(
                request,
                _("Saved locally, but Flow sync failed: %s") % exc,
                level=messages.WARNING,
            )
        # PayPal solo si el plan lo habilita.
        if obj.paypal_enabled:
            try:
                sync_plan_to_paypal(obj)
                self.message_user(request, _("Plan synced to PayPal."), level=messages.SUCCESS)
            except PayPalError as exc:
                self.message_user(
                    request,
                    _("Saved locally, but PayPal sync failed: %s") % exc,
                    level=messages.WARNING,
                )

    @admin.action(description=_("Sync selected plans to Flow"))
    def action_sync_to_flow(self, request, queryset):
        ok, failed = 0, 0
        for plan in queryset:
            try:
                sync_plan_to_flow(plan)
                ok += 1
            except FlowError as exc:
                failed += 1
                self.message_user(request, f"{plan.name}: {exc}", level=messages.WARNING)
        if ok:
            self.message_user(request, _("%d plan(s) synced to Flow.") % ok, level=messages.SUCCESS)

    @admin.action(description=_("Sync selected plans to PayPal"))
    def action_sync_to_paypal(self, request, queryset):
        ok = 0
        for plan in queryset:
            try:
                sync_plan_to_paypal(plan)
                ok += 1
            except PayPalError as exc:
                self.message_user(request, f"{plan.name}: {exc}", level=messages.WARNING)
        if ok:
            self.message_user(request, _("%d plan(s) synced to PayPal.") % ok, level=messages.SUCCESS)

    @admin.action(description=_("Import plans from Flow"))
    def action_import_from_flow(self, request, queryset):
        # Imports the whole Flow catalogue (the selection is ignored).
        try:
            result = import_plans_from_flow()
        except FlowError as exc:
            self.message_user(request, _("Flow import failed: %s") % exc, level=messages.ERROR)
            return
        self.message_user(
            request,
            _("Imported %(created)d, updated %(updated)d plan(s) from Flow.") % result,
            level=messages.SUCCESS,
        )


@admin.register(CheckoutSession)
class CheckoutSessionAdmin(admin.ModelAdmin):
    """Suscripciones públicas. ``provider`` distingue Flow (CLP) de PayPal (USD).

    Permite el ALTA/EDICIÓN manual: útil cuando un pago (p. ej. PayPal) se cobró
    pero el registro automático falló y hay que dejar al cliente con acceso a mano.
    Para dar acceso: provider=PayPal, plan, email, status=Subscribed (el
    subscription_id ``I-…`` es opcional; ayuda a cancelar/verificar después)."""

    list_display = ["email", "provider", "plan", "status", "subscription_id", "created"]
    list_filter = ["provider", "status", "plan"]
    search_fields = ["email", "name", "subscription_id", "flow_customer_id", "register_token"]
    ordering = ["-created"]
    autocomplete_fields = ["plan"]
    # Solo los campos relevantes para el alta manual (los internos de Flow y el
    # link de pago quedan fuera del form). Las fechas son automáticas.
    fields = [
        "provider", "plan", "name", "email", "status", "subscription_id",
        "access_until", "period_months", "origin_note", "created", "modified",
    ]
    readonly_fields = ["created", "modified"]


@admin.register(ContentItem)
class ContentItemAdmin(admin.ModelAdmin):
    list_display = ["title", "kind", "is_published", "live_start", "order", "created"]
    list_filter = ["kind", "is_published"]
    search_fields = ["title", "text"]
    ordering = ["order"]
    fieldsets = (
        (None, {"fields": ("title", "kind", "text", "order", "is_published")}),
        (_("Archivo / enlace"), {"fields": ("file_url", "external_url", "image_url")}),
        (_("Sesión en vivo (Zoom)"), {
            "fields": ("zoom_meeting_number", "zoom_passcode", "live_start", "live_end"),
            "description": _(
                "Solo para tipo 'Sesión Zoom'. El número de reunión y el passcode se "
                "guardan en el servidor; el miembro NUNCA ve el link. El acceso se abre "
                "unos minutos antes de 'live start' y se cierra en 'live end'."
            ),
        }),
    )


@admin.register(ContentSchedule)
class ContentScheduleAdmin(admin.ModelAdmin):
    list_display = ["content", "plan", "starts_at", "ends_at"]
    list_filter = ["plan"]
    search_fields = ["content__title", "plan__name"]
    ordering = ["plan", "-starts_at"]


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ["name", "date", "price", "is_public", "is_active", "order"]
    list_filter = ["is_public", "is_active"]
    search_fields = ["name", "subtitle"]
    ordering = ["order", "name"]


@admin.register(EventOrder)
class EventOrderAdmin(admin.ModelAdmin):
    list_display = ["email", "event", "amount", "status", "created"]
    list_filter = ["status", "event"]
    search_fields = ["email", "name", "commerce_order"]
    ordering = ["-created"]
    readonly_fields = [f.name for f in EventOrder._meta.fields]


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ["kind", "email", "name", "source", "created"]
    list_filter = ["kind", "source", "created"]
    search_fields = ["email", "name", "subject", "message"]
    ordering = ["-created"]
    readonly_fields = [f.name for f in Lead._meta.fields]


@admin.register(LaunchSchedule)
class LaunchScheduleAdmin(admin.ModelAdmin):
    """Bloque de campaña (bienvenida + próximas actividades). Singleton: se edita
    la única fila; no se agrega ni se borra. Las columnas de actividades ya NO se
    editan aquí: se generan solas desde la Programación (``admin/programacion``)."""

    fieldsets = (
        (_("Visibilidad"), {"fields": ("enabled",)}),
        (_("Bienvenida"), {"fields": ("intro_title", "intro_body", "gift_note")}),
        (_("Próximas actividades"), {
            "fields": ("timezone_label", "heading", "signature"),
            "description": _(
                "Las columnas de actividades por nivel se generan automáticamente "
                "desde la Programación (sesiones en vivo próximas de cada membresía); "
                "ya no se editan a mano aquí."
            ),
        }),
        (_("Registro"), {"fields": ("created", "modified")}),
    )
    readonly_fields = ["created", "modified"]

    def has_add_permission(self, request):
        # Singleton: solo se edita la fila existente (se crea sola vía load()).
        return not LaunchSchedule.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CompMembership)
class CompMembershipAdmin(admin.ModelAdmin):
    """Accesos de cortesía / staff (ven el contenido sin suscripción real)."""

    list_display = ["email", "full_name", "all_plans", "is_active", "note", "created"]
    list_filter = ["is_active", "all_plans"]
    search_fields = ["email", "full_name", "note"]
    filter_horizontal = ["plans"]
    ordering = ["email"]
