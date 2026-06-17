"""Widgets reutilizables (admin, forms)."""

from django import forms
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from .material_icon_ligatures import MATERIAL_ICON_LIGATURES


class MaterialIconTextInput(forms.TextInput):
    """
    Campo texto con <datalist> de ligatures habituales (autocompletar al escribir)
    y enlace al catálogo oficial.
    """

    def __init__(self, attrs=None):
        base = {"placeholder": "people"}
        if attrs:
            base.update(attrs)
        super().__init__(base)

    def render(self, name, value, attrs=None, renderer=None):
        attrs = {} if attrs is None else {**attrs}
        safe_name = "".join(ch if ch.isalnum() else "_" for ch in name)
        dl_id = f"material_icon_dl_{safe_name}"
        attrs["list"] = dl_id
        input_html = super().render(name, value, attrs, renderer)
        options = format_html_join(
            "",
            '<option value="{}"></option>',
            ((lig,) for lig in MATERIAL_ICON_LIGATURES),
        )
        datalist = format_html('<datalist id="{}">{}</datalist>', dl_id, options)
        link = format_html(
            '<p class="help"><a href="{}" target="_blank" rel="noopener noreferrer">{}</a></p>',
            "https://fonts.google.com/icons?icon.set=Material+Icons",
            _("Abrir catálogo completo (Material Icons clásico)"),
        )
        return mark_safe(input_html + datalist + link)
