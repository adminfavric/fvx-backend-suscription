# Reemplaza el booleano `date_tbd` por `date_mode` (3 estados) en la Programación:
# "date" (mostrar fecha), "tbd" (Por confirmar) y "available" (Material disponible).
# Conserva lo ya marcado: date_tbd=True → date_mode="tbd".

from django.db import migrations, models


def tbd_to_mode(apps, schema_editor):
    ContentSchedule = apps.get_model("subscriptions", "ContentSchedule")
    ContentSchedule.objects.filter(date_tbd=True).update(date_mode="tbd")


def mode_to_tbd(apps, schema_editor):
    ContentSchedule = apps.get_model("subscriptions", "ContentSchedule")
    ContentSchedule.objects.filter(date_mode="tbd").update(date_tbd=True)


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0020_contentschedule_date_tbd"),
    ]

    operations = [
        migrations.AddField(
            model_name="contentschedule",
            name="date_mode",
            field=models.CharField(
                choices=[
                    ("date", "Mostrar fecha"),
                    ("tbd", "Por confirmar"),
                    ("available", "Material disponible"),
                ],
                default="date",
                help_text=(
                    "Cómo aparece en «Próximas actividades»: «Mostrar fecha» usa la fecha "
                    "real (o la hora de la sesión en vivo) y desaparece al pasar; «Por "
                    "confirmar» la muestra siempre como «Fecha por confirmar»; «Material "
                    "disponible» la muestra siempre como «Material disponible» (contenido "
                    "sin fecha, ya disponible)."
                ),
                max_length=12,
                verbose_name="mostrar fecha",
            ),
        ),
        migrations.RunPython(tbd_to_mode, mode_to_tbd),
        migrations.RemoveField(
            model_name="contentschedule",
            name="date_tbd",
        ),
    ]
