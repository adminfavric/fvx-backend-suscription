"""DRF serializers for subscription plans."""

from rest_framework import serializers

from .models import (
    CheckoutSession,
    CompMembership,
    ContentItem,
    ContentSchedule,
    EmailLog,
    Event,
    LaunchSchedule,
    Lead,
    PaymentProvider,
    Plan,
)


class EmailLogSerializer(serializers.ModelSerializer):
    """Historial de correos salientes (solo lectura)."""

    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    lead_email = serializers.CharField(source="lead.email", read_only=True, default="")

    class Meta:
        model = EmailLog
        fields = [
            "id", "sender_email", "kind", "kind_label", "subject",
            "to_email", "recipients_count", "note", "lead", "lead_email", "created",
        ]
        read_only_fields = fields


class PlanSerializer(serializers.ModelSerializer):
    # Precio USD efectivo (override o conversión desde CLP) — solo lectura.
    paypal_price_usd = serializers.SerializerMethodField()

    class Meta:
        model = Plan
        fields = [
            "id", "uuid", "name", "slug", "flow_plan_id",
            "amount", "currency", "interval", "interval_count",
            "trial_period_days", "days_until_due", "periods_number",
            "charges_retries_number",
            "tagline", "description", "cadence", "recorded", "features",
            "icon", "image_url", "featured", "is_public", "order", "is_active",
            "flow_synced_at", "flow_status", "last_sync_error",
            # PayPal (alternativa internacional en USD)
            "paypal_enabled", "paypal_amount", "paypal_currency", "paypal_price_usd",
            "paypal_plan_id", "paypal_product_id", "paypal_synced_at",
            "paypal_status", "paypal_last_sync_error",
            "created", "modified",
        ]
        read_only_fields = [
            "uuid", "slug", "flow_plan_id", "flow_synced_at", "flow_status",
            "last_sync_error", "paypal_price_usd", "paypal_plan_id", "paypal_product_id",
            "paypal_synced_at", "paypal_status", "paypal_last_sync_error",
            "created", "modified",
        ]

    def get_paypal_price_usd(self, obj: Plan):
        price = obj.paypal_price_usd
        return float(price) if price is not None else None


class PublicMembershipSerializer(serializers.ModelSerializer):
    """Shape consumed by the public membership cards (matches the frontend
    ``Membership`` interface). ``priceMonthly`` is null → 'Valor por confirmar'.
    ``paypalEnabled`` / ``priceUsd`` permiten al frontend ofrecer el botón de
    PayPal (alternativa internacional) y mostrar el precio aproximado en USD."""

    priceMonthly = serializers.IntegerField(source="amount", allow_null=True)
    paypalEnabled = serializers.SerializerMethodField()
    paypalPlanId = serializers.CharField(source="paypal_plan_id")
    priceUsd = serializers.SerializerMethodField()

    class Meta:
        model = Plan
        fields = [
            "slug", "name", "tagline", "description", "cadence",
            "recorded", "features", "priceMonthly", "icon", "featured",
            "image_url", "interval", "paypalEnabled", "paypalPlanId", "priceUsd",
        ]

    def get_paypalEnabled(self, obj: Plan) -> bool:
        return obj.is_paypal_purchasable

    def get_priceUsd(self, obj: Plan):
        price = obj.paypal_price_usd
        return float(price) if price is not None else None


class EventSerializer(serializers.ModelSerializer):
    """CRUD admin de eventos especiales (compra única)."""

    class Meta:
        model = Event
        fields = [
            "id", "uuid", "name", "slug", "subtitle", "description", "date",
            "price", "currency", "icon", "image_url", "is_public", "order",
            "is_active", "created", "modified",
        ]
        read_only_fields = ["id", "uuid", "slug", "created", "modified"]


class PublicEventSerializer(serializers.ModelSerializer):
    """Eventos para la página pública (compra directa)."""

    class Meta:
        model = Event
        fields = ["slug", "name", "subtitle", "description", "date", "price", "icon", "image_url"]


