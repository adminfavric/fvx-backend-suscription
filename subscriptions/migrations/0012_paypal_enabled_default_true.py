"""PayPal activado por defecto en todos los planes (todas las membresías deben
poder pagarse con PayPal en USD, convertido desde CLP)."""

from django.db import migrations, models


def enable_paypal_on_existing(apps, schema_editor):
    """Activa PayPal en los planes ya existentes (la sincronización a PayPal —
    crear el billing plan — se hace por separado al guardar/sincronizar)."""
    Plan = apps.get_model("subscriptions", "Plan")
    Plan.objects.update(paypal_enabled=True)


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0011_paypal_support"),
    ]

    operations = [
        migrations.AlterField(
            model_name="plan",
            name="paypal_enabled",
            field=models.BooleanField(
                default=True,
                help_text="Ofrecer PayPal (USD) como alternativa internacional en este plan.",
                verbose_name="PayPal enabled",
            ),
        ),
        migrations.RunPython(enable_paypal_on_existing, migrations.RunPython.noop),
    ]
