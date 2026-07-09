# Agrega a la Programación la casilla "Por confirmar fecha": permite mostrar una
# actividad en "Próximas actividades" como «Fecha por confirmar», sin una fecha
# definitiva y sin que la filtre el corte por fecha futura.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0019_launchschedule"),
    ]

    operations = [
        migrations.AddField(
            model_name="contentschedule",
            name="date_tbd",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Márcalo si la actividad aún no tiene fecha definitiva. En «Próximas "
                    "actividades» aparecerá como «Fecha por confirmar» y se mantendrá "
                    "visible aunque su fecha «Desde» no sea futura. Al confirmar la fecha, "
                    "desmárcalo."
                ),
                verbose_name="por confirmar fecha",
            ),
        ),
    ]
