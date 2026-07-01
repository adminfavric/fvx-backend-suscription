# Acceso de cortesía / staff (CompMembership): un correo que ve el contenido de
# las membresías sin una suscripción real. Ver subscriptions/models.py.

from django.db import migrations, models
import django.utils.timezone
import model_utils.fields


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0017_live_event_reminders_schedule"),
    ]

    operations = [
        migrations.CreateModel(
            name="CompMembership",
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
                ("email", models.EmailField(max_length=254, unique=True, verbose_name="email")),
                ("full_name", models.CharField(blank=True, max_length=255, verbose_name="full name")),
                (
                    "all_plans",
                    models.BooleanField(
                        default=True,
                        help_text="Acceso a TODAS las membresías activas. Desmárcalo para limitar a planes concretos.",
                        verbose_name="all plans",
                    ),
                ),
                ("is_active", models.BooleanField(default=True, verbose_name="active")),
                ("note", models.CharField(blank=True, max_length=255, verbose_name="note")),
                (
                    "plans",
                    models.ManyToManyField(
                        blank=True,
                        help_text="Si 'all plans' está desmarcado, solo estas membresías.",
                        related_name="comp_members",
                        to="subscriptions.plan",
                    ),
                ),
            ],
            options={
                "verbose_name": "complimentary access",
                "verbose_name_plural": "complimentary access",
                "ordering": ["email"],
            },
        ),
    ]
