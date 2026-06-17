"""Selector de settings por entorno.

`DJANGO_SETTINGS_MODULE` sigue apuntando a `core.settings` (manage.py, wsgi/asgi,
compose, pytest.ini — sin cambios). Este `__init__` reexporta el módulo del
entorno activo, elegido por la variable `DJANGO_ENV`:

  · `dev`  (default) → core.settings.dev   — desarrollo local.
  · `prod`           → core.settings.prod  — producción (hardening explícito).
  · `test`           → core.settings.test  — tests (DB rápida, email en memoria).

Ejemplos:
  DJANGO_ENV=prod gunicorn core.wsgi   ·   DJANGO_ENV=test pytest
"""

import os

_ENV = os.environ.get("DJANGO_ENV", "dev").strip().lower()

if _ENV == "prod":
    from .prod import *  # noqa: F401,F403
elif _ENV == "test":
    from .test import *  # noqa: F401,F403
else:
    from .dev import *  # noqa: F401,F403
