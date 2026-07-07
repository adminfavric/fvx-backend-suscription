# Bloque de campaña editable (bienvenida + "Próximas actividades"): singleton
# que el admin edita para controlar qué se muestra antes de las membresías.
# Ver subscriptions/models.py (LaunchSchedule).

from django.db import migrations, models
import django.utils.timezone
import model_utils.fields
import subscriptions.models


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0018_compmembership"),
    ]

    operations = [
        migrations.CreateModel(
            name="LaunchSchedule",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                (
                    "enabled",
                    models.BooleanField(
                        default=True,
                        help_text="Mostrar el bloque de bienvenida + próximas actividades en el sitio.",
                        verbose_name="enabled",
                    ),
                ),
                (
                    "intro_title",
                    models.CharField(
                        default="Estamos preparando tu espacio con mucho cariño",
                        max_length=255,
                        verbose_name="intro title",
                    ),
                ),
                (
                    "intro_body",
                    models.TextField(
                        default=(
                            "Este es un espacio donde podrás acceder al nutritivo contenido que estamos "
                            "creando para ti: videos, libros, talleres y nuestros encuentros por Zoom "
                            "dedicados especialmente a nuestra comunidad.\n\n"
                            "Ya tenemos las primeras fechas confirmadas. Si aún no ves nada en tu panel "
                            "de suscripción, ¡no te preocupes! Aquí abajo te compartimos el calendario "
                            "de iniciación."
                        ),
                        help_text="Párrafos de bienvenida. Separa cada párrafo con una línea en blanco.",
                        verbose_name="intro body",
                    ),
                ),
                (
                    "gift_note",
                    models.TextField(
                        blank=True,
                        default=(
                            "Y como agradecimiento por tu confianza y tu espera, quienes se hayan "
                            "registrado antes del 25 de junio recibirán un regalo sorpresa. 🎁"
                        ),
                        help_text="Aviso del regalo (recuadro dorado). Vacío = no se muestra el recuadro.",
                        verbose_name="gift note",
                    ),
                ),
                (
                    "timezone_label",
                    models.CharField(
                        default="Horarios de Chile · GMT-3",
                        max_length=80,
                        verbose_name="timezone label",
                    ),
                ),
                (
                    "heading",
                    models.CharField(
                        default="Próximas actividades",
                        max_length=120,
                        verbose_name="schedule heading",
                    ),
                ),
                (
                    "tiers",
                    models.JSONField(
                        blank=True,
                        default=subscriptions.models.default_launch_tiers,
                        help_text=(
                            'Columnas por nivel. Lista de objetos: '
                            '{"name", "badge", "featured", "items":[{"title", "when"}]}.'
                        ),
                        verbose_name="tiers",
                    ),
                ),
                (
                    "signature",
                    models.CharField(
                        default="Grupo Alkymia",
                        max_length=120,
                        verbose_name="signature",
                    ),
                ),
            ],
            options={
                "verbose_name": "launch schedule",
                "verbose_name_plural": "launch schedule",
            },
        ),
    ]
