"""Cache del árbol de menú (``GET /menus/tree/``) con invalidación por versión.

La respuesta del menú depende del menú resuelto y del rol efectivo del usuario,
y cambia rara vez (la edita un admin). En vez de recomputarla en cada request,
se cachea con una clave que incluye una **versión global**; cualquier cambio en
``Menu`` / ``MenuSection`` / ``MenuItem`` (vía signals) **incrementa la versión**,
invalidando todas las entradas sin tener que enumerarlas.
"""

from django.core.cache import cache

_MENU_VER_KEY = "fvx:menu_tree:ver"
MENU_CACHE_TTL = 300  # backstop; la invalidación real es por versión


def menu_cache_version() -> int:
    """Versión actual del cache de menú (la crea en 1 si no existe)."""
    v = cache.get(_MENU_VER_KEY)
    if v is None:
        cache.set(_MENU_VER_KEY, 1, None)
        return 1
    return v


def bump_menu_cache_version() -> None:
    """Invalida todo el cache de menú incrementando la versión."""
    try:
        cache.incr(_MENU_VER_KEY)
    except ValueError:
        # La clave no existía aún (incr falla); inicializa.
        cache.set(_MENU_VER_KEY, 1, None)