class ContentItemSerializer(serializers.ModelSerializer):
    """CRUD admin de las piezas de la biblioteca (independientes del plan)."""

    class Meta:
        model = ContentItem
        fields = [
            "id", "title", "kind", "text", "file_url", "external_url",
            "image_url", "order", "is_published",
            # Sesión en vivo (Zoom): número/passcode (solo servidor) + franja.
            "zoom_meeting_number", "zoom_passcode", "live_start", "live_end",
            "created",
        ]
        read_only_fields = ["id", "created"]


class ContentScheduleSerializer(serializers.ModelSerializer):
    """CRUD admin de la Programación (contenido ↔ plan con rango de fechas)."""

    content_title = serializers.CharField(source="content.title", read_only=True)
    content_kind = serializers.CharField(source="content.kind", read_only=True)
    plan_name = serializers.CharField(source="plan.name", read_only=True)

    class Meta:
        model = ContentSchedule
        fields = [
            "id", "content", "content_title", "content_kind", "plan", "plan_name",
            "starts_at", "ends_at", "date_mode", "created",
        ]
        read_only_fields = ["id", "content_title", "content_kind", "plan_name", "created"]


class MemberContentSerializer(serializers.ModelSerializer):
    """Pieza de la biblioteca del miembro (solo lectura).

    Para las sesiones Zoom expone la franja horaria (``live_start``/``live_end``)
    y dos banderas calculadas — ``has_zoom`` (tiene reunión configurada) y
    ``live_open`` (se puede entrar ahora) — para que la UI muestre el estado y
    habilite el botón "Entrar". NUNCA expone el número de reunión ni el passcode.
    """

    live_open = serializers.SerializerMethodField()
    has_zoom = serializers.SerializerMethodField()
    # Momentos exactos de apertura/cierre de la sala (incluyen el margen de 15 min
    # antes). El frontend los usa para la cuenta regresiva en vivo.
    opens_at = serializers.SerializerMethodField()
    closes_at = serializers.SerializerMethodField()
    # NUNCA se expone la URL permanente del archivo: el miembro pide una URL
    # FIRMADA de vida corta al endpoint ``/content/<id>/media/`` cuando reproduce.
    # Aquí solo va una bandera de si hay archivo, para que la UI sepa qué mostrar.
    has_file = serializers.SerializerMethodField()

    class Meta:
        model = ContentItem
        fields = [
            "id", "title", "kind", "text", "external_url", "image_url",
            "created", "live_start", "live_end", "live_open", "has_zoom",
            "opens_at", "closes_at", "has_file",
        ]

    def get_has_file(self, obj: ContentItem) -> bool:
        return bool(obj.file_url)

    def get_live_open(self, obj: ContentItem) -> bool:
        return obj.is_live_open() if obj.kind == ContentItem.Kind.ZOOM else False

    def get_has_zoom(self, obj: ContentItem) -> bool:
        return bool(obj.zoom_meeting_number) if obj.kind == ContentItem.Kind.ZOOM else False

    def get_opens_at(self, obj: ContentItem):
        return obj.live_opens_at if obj.kind == ContentItem.Kind.ZOOM else None

    def get_closes_at(self, obj: ContentItem):
        return obj.live_closes_at if obj.kind == ContentItem.Kind.ZOOM else None


class CompMembershipSerializer(serializers.ModelSerializer):
    """Acceso de cortesía/staff (CRUD admin). ``plans`` recibe/lista IDs de plan;
    ``plan_names`` es solo lectura para mostrarlos en la tabla."""

    plan_names = serializers.SerializerMethodField()

    class Meta:
        model = CompMembership
        fields = [
            "id", "email", "full_name", "all_plans", "plans", "plan_names",
            "is_active", "note", "created",
        ]
        read_only_fields = ["id", "plan_names", "created"]

    def get_plan_names(self, obj) -> str:
        return ", ".join(obj.plans.values_list("name", flat=True)) or ("Todas" if obj.all_plans else "—")


