"""Cuentas de proveedores sociales (Google, Apple, Microsoft) enlazadas a Usuario de Django."""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from .base import TimeStampedModel, UppercaseFieldsMixin


class SocialProvider(models.TextChoices):
    GOOGLE = "google", _("Google")
    APPLE = "apple", _("Apple")
    MICROSOFT = "microsoft", _("Microsoft")


class SocialAccount(TimeStampedModel, UppercaseFieldsMixin):
    """
    Vinculación 1:1 lógica por (provider, uid) con posibilidad de varias cuentas
    (proveedores distintos) hacia un mismo user.
    """

    # provider debe coincidir con TextChoices ("google"/"apple"/"microsoft"); uid no debe
    # mutarse (subject del proveedor); el resto de CharFields pasa por el mixin.
    UPPERCASE_EXCLUDE_FIELDS = ["provider", "uid"]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="social_accounts",
    )
    provider = models.CharField(
        max_length=20,
        choices=SocialProvider.choices,
        db_index=True,
    )
    uid = models.CharField(
        max_length=255,
        help_text="Subject (sub) del id_token del proveedor.",
    )
    email = models.EmailField(
        null=True,
        blank=True,
        help_text="Email visto al enlazar; Apple puede dejar de enviarlo en re-inicios.",
    )

    class Meta:
        unique_together = [("provider", "uid")]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "provider"],
                name="api_socialaccount_user_provider_uniq",
            )
        ]
        indexes = [
            models.Index(fields=["provider", "uid"]),
        ]
        verbose_name = _("social account")
        verbose_name_plural = _("social accounts")

    def __str__(self) -> str:
        return f"{self.provider}:{self.uid} → {self.user_id}"
