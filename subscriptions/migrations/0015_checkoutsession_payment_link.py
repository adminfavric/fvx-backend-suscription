# Link de pago de Flow en CheckoutSession: meses de acceso que habilita el pago
# y la URL del link generado. Reemplaza la modalidad manual/transferencia por el
# cobro por link de Flow (ver docs/plan-pagos-y-accesos.md, Fase 2).

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0014_checkoutsession_access_period"),
    ]

    operations = [
        migrations.AddField(
            model_name="checkoutsession",
            name="period_months",
            field=models.PositiveIntegerField(
                default=1,
                help_text="Meses de acceso que habilita el pago del link (se suman a access_until al confirmar).",
                verbose_name="period months",
            ),
        ),
        migrations.AddField(
            model_name="checkoutsession",
            name="payment_url",
            field=models.CharField(
                blank=True,
                max_length=600,
                help_text="Link de pago de Flow generado para enviar al cliente.",
                verbose_name="payment URL",
            ),
        ),
    ]