class PaymentLinkSerializer(serializers.ModelSerializer):
    """
    Cobro por LINK DE PAGO de Flow. El admin genera un link (pago único que
    habilita ``period_months`` meses); se envía al cliente, que paga con cualquier
    medio (tarjeta, débito, transferencia) dentro de Flow. Al confirmar el pago
    (botón "Verificar pago"), la membresía pasa a ``subscribed`` y se fija
    ``access_until = hoy + period_months``. Se guarda como ``CheckoutSession`` con
    ``provider="flow_mensual"``.

    Para CREAR solo se envían ``plan``, ``email``, ``name`` y ``months``; el resto
    (token, URL del link, estado) lo completa la vista al llamar a Flow.
    """

    plan_name = serializers.CharField(source="plan.name", read_only=True)
    is_active = serializers.SerializerMethodField()
    is_paid = serializers.SerializerMethodField()
    # Alias de entrada para los meses (el modelo usa ``period_months``).
    months = serializers.IntegerField(source="period_months", required=False, min_value=1, default=1)

    class Meta:
        model = CheckoutSession
        fields = [
            "id", "plan", "plan_name", "name", "email", "months",
            "access_until", "payment_url", "status", "provider",
            "is_active", "is_paid", "created",
        ]
        read_only_fields = [
            "id", "plan_name", "access_until", "payment_url", "status",
            "provider", "is_active", "is_paid", "created",
        ]

    def get_is_active(self, obj: CheckoutSession) -> bool:
        return obj.has_period_access and obj.status == CheckoutSession.Status.SUBSCRIBED

    def get_is_paid(self, obj: CheckoutSession) -> bool:
        return obj.status == CheckoutSession.Status.SUBSCRIBED


class LaunchScheduleSerializer(serializers.ModelSerializer):
    """Bloque de campaña editable (bienvenida + próximas actividades). Forma
    consumida por ``app-launch-schedule`` en el sitio público y por el editor del
    panel admin."""

    class Meta:
        model = LaunchSchedule
        fields = [
            "enabled", "intro_title", "intro_body", "gift_note",
            "timezone_label", "heading", "tiers", "signature",
        ]

    def validate_tiers(self, value):
        """``tiers`` debe ser una lista de columnas normalizadas: cada una con
        ``name`` (texto), ``badge``/``featured`` opcionales e ``items`` (lista de
        ``{title, when}``). Se normaliza para no publicar formas que rompan el
        render del sitio."""
        if not isinstance(value, list):
            raise serializers.ValidationError("Debe ser una lista de columnas.")
        clean = []
        for col in value:
            if not isinstance(col, dict):
                raise serializers.ValidationError("Cada columna debe ser un objeto.")
            items = []
            for it in col.get("items") or []:
                if not isinstance(it, dict):
                    continue
                title = str(it.get("title", "")).strip()
                if not title:
                    continue
                items.append({"title": title, "when": str(it.get("when", "")).strip()})
            clean.append({
                "name": str(col.get("name", "")).strip(),
                "badge": str(col.get("badge", "")).strip(),
                "featured": bool(col.get("featured", False)),
                "items": items,
            })
        return clean


class LeadSerializer(serializers.ModelSerializer):
    """
    Captura flexible de leads del sitio público. El frontend manda formas
    distintas según el formulario (newsletter/contact/maraton); aquí se mapean
    los campos conocidos y se conserva el payload íntegro en ``raw``.

    Acepta ``fullName`` (del diálogo de maratón) como alias de ``name``.
    """

    fullName = serializers.CharField(required=False, allow_blank=True, write_only=True)

    class Meta:
        model = Lead
        fields = [
            "id", "kind", "source", "name", "email", "phone",
            "country", "subject", "message", "fullName", "created",
            "is_read", "is_replied",
        ]
        read_only_fields = ["id", "created", "is_read", "is_replied"]

    def create(self, validated_data):
        full_name = validated_data.pop("fullName", "")
        if full_name and not validated_data.get("name"):
            validated_data["name"] = full_name
        # Conservar el payload original completo (incluye campos no modelados).
        request = self.context.get("request")
        validated_data["raw"] = dict(request.data) if request is not None else dict(validated_data)
        return super().create(validated_data)
