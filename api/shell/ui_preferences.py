"""Validación y fusión de ``User.ui_preferences`` (shell Angular).

JSONField del custom user model que persiste las preferencias del shell del
front (tema, ancho de página, idioma, panel apariencia). Validación
allow-list: claves desconocidas se descartan; valores fuera del enumerado
devuelven 400.
"""

from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ValidationError

ALLOWED_THEME_IDS = frozenset(
    {
        "tmp-default",
        "tmp-light",
        "tmp-dark",
        "tmp-blackandwhite",
        "tmp-beige",
    }
)

# Antiguos valores persistidos en BD / cliente (renombre / fusión de temas).
_THEME_ID_ALIASES = {"tmp-hybrid": "tmp-default"}
ALLOWED_PAGE_WIDTH = frozenset({"compact", "extended"})
ALLOWED_UI_LANG = frozenset({"en", "es"})
# Densidad de las tablas de datos (alto de fila). Global del usuario; el front
# arranca en "compact" si no hay preferencia guardada.
ALLOWED_TABLE_DENSITY = frozenset({"compact", "normal"})

# Máximo de items "favoritos" del menú que un usuario puede marcar para que
# aparezcan al tope del sidebar. La lista se persiste como una lista de slugs
# de ``MenuItem`` (ej. ``["menu-users", "fallback-components"]``) cuya
# posición determina el orden visual.
ALLOWED_FAVORITES_MAX = 5


def validate_ui_preferences_patch(data: dict) -> dict:
    """
    Valida solo claves reconocidas en un PATCH parcial.
    Devuelve un dict con entradas válidas (subconjunto de ``data``).
    """
    if not isinstance(data, dict):
        raise ValidationError(_("El cuerpo debe ser un objeto JSON."))

    out = {}
    errors = {}

    if "theme_id" in data:
        v = data["theme_id"]
        if v is not None:
            v = _THEME_ID_ALIASES.get(str(v), str(v))
        if v is not None and v not in ALLOWED_THEME_IDS:
            errors["theme_id"] = _("Valor de tema no permitido.")
        else:
            out["theme_id"] = v

    if "page_content_width" in data:
        v = data["page_content_width"]
        if v not in ALLOWED_PAGE_WIDTH:
            errors["page_content_width"] = _("Valor de ancho de página no permitido.")
        else:
            out["page_content_width"] = v

    if "ui_lang" in data:
        v = data["ui_lang"]
        if v not in ALLOWED_UI_LANG:
            errors["ui_lang"] = _("Idioma UI no permitido.")
        else:
            out["ui_lang"] = v

    if "appearance_section_expanded" in data:
        v = data["appearance_section_expanded"]
        if not isinstance(v, bool):
            errors["appearance_section_expanded"] = _("Debe ser booleano.")
        else:
            out["appearance_section_expanded"] = v

    if "table_density" in data:
        v = data["table_density"]
        if v not in ALLOWED_TABLE_DENSITY:
            errors["table_density"] = _("Valor de densidad de tabla no permitido.")
        else:
            out["table_density"] = v

    if "favorite_menu_items" in data:
        v = data["favorite_menu_items"]
        if not isinstance(v, list):
            errors["favorite_menu_items"] = _("Debe ser una lista de slugs.")
        elif len(v) > ALLOWED_FAVORITES_MAX:
            errors["favorite_menu_items"] = _("Máximo %(max)d favoritos.") % {
                "max": ALLOWED_FAVORITES_MAX
            }
        else:
            # Cada elemento debe ser un string no vacío. Se dedupea preservando
            # el orden — el orden importa porque define la posición en el
            # sidebar.
            cleaned: list[str] = []
            seen: set[str] = set()
            invalid = False
            for item in v:
                if not isinstance(item, str) or not item.strip():
                    invalid = True
                    break
                key = item.strip()
                if key not in seen:
                    seen.add(key)
                    cleaned.append(key)
            if invalid:
                errors["favorite_menu_items"] = _("Cada favorito debe ser un slug no vacío.")
            else:
                out["favorite_menu_items"] = cleaned

    if errors:
        raise ValidationError(errors)

    return out


def merge_ui_preferences(existing: dict | None, validated_patch: dict) -> dict:
    base = dict(existing) if isinstance(existing, dict) else {}
    base.update(validated_patch)
    return base
