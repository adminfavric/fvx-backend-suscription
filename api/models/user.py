"""Custom user model for the FVX template.

Declaring a custom ``User`` from day zero lets downstream projects extend the
user with new fields (e.g. ``tax_id``, ``mfa_enabled``) via a routine
``makemigrations`` instead of Django's traumatic ``AUTH_USER_MODEL`` swap.

The class intentionally absorbs what previously lived in a separate ``Profile``
(``role``, ``phone``, ``photo_url``, ``verified``, ``ui_preferences``) so a
single query loads everything needed for the authenticated user. No more
``select_related('profile')`` and no more defensive ``hasattr(user, 'profile')``
checks across the codebase.

Soft-delete: ``User`` is a primary business entity, so it carries
``is_removed`` via ``SoftDeletableModel`` (the template's rule — config/link
models keep only ``is_active``). Two states coexist intentionally:

* ``is_active=False`` — reversible disable (suspended account, can be re-enabled
  from the UI; the row stays visible to admins). Django uses it to block login.
* ``is_removed=True`` — logical delete (hidden from the default manager and the
  UI; recoverable by an admin or via ``all_objects``). A row is never destroyed.

``DELETE`` on the user endpoint soft-deletes; ``objects`` excludes removed rows,
``all_objects`` returns everything.
"""

from __future__ import annotations

from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _
from model_utils.managers import SoftDeletableManager
from model_utils.models import SoftDeletableModel

from ..choices import ROLE_CHOICES, ROLE_VIEWER
from .base import TimeStampedModel


class UserManager(DjangoUserManager, SoftDeletableManager):
    """Combines Django's ``UserManager`` (``create_user`` / ``create_superuser`` /
    ``get_by_natural_key`` / ``use_in_migrations``) with soft-delete filtering.

    MRO resolves ``get_queryset`` to ``SoftDeletableManager`` (filters
    ``is_removed=False``) and ``_queryset_class`` to ``SoftDeletableQuerySet``
    (so ``.delete()`` is soft), while the account-creation helpers come from
    ``DjangoUserManager``. As the model's default manager, this means a
    soft-removed account cannot authenticate (``ModelBackend`` resolves users
    through ``_default_manager``) — the desired behaviour.
    """


class User(AbstractUser, TimeStampedModel, SoftDeletableModel):
    """Application user. Extends Django's ``AbstractUser`` with role, contact and
    UI-preferences fields. Not subject to ``UppercaseFieldsMixin``: first_name /
    last_name / phone are user-typed values that must keep case."""

    role = models.CharField(
        _("role"),
        max_length=20,
        default=ROLE_VIEWER,
        choices=ROLE_CHOICES,
    )
    phone = models.CharField(_("phone"), max_length=50, blank=True)
    photo_url = models.URLField(_("photo URL"), max_length=500, blank=True)
    verified = models.BooleanField(_("verified"), default=False)
    ui_preferences = models.JSONField(
        _("UI preferences"),
        default=dict,
        blank=True,
        help_text=_(
            "Shell preferences for the frontend (theme, page width, UI locale, "
            "appearance panel collapse state). Shallow-merged on PATCH; "
            "unknown keys are preserved."
        ),
    )

    # Default manager: account helpers + soft-delete filtering (excludes removed).
    objects = UserManager()
    # Escape hatch: every row including soft-removed, with account helpers intact.
    all_objects = DjangoUserManager()

    class Meta:
        verbose_name = _("user")
        verbose_name_plural = _("users")
        ordering = ["username"]
        default_manager_name = "objects"
        indexes = [
            models.Index(fields=["role"]),
            models.Index(fields=["verified"]),
            models.Index(fields=["is_removed"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_username()} — {self.role}"
