"""Helpers para setear y limpiar las cookies de JWT (access + refresh).

Centralizamos el set/clear de cookies en este módulo para que **todas** las
vistas que emiten tokens (login JWT, login social, refresh) usen los mismos
atributos: `HttpOnly`, `Secure`, `SameSite`, `Domain`, `Path`, `Max-Age`.

Si en el futuro cambia la política (ej. agregar `Domain=.fvx-med.cl` al
desplegar a varios subdominios) se ajusta el `.env` — el código no se toca.
"""

from datetime import datetime, timezone
from typing import Optional

from django.conf import settings
from rest_framework.response import Response


def _max_age_from_token_exp(token_str: str) -> Optional[int]:
    """Calcula max-age en segundos a partir del claim `exp` del token.

    Usar el `exp` real del token (no la duración configurada) garantiza que
    la cookie expira exactamente cuando el token se invalida del lado server.
    """
    try:
        # Importación lazy: evita peso de simplejwt en módulos que solo
        # quieren clear_auth_cookies (logout).
        from rest_framework_simplejwt.tokens import UntypedToken

        token = UntypedToken(token_str)
        exp = token.get("exp")
        if exp is None:
            return None
        now = datetime.now(timezone.utc).timestamp()
        return max(int(exp - now), 0)
    except Exception:
        return None


def set_auth_cookies(
    response: Response,
    access: str,
    refresh: Optional[str] = None,
) -> Response:
    """Setea ``fvx_access``, opcionalmente ``fvx_refresh``, y la cookie de
    expiración (``fvx_access_exp``) que el frontend usa para warning de timeout.
    """
    common = {
        "httponly": True,
        "secure": settings.AUTH_COOKIE_SECURE,
        "samesite": settings.AUTH_COOKIE_SAMESITE,
        "domain": settings.AUTH_COOKIE_DOMAIN,
    }

    access_max_age = _max_age_from_token_exp(access)

    response.set_cookie(
        key=settings.AUTH_COOKIE_ACCESS,
        value=access,
        max_age=access_max_age,
        path=settings.AUTH_COOKIE_PATH_ACCESS,
        **common,
    )

    # Cookie auxiliar (NO HttpOnly) con el timestamp de expiración del access.
    # Permite al SPA mostrar el warning "tu sesión expira en N segundos" sin
    # leer el JWT mismo. Solo expone metadata pública (un epoch en segundos);
    # no es un token y no autentica nada por sí sola.
    if access_max_age is not None:
        import time

        exp_epoch = int(time.time() + access_max_age)
        response.set_cookie(
            key=f"{settings.AUTH_COOKIE_ACCESS}_exp",
            value=str(exp_epoch),
            max_age=access_max_age,
            path=settings.AUTH_COOKIE_PATH_ACCESS,
            httponly=False,  # ← legible desde JS
            secure=settings.AUTH_COOKIE_SECURE,
            samesite=settings.AUTH_COOKIE_SAMESITE,
            domain=settings.AUTH_COOKIE_DOMAIN,
        )

    if refresh is not None:
        response.set_cookie(
            key=settings.AUTH_COOKIE_REFRESH,
            value=refresh,
            max_age=_max_age_from_token_exp(refresh),
            path=settings.AUTH_COOKIE_PATH_REFRESH,
            **common,
        )

    return response


def clear_auth_cookies(response: Response) -> Response:
    """Borra las cookies de auth — usado por el endpoint de logout."""
    # El delete_cookie de Django solo respeta path/domain — el resto de los
    # atributos no afectan el borrado. Aún así pasamos samesite/secure por
    # claridad y compatibilidad con browsers estrictos.
    common = {
        "samesite": settings.AUTH_COOKIE_SAMESITE,
    }
    response.delete_cookie(
        settings.AUTH_COOKIE_ACCESS,
        path=settings.AUTH_COOKIE_PATH_ACCESS,
        domain=settings.AUTH_COOKIE_DOMAIN,
        **common,
    )
    response.delete_cookie(
        f"{settings.AUTH_COOKIE_ACCESS}_exp",
        path=settings.AUTH_COOKIE_PATH_ACCESS,
        domain=settings.AUTH_COOKIE_DOMAIN,
        **common,
    )
    response.delete_cookie(
        settings.AUTH_COOKIE_REFRESH,
        path=settings.AUTH_COOKIE_PATH_REFRESH,
        domain=settings.AUTH_COOKIE_DOMAIN,
        **common,
    )
    return response
