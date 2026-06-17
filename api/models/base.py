"""
Generic template models: abstract bases, navigation menu, notifications,
API keys and UI settings. The custom ``User`` model lives in ``user.py``;
``django.contrib.auth.Group`` is reused as-is.
"""

from __future__ import annotations

import secrets
from typing import ClassVar
from uuid import uuid4

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.db import models
from django.db.models import SlugField
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from model_utils.models import TimeStampedModel as ModelUtilsTimeStampedModel


class TimeStampedModel(ModelUtilsTimeStampedModel):
    """django-model-utils ``created`` / ``modified`` timestamps only."""

    class Meta:
        abstract = True


class UppercaseFieldsMixin(models.Model):
    """
    Auto-uppercases ``CharField`` / ``TextField`` values on save. Opt-in:
    only models that explicitly inherit from this mixin get the behaviour.

    Skipped automatically: ``EmailField``, ``URLField``, ``SlugField``.
    Per-field overrides go in the subclass ``UPPERCASE_EXCLUDE_FIELDS``.

    Place at the end of the inheritance list so the uppercase pass runs
    just before ``models.Model.save()`` persists the row.
    """

    UPPERCASE_EXCLUDE_FIELDS: ClassVar[list[str]] = []

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        for field in self._meta.get_fields():
            if not hasattr(field, "attname"):
                continue
            if isinstance(
                field,
                (models.EmailField, models.URLField, SlugField),
            ):
                continue
            if field.attname in self.UPPERCASE_EXCLUDE_FIELDS:
                continue
            if isinstance(field, (models.CharField, models.TextField)):
                val = getattr(self, field.attname, None)
                if isinstance(val, str) and val:
                    setattr(self, field.attname, val.upper())
        super().save(*args, **kwargs)


class AbstractActiveModel(models.Model):
    """
    Abstract base with ``is_active`` for soft enable/disable without deletion.
    Use on models that need the flag without ``BaseModelGeneric`` (name/slug/uuid).
    """

    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        abstract = True


class AbstractUUIDModel(models.Model):
    """
    Abstract base with a prefixed external UUID (``PREFIX-uuid4``).
    Use for models that need a stable public id without ``BaseModelGeneric`` (name/slug).
    Set ``uuid_prefix`` on the subclass (letters only; first three are used in uppercase),
    or rely on the class name (e.g. ``MyThing`` → ``MYT``).
    """

    uuid_prefix: ClassVar[str | None] = None

    uuid = models.CharField(
        _("uuid"),
        max_length=40,
        unique=True,
        editable=False,
        blank=True,
        help_text=_("Format: XXX-uuid4. Assigned on first save."),
    )

    class Meta:
        abstract = True

    @classmethod
    def get_uuid_prefix(cls) -> str:
        raw = getattr(cls, "uuid_prefix", None)
        if raw:
            letters = "".join(c for c in str(raw) if c.isalpha())
            return (letters + "XXX")[:3].upper()
        letters = "".join(c for c in cls.__name__ if c.isalpha())
        return (letters + "XXX")[:3].upper()

    def _prefixed_uuid(self) -> str:
        return f"{self.get_uuid_prefix()}-{uuid4()}"

    def save(self, *args, **kwargs):
        if not self.uuid:
            self.uuid = self._prefixed_uuid()
        super().save(*args, **kwargs)


class BaseModelGeneric(AbstractUUIDModel, AbstractActiveModel):
    """
    Campos comunes: nombre, slug y ``uuid`` legible ``PREFIX-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx``.
    PREFIX = 3 letras del nombre de la clase (p. ej. ``Organization`` → ``ORG``), salvo que definas
    ``uuid_prefix = "REP"`` en la subclase (solo letras, se toman las 3 primeras en mayúsculas).
    Hereda ``AbstractUUIDModel`` y ``AbstractActiveModel`` para ``uuid`` e ``is_active``.
    """

    name = models.CharField(_("name"), max_length=255)
    slug = models.SlugField(_("slug"), max_length=255, unique=True, blank=True)

    class Meta:
        abstract = True

    def _ensure_slug_unique(self) -> None:
        base = slugify(self.name)
        if not base:
            base = "item"
        candidate = base
        n = 2
        manager = getattr(self.__class__, "all_objects", None)
        qs = manager.all() if manager is not None else self.__class__.objects.all()
        if self.pk:
            qs = qs.exclude(pk=self.pk)
        while qs.filter(slug=candidate).exists():
            candidate = f"{base}-{n}"
            n += 1
        self.slug = candidate

    def save(self, *args, **kwargs):
        if not self.slug:
            self._ensure_slug_unique()
        super().save(*args, **kwargs)


