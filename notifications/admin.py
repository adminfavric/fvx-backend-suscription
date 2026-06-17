"""Admin Django para inspección y soporte de emails enviados."""

from django.contrib import admin

from .models import EmailMessage, EmailSuppression


@admin.register(EmailMessage)
class EmailMessageAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "template_name",
        "to_address",
        "status",
        "provider",
        "sent_at",
        "created",
    )
    list_filter = ("status", "template_name", "provider", "bounce_type")
    search_fields = ("to_address", "subject", "provider_message_id")
    date_hierarchy = "created"
    readonly_fields = (
        "to_address",
        "to_user",
        "template_name",
        "subject",
        "context_snapshot",
        "provider",
        "provider_message_id",
        "status",
        "sent_at",
        "delivered_at",
        "bounced_at",
        "bounce_type",
        "bounce_subtype",
        "complained_at",
        "error_message",
        "related_object_type",
        "related_object_id",
        "tags",
        "created",
        "modified",
    )
    ordering = ("-created",)

    def has_add_permission(self, request):
        # EmailMessage solo se crea desde el código, no manualmente.
        return False


@admin.register(EmailSuppression)
class EmailSuppressionAdmin(admin.ModelAdmin):
    list_display = ("email", "reason", "detail", "created")
    list_filter = ("reason",)
    search_fields = ("email", "notes")
    date_hierarchy = "created"
    ordering = ("-created",)
