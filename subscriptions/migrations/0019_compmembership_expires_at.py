# Caducidad opcional de los accesos de cortesía: acceso válido hasta
# ``expires_at`` inclusive; vacío = indefinido. Ver CompMembership.plan_ids().

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0018_compmembership"),
    ]

    operations = [
        migrations.AddField(
            model_name="compmembership",
            name="expires_at",
            field=models.DateField(
                blank=True,
                help_text="Acceso válido hasta esta fecha inclusive. Vacío = indefinido.",
                null=True,
                verbose_name="expires at",
            ),
        ),
    ]
