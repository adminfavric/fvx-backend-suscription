# Registra la tarea periódica (Celery beat) que revisa la casilla del admin por
# IMAP y trae las respuestas de clientas conocidas a Mensajes. Corre cada 5 min.
# Mismo patrón defensivo que 0016/0017: nunca rompe el migrate.

from django.db import migrations

TASK = "subscriptions.tasks.fetch_inbound_replies"
NAME = "Traer respuestas de correo (Gmail → Mensajes)"


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
        ("subscriptions", "0023_lead_kind_email"),
        ("django_celery_beat", "0001_initial"),
    ]

    operations = [migrations.RunPython(create_schedule, remove_schedule)]
