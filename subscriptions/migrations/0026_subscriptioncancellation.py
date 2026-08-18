# Bitácora de cancelaciones: quién (miembro/admin/pasarela), cuándo y cómo se
# canceló cada suscripción recurrente. Ver SubscriptionCancellation en models.py.

import django.db.models.deletion
import django.utils.timezone
import model_utils.fields
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0025_compmembership_expires_at"),
    ]

    operations = [
        migrations.CreateModel(
            name="SubscriptionCancellation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created", model_utils.fields.AutoCreatedField(default=django.utils.timezone.now, editable=False, verbose_name="created")),
                ("modified", model_utils.fields.AutoLastModifiedField(default=django.utils.timezone.now, editable=False, verbose_name="modified")),
                ("subscription_id", models.CharField(db_index=True, max_length=120, verbose_name="subscription id")),
                ("email", models.EmailField(blank=True, max_length=254, verbose_name="email")),
                ("provider", models.CharField(blank=True, max_length=20, verbose_name="provider")),
                ("actor", models.CharField(choices=[("member", "El miembro (Mi suscripción)"), ("admin", "Administrador (panel)"), ("gateway", "Pasarela / reconciliación")], max_length=12, verbose_name="actor")),
                ("actor_detail", models.CharField(blank=True, max_length=255, verbose_name="actor detail")),
                ("at_period_end", models.BooleanField(default=True, verbose_name="at period end")),
                ("reason", models.CharField(blank=True, max_length=255, verbose_name="reason")),
                ("session", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="cancellations", to="subscriptions.checkoutsession")),
            ],
            options={
                "verbose_name": "subscription cancellation",
                "verbose_name_plural": "subscription cancellations",
                "ordering": ["-created"],
            },
        ),
    ]