class Menu(BaseModelGeneric, TimeStampedModel, UppercaseFieldsMixin):
    """
    Root navigation document: contains ``MenuSection`` rows.

    Exactly one row may have ``is_default`` (enforced in ``save``): that menu is
    served to every authenticated user.
    """

    uuid_prefix = "MNU"
    UPPERCASE_EXCLUDE_FIELDS = [
        "name",
        "slug",
        "uuid",
        "description",
    ]

    description = models.TextField(_("description"), blank=True)
    is_default = models.BooleanField(
        _("default menu"),
        default=False,
        db_index=True,
        help_text=_(
            "If enabled, becomes the only default menu; all other menus are cleared. "
            "Served to every authenticated user."
        ),
    )

    class Meta:
        verbose_name = _("menu")
        verbose_name_plural = _("menus")
        ordering = ["name"]
        indexes = [
            # slug y uuid ya están indexados por unique=True; no duplicar.
            models.Index(fields=["is_active"]),
        ]

    def save(self, *args, **kwargs):
        if self.is_default:
            Menu.objects.exclude(pk=self.pk).filter(is_default=True).update(is_default=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class MenuSection(BaseModelGeneric, TimeStampedModel, UppercaseFieldsMixin):
    """Group of ``MenuItem`` rows under one ``Menu``."""

    uuid_prefix = "SEC"
    UPPERCASE_EXCLUDE_FIELDS = [
        "name",
        "slug",
        "uuid",
        "description",
    ]

    menu = models.ForeignKey(
        Menu,
        on_delete=models.CASCADE,
        related_name="sections",
        verbose_name=_("menu"),
    )
    description = models.TextField(_("description"), blank=True)
    order = models.PositiveSmallIntegerField(_("order"), default=0)

    class Meta:
        verbose_name = _("menu section")
        verbose_name_plural = _("menu sections")
        ordering = ["menu", "order", "id"]
        indexes = [
            models.Index(fields=["menu", "is_active"]),
            # slug y uuid ya están indexados por unique=True.
        ]

    def __str__(self):
        return f"{self.menu.name} › {self.name}"


class MenuItem(BaseModelGeneric, TimeStampedModel, UppercaseFieldsMixin):
    """
    Single nav link under a ``MenuSection``. ``allowed_roles`` lists which roles
    may see the item (e.g. ``[\"VIEWER\", \"EDITOR\"]``). Fail-closed: an empty
    list / ``None`` means ONLY staff see it (non-staff users do NOT); list one
    or more roles to also grant matching non-staff users. Staff always see every
    item. See ``api.roles.user_can_see_menu_item``.
    """

    uuid_prefix = "MIT"
    UPPERCASE_EXCLUDE_FIELDS = [
        "name",
        "slug",
        "uuid",
        "route",
        "icon",
        "description",
    ]

    section = models.ForeignKey(
        MenuSection,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name=_("section"),
    )
    description = models.TextField(_("description"), blank=True)
    route = models.CharField(
        _("route"),
        max_length=255,
        help_text=_("Path without domain, e.g. /users"),
    )
    icon = models.CharField(
        _("icon"),
        max_length=80,
        blank=True,
        help_text=_(
            "Nombre del glifo (ligature) de Google Material Icons (clásico), en snake_case; "
            "es el mismo texto que usa el frontend en Angular Material "
            "(`<mat-icon>nombre</mat-icon>`). El frontend carga Material Icons + "
            "Material Icons Outlined (NO Material Symbols), así que un glifo que solo "
            "exista en Symbols se vería en blanco. "
            "En el admin puedes usar las sugerencias al escribir (lista corta) o el enlace al catálogo. "
            "Catálogo: https://fonts.google.com/icons?icon.set=Material+Icons — "
            "Vacío: el frontend muestra el icono «label»."
        ),
    )
    order = models.PositiveSmallIntegerField(_("order"), default=0)
    allowed_roles = models.JSONField(
        _("allowed roles"),
        default=list,
        blank=True,
        help_text=_(
            'JSON list of role codes, e.g. ["VIEWER","ADMIN"]. '
            "Empty: only staff see this item (non-staff users will NOT); "
            "list roles to also grant matching non-staff users. Staff always see every item."
        ),
    )

    class Meta:
        verbose_name = _("menu item")
        verbose_name_plural = _("menu items")
        ordering = ["section", "order", "id"]
        indexes = [
            models.Index(fields=["section", "is_active"]),
            # slug y uuid ya están indexados por unique=True.
        ]

    def __str__(self):
        return f"{self.name} → {self.route}"


class Notification(TimeStampedModel):
    """
    Notificación dirigida a un usuario concreto. Polling desde el front
    (``GET /api/v1/notifications/``); marca como leída con
    ``POST /api/v1/notifications/{id}/read/``. Tres ``kind`` controlan color
    del icono en el panel del topbar:

    - ``system``: informativo (export terminado, etc.).
    - ``operational``: requiere atención (X usuarios sin acceso 90d).
    - ``critical``: bloqueante / urgente.
    """

    KIND_SYSTEM = "system"
    KIND_OPERATIONAL = "operational"
    KIND_CRITICAL = "critical"
    KIND_CHOICES = [
        (KIND_SYSTEM, _("System")),
        (KIND_OPERATIONAL, _("Operational")),
        (KIND_CRITICAL, _("Critical")),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name=_("user"),
    )
    kind = models.CharField(
        _("kind"),
        max_length=20,
        choices=KIND_CHOICES,
        default=KIND_SYSTEM,
    )
    title = models.CharField(_("title"), max_length=200)
    body = models.TextField(_("body"), blank=True)
    link = models.URLField(_("link"), max_length=500, blank=True)
    read_at = models.DateTimeField(_("read at"), null=True, blank=True)

    class Meta:
        verbose_name = _("notification")
        verbose_name_plural = _("notifications")
        ordering = ["-created"]
        indexes = [
            models.Index(fields=["user", "read_at"]),
            models.Index(fields=["user", "-created"]),
        ]

    def __str__(self):
        return f"{self.user.get_username()} — [{self.kind}] {self.title}"


class ApiKey(TimeStampedModel, UppercaseFieldsMixin):
    """
    Clave de API para integraciones: el cliente envía el valor completo una sola vez
    (formato ``<brand>.<prefijo>.<secreto>``, donde ``brand`` =
    ``settings.API_KEY_BRAND_PREFIX``, default ``fvx``); solo se guarda hash del
    secreto y el prefijo para búsqueda. La petición se autentica como ``user``
    (mismos permisos que ese usuario).
    """

    UPPERCASE_EXCLUDE_FIELDS = ["name", "prefix", "secret_hash"]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="api_keys",
        verbose_name=_("user"),
        help_text=_("Usuario cuyos permisos tendrán las llamadas con esta clave."),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="api_keys_created",
        verbose_name=_("created by"),
    )
    name = models.CharField(
        _("name"),
        max_length=100,
        blank=True,
        help_text=_("Etiqueta para identificar la integración (ej. app móvil X)."),
    )
    prefix = models.CharField(
        _("prefix"),
        max_length=16,
        unique=True,  # unique ya crea índice; db_index sería redundante.
        editable=False,
        help_text=_("Segmento público de la clave; forma parte del valor mostrado al crear."),
    )
    secret_hash = models.CharField(
        _("secret hash"),
        max_length=128,
        editable=False,
    )
    last_used_at = models.DateTimeField(
        _("last used at"),
        null=True,
        blank=True,
    )
    is_active = models.BooleanField(_("active"), default=True)
    expires_at = models.DateTimeField(
        _("expires at"),
        null=True,
        blank=True,
        help_text=_(
            "Si se setea, la clave deja de autenticar después de esta fecha. Vacío = no expira."
        ),
    )
    scopes = models.JSONField(
        _("scopes"),
        default=list,
        blank=True,
        help_text=_(
            'Lista de scopes permitidos (ej. ["uploads.write"]). Vacío = sin '
            "restricción de scope (la clave hereda los permisos del usuario). "
            "Se exige con `require_api_key_scope` en las vistas que lo necesiten."
        ),
    )

    class Meta:
        verbose_name = _("API key")
        verbose_name_plural = _("API keys")
        ordering = ["-created"]
        indexes = [
            models.Index(fields=["user", "is_active"]),
        ]

    def __str__(self):
        label = self.name or self.prefix
        return f"{label} → {self.user.get_username()}"

    @property
    def is_expired(self) -> bool:
        """True si tiene ``expires_at`` y ya pasó. La autenticación la rechaza."""
        return self.expires_at is not None and self.expires_at <= timezone.now()

    @classmethod
    def generate_credentials(cls) -> tuple[str, str, str]:
        """
        Genera ``prefix``, ``secret_hash`` y la clave completa
        ``<brand>.<prefix>.<secret>``. La marca (``brand``) es configurable vía
        ``settings.API_KEY_BRAND_PREFIX`` (default ``fvx``); el prefijo es hex
        (12 caracteres) único en tabla.
        """

        for _attempt in range(50):  # `_attempt` (no `_`): no pisar el `_` de gettext (F402)
            prefix = secrets.token_hex(6)
            if not cls.objects.filter(prefix=prefix).exists():
                break
        else:
            msg = "No se pudo asignar un prefijo único para la API key."
            raise RuntimeError(msg)

        secret = secrets.token_urlsafe(32)
        brand = settings.API_KEY_BRAND_PREFIX
        full_key = f"{brand}.{prefix}.{secret}"
        secret_hash = make_password(secret)
        return prefix, secret_hash, full_key


