"""DRF permissions — reexporta clases para ``from api.permissions import …``."""

from .drf import IsAdminOrReadOnly, require_api_key_scope

__all__ = ["IsAdminOrReadOnly", "require_api_key_scope"]
