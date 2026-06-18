"""DRF serializers for subscription plans."""

from rest_framework import serializers

from .models import ContentItem, ContentSchedule, Event, Lead, Plan


class PlanSerializer(serializers.ModelSerializer):
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
            "created", "modified",
        ]
        read_only_fields = [
            "uuid", "slug", "flow_plan_id", "flow_synced_at", "flow_status",
            "last_sync_error", "created", "modified",
        ]


class PublicMembershipSerializer(serializers.ModelSerializer):
    """Shape consumed by the public membership cards (matches the frontend
    ``Membership`` interface). ``priceMonthly`` is null → 'Valor por confirmar'."""

    priceMonthly = serializers.IntegerField(source="amount", allow_null=True)

    class Meta:
        model = Plan
        fields = [
            "slug", "name", "tagline", "description", "cadence",
            "recorded", "features", "priceMonthly", "icon", "featured",
            "image_url", "interval",
        ]


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
            "image_url", "order", "is_published", "created",
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
            "starts_at", "ends_at", "created",
        ]
        read_only_fields = ["id", "content_title", "content_kind", "plan_name", "created"]


class MemberContentSerializer(serializers.ModelSerializer):
    """Pieza de la biblioteca del miembro (solo lectura)."""

    class Meta:
        model = ContentItem
        fields = ["id", "title", "kind", "text", "file_url", "external_url", "image_url", "created"]


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
