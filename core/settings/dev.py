"""Settings de DESARROLLO local.

Hereda todo de `base`. El comportamiento dev ya está gobernado por `DEBUG`
(default True vía `DJANGO_DEBUG`) dentro de `base`, así que este overlay es
delgado: existe para nombrar el entorno explícitamente y como punto de extensión
si dev necesita algo que prod no (p. ej. django-debug-toolbar a futuro).
"""

from .base import *  # noqa: F401,F403
