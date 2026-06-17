"""Vistas ligadas a autenticación (JWT) con tokens en cookies HttpOnly.

El access y refresh viajan en cookies HttpOnly (set por estas vistas) — lo más
seguro para front + API en el mismo dominio raíz. Además se devuelven en el
body para soportar SPAs cross-domain (front y API en dominios raíz distintos),
donde la cookie de terceros queda bloqueada por el navegador y el cliente debe
guardar el token y mandarlo vía `Authorization: Bearer`.
"""

from django.conf import settings
from django.middleware.csrf import get_token
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .cookies import clear_auth_cookies, set_auth_cookies
from .serializers import FvxTokenObtainPairSerializer
from .throttles import (
    LoginIPRateThrottle,
    LoginUsernameRateThrottle,
    TokenRefreshRateThrottle,
)


class FvxTokenObtainPairView(TokenObtainPairView):
    """``POST /api/auth/token/`` — set HttpOnly cookies con access + refresh.

    Mensaje explícito si la cuenta existe pero está inactiva. Protegido
    contra credential stuffing y brute force con rate-limit por IP y por
    username (ver ``throttles.py``).
    """

    serializer_class = FvxTokenObtainPairSerializer
    throttle_classes = [LoginIPRateThrottle, LoginUsernameRateThrottle]

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == status.HTTP_200_OK and "access" in response.data:
            access = response.data["access"]
            refresh = response.data.get("refresh")
            set_auth_cookies(response, access, refresh)
            # Emite la cookie `csrftoken` (legible por JS) para el double-submit
            # CSRF que exige JWTCookieAuthentication en requests mutantes.
            get_token(request)
            # Tokens también en el body: los SPA cross-domain (front en otro
            # dominio raíz que el API) no pueden usar la cookie HttpOnly de
            # terceros, así que guardan el token y lo mandan vía
            # `Authorization: Bearer`. Same-domain sigue usando las cookies.
            response.data = {"access": access, "refresh": refresh}
        return response


class FvxTokenRefreshView(TokenRefreshView):
    """``POST /api/auth/token/refresh/`` — lee refresh de cookie, set nuevo access cookie.

    Rate-limited por IP. El frontend NO manda nada en el body — la cookie
    `fvx_refresh` viaja automáticamente con el request (su `Path=/api/auth/`
    permite que llegue acá).
    """

    throttle_classes = [TokenRefreshRateThrottle]

    def post(self, request, *args, **kwargs):
        # Inyectar el refresh de la cookie al body para que el serializer base
        # de simplejwt lo procese. Si el cliente además mandó `refresh` en
        # el body (uso de Swagger / Postman), priorizamos la cookie.
        cookie_refresh = request.COOKIES.get(settings.AUTH_COOKIE_REFRESH)
        if cookie_refresh:
            # request.data puede ser inmutable (QueryDict); copiamos.
            data = request.data.copy() if hasattr(request.data, "copy") else dict(request.data)
            data["refresh"] = cookie_refresh
            request._full_data = data  # noqa: SLF001 — DRF stores parsed body acá

        response = super().post(request, *args, **kwargs)
        if response.status_code == status.HTTP_200_OK and "access" in response.data:
            access = response.data["access"]
            # Con ROTATE_REFRESH_TOKENS=True, simplejwt devuelve un refresh
            # nuevo y blacklistea el viejo. Si no rota (config off), no lo
            # incluimos para mantener el refresh original con su exp original.
            refresh = response.data.get("refresh")
            set_auth_cookies(response, access, refresh)
            get_token(request)  # mantener fresca la cookie csrftoken
            # Tokens en el body para clientes SPA cross-domain (ver login).
            response.data = {"access": access, "refresh": refresh}
        return response


class LogoutView(APIView):
    """``POST /api/auth/logout/`` — cierra sesión server-side.

    Hace dos cosas:
    1. **Blacklistea el refresh token** (si está) para que aunque alguien lo
       hubiera robado antes, no pueda obtener nuevos access tokens.
    2. **Borra las cookies** `fvx_access` y `fvx_refresh` del browser.

    El access token vivo sigue siendo válido hasta su `exp` (lifetime corto),
    pero el atacante no puede renovarlo → la sesión muere en minutos.
    """

    permission_classes = [AllowAny]  # OK pasar sin auth (idempotente)
    authentication_classes = []  # evita 401 si cookies expiraron

    def post(self, request, *args, **kwargs):
        refresh_token = request.COOKIES.get(settings.AUTH_COOKIE_REFRESH)
        if refresh_token:
            try:
                # Blacklist requiere `rest_framework_simplejwt.token_blacklist`
                # en INSTALLED_APPS (ya está activado).
                RefreshToken(refresh_token).blacklist()
            except TokenError:
                # Token ya expirado/blacklisteado; tampoco se renovará.
                pass
        response = Response({"detail": "OK"}, status=status.HTTP_200_OK)
        clear_auth_cookies(response)
        return response
