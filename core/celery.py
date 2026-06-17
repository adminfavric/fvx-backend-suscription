"""Celery app del proyecto.

`autodiscover_tasks()` recorre todas las apps en `INSTALLED_APPS` y busca un
módulo `tasks.py` en cada una. Hoy solo `notifications/tasks.py` registra
tasks (`send_email_task`); futuras apps de negocio agregarán las suyas.

Para arrancar:
- Worker:  ``celery -A core worker -l info -Q default,emails``
- Beat:    ``celery -A core beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler``

Ambos comandos viven en `docker-compose.yml` como servicios `celery_worker` y
`celery_beat` que se levantan junto al `web`.
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

app = Celery("fvx_backend")

# Config con prefijo `CELERY_` desde Django settings.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-descubrimiento de tasks por app.
app.autodiscover_tasks()


@app.task(bind=True)
def debug_task(self):
    """Echo de la request — útil para verificar que el worker corre.

    Uso desde shell:
        from core.celery import debug_task
        debug_task.delay()
    """
    print(f"Request: {self.request!r}")
