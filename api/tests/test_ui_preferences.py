"""Unit tests for the UI-preferences patch validator (pure logic, no DB).

``validate_ui_preferences_patch`` is the allow-list/clamp guarding
``User.ui_preferences`` (theme, page width, UI lang, favorites). It's pure, so
these are fast unit tests — intentionally NO ``django_db``. They pin the
favorites rules exercised during stabilization (max 5, order-preserving dedup,
non-empty strings) plus the theme allow-list + legacy alias.
"""

import pytest
from rest_framework.exceptions import ValidationError

from api.shell.ui_preferences import (
    ALLOWED_FAVORITES_MAX,
    validate_ui_preferences_patch,
)


# ── Shape / allow-list ──────────────────────────────────────────────────────


def test_valid_full_patch_passes_through():
    data = {
        "theme_id": "tmp-dark",
        "page_content_width": "compact",
        "ui_lang": "es",
        "appearance_section_expanded": True,
        "favorite_menu_items": ["menu-users", "menu-groups"],
    }
    assert validate_ui_preferences_patch(data) == data


def test_empty_patch_returns_empty():
    assert validate_ui_preferences_patch({}) == {}


def test_unknown_keys_are_dropped():
    # Allow-list: claves no reconocidas se descartan en silencio.
    assert validate_ui_preferences_patch({"theme_id": "tmp-dark", "hacker": "x"}) == {
        "theme_id": "tmp-dark"
    }


def test_non_dict_body_raises():
    with pytest.raises(ValidationError):
        validate_ui_preferences_patch(["not", "a", "dict"])


# ── Theme / width / lang enumerados ─────────────────────────────────────────


def test_theme_alias_is_normalized():
    # tmp-hybrid fue fusionado en tmp-default.
    assert validate_ui_preferences_patch({"theme_id": "tmp-hybrid"})["theme_id"] == "tmp-default"


def test_invalid_theme_raises():
    with pytest.raises(ValidationError):
        validate_ui_preferences_patch({"theme_id": "not-a-theme"})


def test_invalid_page_width_raises():
    with pytest.raises(ValidationError):
        validate_ui_preferences_patch({"page_content_width": "huge"})


def test_invalid_lang_raises():
    with pytest.raises(ValidationError):
        validate_ui_preferences_patch({"ui_lang": "fr"})


def test_appearance_must_be_bool():
    with pytest.raises(ValidationError):
        validate_ui_preferences_patch({"appearance_section_expanded": "yes"})


# ── Favoritos: las reglas que tocamos/aseguramos esta sesión ────────────────


def test_favorites_dedup_preserves_order():
    out = validate_ui_preferences_patch({"favorite_menu_items": ["a", "b", "a", "c", "b"]})
    assert out["favorite_menu_items"] == ["a", "b", "c"]


def test_favorites_over_max_raises():
    too_many = [f"item-{i}" for i in range(ALLOWED_FAVORITES_MAX + 1)]
    with pytest.raises(ValidationError):
        validate_ui_preferences_patch({"favorite_menu_items": too_many})


def test_favorites_must_be_nonempty_strings():
    with pytest.raises(ValidationError):
        validate_ui_preferences_patch({"favorite_menu_items": ["ok", "  "]})
    with pytest.raises(ValidationError):
        validate_ui_preferences_patch({"favorite_menu_items": ["ok", 123]})


def test_favorites_must_be_a_list():
    with pytest.raises(ValidationError):
        validate_ui_preferences_patch({"favorite_menu_items": "menu-users"})
