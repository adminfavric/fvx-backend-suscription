# Registro permanente de correos salientes enviados desde el panel (masivos,
# individuales y respuestas), con quién los envió. Ver subscriptions/models.py (EmailLog).

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import model_utils.fields


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("subscriptions", "0021_contentschedule_date_mode"),
    ]

    operations = [
        migrations.CreateModel(
            name="EmailLog",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now, editable=False, verbose_name="created"
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now, editable=False, verbose_name="modified"
                    ),
                ),
                ("sender_email", models.EmailField(blank=True, max_length=254, verbose_name="sender email")),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("broadcast", "Masivo"),
                            ("individual", "Individual"),
                            ("reply", "Respuesta"),
                        ],
                        default="broadcast",
                        max_length=12,
                        verbose_name="kind",
                    ),
                ),
                ("subject", models.CharField(blank=True, max_length=255, verbose_name="subject")),
                ("to_email", models.EmailField(blank=True, max_length=254, verbose_name="to email")),
                ("recipients_count", models.PositiveIntegerField(default=0, verbose_name="recipients count")),
                ("note", models.CharField(blank=True, max_length=255, verbose_name="note")),
                (
                    "lead",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="email_logs",
                        to="subscriptions.lead",
                    ),
                ),
                (
                    "sender",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="email_logs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "email log",
                "verbose_name_plural": "email logs",
                "ordering": ["-created"],
            },
        ),
    ]
