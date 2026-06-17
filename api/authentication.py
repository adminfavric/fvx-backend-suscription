"""
Custom authentication classes for FVX Template API
"""

import re

from django.conf import settings
from django.contrib.auth.hashers import check_password
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication, CSRFCheck
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied

from .models import ApiKey


def _enforce_csrf(request):
    """Run Django's CSRF validation against ``request`` (double-submit token).

    Mirrors DRF's ``SessionAuthentication.enforce_csrf``: only unsafe methods
    (POST/PUT/PATCH/DELETE) are checked; safe methods pass through. Used by the
    cookie-based JWT auth — without it, the auto-attached HttpOnly cookie would
    make every state-changing endpoint forgeable cross-site.
    """

    def dummy_get_response(_request):  # pragma: no cover - never called
        return None

    check = CSRFCheck(dummy_get_response)
    check.process_request(request)
    reason = check.process_view(request, None, (), {})
    if reason:
        raise PermissionDenied(f"CSRF Failed: {reason}")


class ApiKeyAuthentication(BaseAuthentication):
    """
    Autenticación por clave de API.

    - Cabecera ``X-Api-Key: <brand>.<prefijo>.<secreto>``
    - O ``Authorization: Api-Key <brand>.<prefijo>.<secreto>`` (no confundir con Bearer JWT).

    ``brand`` = ``settings.API_KEY_BRAND_PREFIX`` (default ``fvx``).

    La clave completa solo se conoce al crear el registro; en BD se guarda prefijo + hash.
    """

    keyword = "api-key"

    def authenticate(self, request):
        raw = self._get_raw_key(request)
        if not raw:
            return None

        parts = raw.split(".", 2)
        # La marca debe coincidir con settings.API_KEY_BRAND_PREFIX (default "fvx";
        # configurable por proyecto). Antes era el literal hardcoded "fvx".
        if len(parts) != 3 or parts[0] != settings.API_KEY_BRAND_PREFIX:
            return None
        prefix, secret = parts[1], parts[2]
        if not prefix or not secret:
            return None
        if not re.fullmatch(r"[0-9a-fA-F]+", prefix):
            return None

        try:
            api_key = ApiKey.objects.select_related("user").get(
                prefix=prefix.lower(), is_active=True
            )
        except ApiKey.DoesNotExist:
            return None

        if not check_password(secret, api_key.secret_hash):
            raise AuthenticationFailed("Invalid API key.")

        if api_key.is_expired:
            raise AuthenticationFailed("API key expired.")

        user = api_key.user
        if not user.is_active:
            raise AuthenticationFailed("User account is disabled.")

        # Debounce: no convertir CADA request autenticada por API key en un
        # UPDATE (con ATOMIC_REQUESTS toda lectura sería lectura+escritura).
        # Basta refrescar ``last_used_at`` como mucho una vez por minuto.
        now = timezone.now()
        last = api_key.last_used_at
        if last is None or (now - last).total_seconds() > 60:
            ApiKey.objects.filter(pk=api_key.pk).update(last_used_at=now)

        return (user, api_key)

    def _get_raw_key(self, request):
        direct = request.META.get("HTTP_X_API_KEY")
        if direct:
            return direct.strip()

        auth = request.META.get("HTTP_AUTHORIZATION")
        if not auth:
            return None
        auth = auth.strip()
        lower = auth.lower()
        prefix = f"{self.keyword} "
        if lower.startswith(prefix):
            return auth[len(prefix) :].strip()
        return None

    def authenticate_header(self, request):
        return self.keyword.title()


class CustomJWTAuthentication(JWTAuthentication):
    """
    Custom JWT Authentication that adds additional checks
    """

    def authenticate(self, request):
        """
        Authenticate the request and return a two-tuple of (user, token)
        """
        header = self.get_header(request)
        if header is None:
            return None

        raw_token = self.get_raw_token(header)
        if raw_token is None:
            return None

        validated_token = self.get_validated_token(raw_token)
        user = self.get_user(validated_token)

        if not user.is_active:
            raise AuthenticationFailed("User account is disabled.")

        return (user, validated_token)


class JWTCookieAuthentication(CustomJWTAuthentication):
    """JWT auth con prioridad a cookie HttpOnly.

    Reemplazo del clásico ``Authorization: Bearer <token>`` por una cookie
    ``fvx_access`` que el browser maneja automáticamente. JS no puede leer
    cookies HttpOnly → XSS no puede exfiltrar el token (P0 #3 del audit).

    **Orden de búsqueda**:
    1. Cookie `settings.AUTH_COOKIE_ACCESS` → flujo SPA estándar.
    2. Header `Authorization` → compat con Swagger, Postman y API clients
       server-to-server que no manejan cookies.

    Si ninguno está presente devuelve ``None`` (DRF prueba el siguiente
    authentication class o responde 401).
    """

    def authenticate(self, request):
        raw_token = request.COOKIES.get(settings.AUTH_COOKIE_ACCESS)
        if raw_token:
            validated_token = self.get_validated_token(raw_token)
            user = self.get_user(validated_token)
            if not user.is_active:
                raise AuthenticationFailed("User account is disabled.")
            # CSRF SOLO en el camino por cookie: la cookie es una credencial
            # ambiente (el browser la adjunta sola) → un POST/PATCH/DELETE
            # cross-site sería forjable sin esto. El camino por header Bearer
            # (abajo) NO necesita CSRF: no hay credencial ambiente.
            _enforce_csrf(request)
            return (user, validated_token)
        # Fallback al header Bearer (Swagger, scripts, etc.) — sin CSRF.
        return super().authenticate(request)
