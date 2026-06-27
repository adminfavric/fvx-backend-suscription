# Acceso por período en CheckoutSession: proveedores manuales/importados/pago
# único + fecha de vencimiento (access_until) y nota de origen. Base de la Fase 1
# del plan de pagos (ver docs/plan-pagos-y-accesos.md).

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0013_contentitem_zoom_live"),
    ]

    operations = [
        migrations.AddField(
            model_name="checkoutsession",
            name="access_until",
            field=models.DateField(
                blank=True,
                null=True,
                help_text="Acceso válido hasta esta fecha (membresías por período: manual/transferencia/importado).",
                verbose_name="access until",
            ),
        ),
        migrations.AddField(
            model_name="checkoutsession",
            name="origin_note",
            field=models.CharField(
                blank=True,
                max_length=255,
                help_text="De dónde viene el alta o referencia del pago (transferencia, comprobante, plataforma origen).",
                verbose_name="origin / note",
            ),
        ),
        migrations.AlterField(
            model_name="checkoutsession",
            name="provider",
            field=models.CharField(
                choices=[
                    ("flow", "Flow (tarjeta, recurrente)"),
                    ("paypal", "PayPal (recurrente)"),
                    ("manual", "Manual / transferencia"),
                    ("imported", "Importado"),
                    ("flow_mensual", "Flow mensual (pago único)"),
                ],
                db_index=True,
                default="flow",
                help_text="Pasarela que respalda esta suscripción (Flow o PayPal).",
                max_length=20,
                verbose_name="provider",
            ),
        ),
    ]