THEME_KEY_CHOICES = [
    ("tmp-default", _("Default (base)")),
    ("tmp-light", _("Light")),
    ("tmp-dark", _("Dark")),
    ("tmp-blackandwhite", _("High contrast (B/W)")),
    ("tmp-beige", _("Beige / warm")),
]


class UiSettings(TimeStampedModel, UppercaseFieldsMixin):
    """
    Singleton con ajustes de UI globales para el front (tema, título, logo).
    Solo debe existir un registro (pk=1). Se crea automáticamente vía migración.
    """

    UPPERCASE_EXCLUDE_FIELDS = ["app_title"]

    theme_key = models.CharField(
        _("theme key"),
        max_length=32,
        choices=THEME_KEY_CHOICES,
        default="tmp-default",
        help_text=_("Tema que el front aplicará al arrancar (sobrescribe localStorage)."),
    )
    app_title = models.CharField(
        _("app title"),
        max_length=100,
        blank=True,
        default="FVX Suscription",
        help_text=_("Título mostrado en la pestaña del navegador (fase 2)."),
    )
    logo_url = models.URLField(
        _("logo URL"),
        max_length=500,
        blank=True,
        null=True,
        help_text=_("URL del logo de marca (fase 2)."),
    )
    theme_overrides = models.JSONField(
        _("theme overrides"),
        default=dict,
        blank=True,
        help_text=_("Override de variables CSS --fvx-* por clave (fase 2)."),
    )

    class Meta:
        verbose_name = _("UI settings")
        verbose_name_plural = _("UI settings")

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        # Singleton: NO se borra. Antes era un `pass` silencioso (confuso: el
        # llamador creía haber borrado). Ahora es explícito y robusto — lanzamos
        # un error claro en vez de fallar callado. El admin ya bloquea el borrado
        # (UiSettingsAdmin.has_delete_permission → False); esto cubre los borrados
        # por CÓDIGO (shell/scripts). Para resetear los valores, edita el registro
        # o usa `UiSettings.load()` tras cambiar campos.
        raise models.ProtectedError(
            "UiSettings es un singleton y no puede eliminarse. "
            "Edita el registro (pk=1) en su lugar.",
            [self],
        )

    @classmethod
    def load(cls) -> "UiSettings":
        # Resiliente: si por cualquier razón no existe el singleton, lo crea.
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return f"UI settings — {self.theme_key}"
