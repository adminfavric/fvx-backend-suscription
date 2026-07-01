# Registra la tarea periódica (Celery beat / DatabaseScheduler) que avisa por
# correo ~30 min antes de cada sesión Zoom. Corre cada 5 minutos; el propio
# servicio decide a qué sesiones les toca aviso y deduplica. Ver
# subscriptions/tasks.py y services/event_reminders.py.

from django.db import migrations

TASK = "subscriptions.tasks.send_live_event_reminders"
NAME = "Aviso de sesiones en vivo (30 min antes)"


def create_schedule(apps, schema_editor):
    try:
        Crontab = apps.get_model("django_celery_beat", "CrontabSchedule")
        Periodic = apps.get_model("django_celery_beat", "PeriodicTask")
    except LookupError:
        return  # django_celery_beat no instalado: nada que hacer

    schedule, _ = Crontab.objects.get_or_create(
        minute="*/5", hour="*", day_of_week="*", day_of_month="*", month_of_year="*",
    )
    Periodic.objects.get_or_create(
        name=NAME,
        defaults={"task": TASK, "crontab": schedule, "enabled": True},
    )


def remove_schedule(apps, schema_editor):
    try:
        Periodic = apps.get_model("django_celery_beat", "PeriodicTask")
    except LookupError:
        return
    Periodic.objects.filter(name=NAME).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0016_expiry_reminders_schedule"),
        ("django_celery_beat", "0001_initial"),
    ]

    operations = [migrations.RunPython(create_schedule, remove_schedule)]
