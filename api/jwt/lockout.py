"""Respuesta personalizada de ``django-axes`` cuando una cuenta está bloqueada.

Por defecto, axes responde con un template HTML estándar de Django (`403`).
Nuestro frontend espera JSON con `detail` para mostrar el mensaje al usuario,
igual que el resto de los errores de auth.
"""

from django.http import JsonResponse


def lockout_response(request, credentials, *args, **kwargs):
    """Devuelve un 403 con cuerpo JSON describiendo el bloqueo.

    `credentials` puede contener el username intentado; lo omitimos del
    cuerpo a propósito (no queremos exponer "esa cuenta existe y está
    bloqueada" — info útil para enumeración de usuarios).
    """
    return JsonResponse(
        {
            "detail": (
                "Demasiados intentos de inicio de sesión fallidos. "
                "La cuenta está bloqueada temporalmente. "
                "Reintenta en una hora o contacta a un administrador."
            ),
            "code": "account_locked",
        },
        status=403,
    )
