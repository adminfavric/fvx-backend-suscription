# Registra la tarea periódica (Celery beat / DatabaseScheduler) que envía los
# recordatorios de vencimiento de membresías por período, a diario ~09:00 Chile
# (13:00 UTC). Ver subscriptions/tasks.py y services/reminders.py.

from django.db import migrations

TASK = "subscriptions.tasks.send_expiry_reminders"
NAME = "Recordatorios de vencimiento de membresías"


def create_schedule(apps, schema_editor):
    try:
        Crontab = apps.get_model("django_celery_beat", "CrontabSchedule")
        Periodic = apps.get_model("django_celery_beat", "PeriodicTask")
    except LookupError:
        return  # django_celery_beat no instalado: nada que hacer

    schedule, _ = Crontab.objects.get_or_create(
        minute="0", hour="13", day_of_week="*", day_of_month="*", month_of_year="*",
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
        ("subscriptions", "0015_checkoutsession_payment_link"),
        ("django_celery_beat", "0001_initial"),
    ]

    operations = [migrations.RunPython(create_schedule, remove_schedule)]
