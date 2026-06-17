"""Settings de PRODUCCIÓN.

Hereda de `base`. El grueso del hardening ya lo aplica `base` cuando `DEBUG` es
False (`SECURE_SSL_REDIRECT`, HSTS, cookies seguras, etc.). Este overlay:
  · Garantiza `DEBUG = False` aunque el `.env` lo deje en True por error.
  · Reafirma el hardening de forma EXPLÍCITA e idempotente (no depende de que el
    `.env` tenga `DJANGO_DEBUG=False` para que aplique).

Activar con `DJANGO_ENV=prod` (ver core/settings/__init__.py).
"""

from .base import *  # noqa: F401,F403

# En producción DEBUG SIEMPRE False, pase lo que pase en el .env.
DEBUG = False

# Hardening explícito (espejo del bloque `if not DEBUG` de base; idempotente).
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
CORS_ALLOW_ALL_ORIGINS = False
