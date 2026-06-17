"""DRF permissions for the generic template API."""

from rest_framework import permissions


class IsAdminOrReadOnly(permissions.BasePermission):
    """Authenticated read; writes for staff or users with ``role == 'ADMIN'``."""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in permissions.SAFE_METHODS:
            return True
        if request.user.is_staff:
            return True
        return getattr(request.user, "role", None) == "ADMIN"


def require_api_key_scope(scope: str):
    """Factory de permiso: exige ``scope`` SOLO cuando la request se autentica
    por API key con scopes definidos.

    - Auth que NO es API key (JWT/sesión) → pasa (los scopes solo acotan llaves).
    - API key con ``scopes`` vacío → pasa (sin restricción; hereda los permisos
      del usuario).
    - API key con scopes → debe incluir ``scope``.

    Uso en una vista::

        permission_classes = [IsAuthenticated, require_api_key_scope("uploads.write")]
    """

    class _ApiKeyScopePermission(permissions.BasePermission):
        message = f"This API key lacks the required scope: {scope}."

        def has_permission(self, request, view):
            # ``request.auth`` es la ApiKey cuando autenticó ApiKeyAuthentication.
            scopes = getattr(getattr(request, "auth", None), "scopes", None)
            if scopes is None:  # no autenticado por API key
                return True
            if not scopes:  # API key sin scopes = sin restricción
                return True
            return scope in scopes

    return _ApiKeyScopePermission
