"""Settings de TESTS (pytest).

Hereda de `base` con DEBUG activo (como dev) y acelera lo típico de tests:
hasher de password rápido y email en memoria. El `conftest.py` además fuerza
cache locmem y desactiva Axes por test (mantiene los tests herméticos sin Redis).

Se activa con `DJANGO_ENV=test` (ver pytest.ini).
"""

from .base import *  # noqa: F401,F403

# Hasher rápido: los tests crean muchos usuarios; MD5 evita el costo de PBKDF2.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Emails a memoria: no tocar SMTP/Mailpit ni consola durante los tests.
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
NOTIFICATIONS_EMAIL_ADAPTER = "console"
