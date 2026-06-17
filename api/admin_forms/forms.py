"""Forms for admin and API (keep model logic in models.py)."""

from django import forms
from django.utils.translation import gettext_lazy as _

from ..choices import ROLE_CHOICES
from ..models import MenuItem
from .widgets import MaterialIconTextInput


class MenuItemAdminForm(forms.ModelForm):
    """
    Reemplaza el JSONField crudo de ``allowed_roles`` por selección múltiple
    (códigos de rol alineados con ``user_can_see_menu_item``).
    """

    allowed_roles = forms.MultipleChoiceField(
        label=_("Allowed roles"),
        choices=ROLE_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text=_(
            "Empty: only staff users see this item (non-staff users will NOT). "
            "Select one or more roles to also show it to users whose effective role matches. "
            "Staff always see every item regardless of this field."
        ),
    )

    class Meta:
        model = MenuItem
        fields = "__all__"
        widgets = {
            "icon": MaterialIconTextInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            raw = self.instance.allowed_roles or []
            valid = {c[0] for c in ROLE_CHOICES}
            self.initial["allowed_roles"] = [r for r in raw if r in valid]
