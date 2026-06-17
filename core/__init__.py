"""Bootstrap del proyecto: expone la app Celery al arrancar Django.

Sin este import, los workers Celery no encuentran la app cuando hacen
``-A core``, y el autodiscover de tasks no corre.
"""

from .celery import app as celery_app

__all__ = ("celery_app",)
