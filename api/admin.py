"""Django admin for the generic template API."""

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _

from .admin_forms import MenuItemAdminForm
from .models import (
    ApiKey,
    Menu,
    MenuItem,
    MenuSection,
    Notification,
    SocialAccount,
    UiSettings,
)

User = get_user_model()


class UserAdmin(BaseUserAdmin):
    """Custom UserAdmin: exposes the fields absorbed from the former Profile
    model (``role``, ``phone``, ``photo_url``, ``verified``, ``ui_preferences``)
    plus Django defaults."""

    list_display = [
        "username",
        "email",
        "first_name",
        "last_name",
        "role",
        "is_staff",
        "is_active",
        "verified",
    ]
    list_filter = ["role", "is_staff", "is_active", "verified", "date_joined"]
    search_fields = ["username", "email", "first_name", "last_name", "phone"]
    fieldsets = BaseUserAdmin.fieldsets + (
        (
            _("Profile (FVX)"),
            {
                "fields": ("role", "phone", "photo_url", "verified", "ui_preferences"),
            },
        ),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        (
            _("Profile (FVX)"),
            {
                "classes": ("wide",),
                "fields": ("role", "phone", "photo_url"),
            },
        ),
    )


admin.site.register(User, UserAdmin)


class MenuItemInline(admin.TabularInline):
    model = MenuItem
    form = MenuItemAdminForm
    extra = 0
    ordering = ["order", "id"]
    fields = ["name", "route", "icon", "order", "allowed_roles", "is_active"]
    readonly_fields = ["slug", "uuid", "created", "modified"]


class MenuSectionInline(admin.TabularInline):
    model = MenuSection
    extra = 0
    ordering = ["order", "id"]
    fields = ["name", "order", "is_active"]
    show_change_link = True
    readonly_fields = ["slug", "uuid", "created", "modified"]


@admin.register(Menu)
class MenuAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "uuid",
        "is_default",
        "is_active",
        "created",
        "modified",
    ]
    list_filter = ["is_active", "is_default"]
    search_fields = ["name", "uuid", "slug"]
    ordering = ["name"]
    fields = [
        "name",
        "is_default",
        "description",
        "is_active",
        "slug",
        "uuid",
        "created",
        "modified",
    ]
    readonly_fields = ["slug", "uuid", "created", "modified"]
    inlines = [MenuSectionInline]


@admin.register(MenuSection)
class MenuSectionAdmin(admin.ModelAdmin):
    list_display = ["name", "menu", "order", "is_active", "created"]
    list_filter = ["is_active", "menu"]
    search_fields = ["name", "uuid", "menu__name"]
    ordering = ["menu", "order", "id"]
    autocomplete_fields = ["menu"]
    inlines = [MenuItemInline]
    readonly_fields = ["slug", "uuid", "created", "modified"]


@admin.register(MenuItem)
class MenuItemAdmin(admin.ModelAdmin):
    form = MenuItemAdminForm
    list_display = ["name", "section", "route", "order", "is_active", "created"]
    list_filter = ["is_active", "section__menu"]
    search_fields = ["name", "uuid", "route", "section__name"]
    ordering = ["section", "order", "id"]
    autocomplete_fields = ["section"]
    readonly_fields = ["slug", "uuid", "created", "modified"]


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["title", "user", "kind", "read_at", "created"]
    list_filter = ["kind", "read_at"]
    search_fields = ["title", "body", "user__username", "user__email"]
    ordering = ["-created"]
    autocomplete_fields = ["user"]
    readonly_fields = ["created", "modified"]


@admin.register(ApiKey)
class ApiKeyAdmin(admin.ModelAdmin):
    list_display = [
        "prefix",
        "name",
        "user",
        "created_by",
        "is_active",
        "expires_at",
        "last_used_at",
        "created",
    ]
    list_filter = ["is_active"]
    search_fields = ["name", "prefix", "user__username", "created_by__username"]
    ordering = ["-created"]
    readonly_fields = ["prefix", "secret_hash", "created", "modified", "last_used_at"]
    raw_id_fields = ["user", "created_by"]


@admin.register(SocialAccount)
class SocialAccountAdmin(admin.ModelAdmin):
    list_display = ["user", "provider", "uid", "email", "created", "modified"]
    list_filter = ["provider"]
    search_fields = ["uid", "email", "user__username", "user__email"]
    raw_id_fields = ["user"]
    readonly_fields = ["created", "modified"]


@admin.register(UiSettings)
class UiSettingsAdmin(admin.ModelAdmin):
    list_display = ["theme_key", "app_title", "modified"]
    fields = ["theme_key", "app_title", "logo_url", "theme_overrides", "created", "modified"]
    readonly_fields = ["created", "modified"]

    def has_add_permission(self, request):
        # Singleton: evitar crear más de un registro desde el admin.
        return not UiSettings.objects.filter(pk=1).exists()

    def has_delete_permission(self, request, obj=None):
        return False
