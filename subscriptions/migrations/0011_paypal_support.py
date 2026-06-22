"""Soporte de PayPal: campos PayPal en Plan + ``provider`` en CheckoutSession.

PayPal es la alternativa internacional (USD) a Flow (CLP). ``provider`` diferencia
las suscripciones; los campos ``flow_*`` pasan a ser opcionales (vacíos en PayPal).
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0010_lead_is_read_lead_is_replied"),
    ]

    operations = [
        # ── Plan: campos de PayPal ───────────────────────────────────────────
        migrations.AddField(
            model_name="plan",
            name="paypal_enabled",
            field=models.BooleanField(
                default=False,
                help_text="Ofrecer PayPal (USD) como alternativa internacional en este plan.",
                verbose_name="PayPal enabled",
            ),
        ),
        migrations.AddField(
            model_name="plan",
            name="paypal_amount",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="Precio en USD a cobrar por PayPal. Vacío = se convierte automáticamente desde el precio CLP usando PAYPAL_CLP_PER_USD.",
                max_digits=10,
                null=True,
                verbose_name="PayPal amount (USD)",
            ),
        ),
        migrations.AddField(
            model_name="plan",
            name="paypal_currency",
            field=models.CharField(default="USD", max_length=3, verbose_name="PayPal currency"),
        ),
        migrations.AddField(
            model_name="plan",
            name="paypal_product_id",
            field=models.CharField(
                blank=True,
                help_text="Producto de catálogo en PayPal (creado en el primer sync).",
                max_length=120,
                verbose_name="PayPal product id",
            ),
        ),
        migrations.AddField(
            model_name="plan",
            name="paypal_plan_id",
            field=models.CharField(
                blank=True,
                help_text="Billing plan en PayPal (P-…). Creado en el primer sync.",
                max_length=120,
                verbose_name="PayPal plan id",
            ),
        ),
        migrations.AddField(
            model_name="plan",
            name="paypal_synced_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="last synced to PayPal"),
        ),
        migrations.AddField(
            model_name="plan",
            name="paypal_status",
            field=models.CharField(
                blank=True,
                help_text="Estado del billing plan en PayPal: ACTIVE / INACTIVE.",
                max_length=20,
                verbose_name="PayPal status",
            ),
        ),
        migrations.AddField(
            model_name="plan",
            name="paypal_last_sync_error",
            field=models.TextField(blank=True, verbose_name="PayPal last sync error"),
        ),
        # ── CheckoutSession: provider + campos Flow opcionales ───────────────
        migrations.AddField(
            model_name="checkoutsession",
            name="provider",
            field=models.CharField(
                choices=[("flow", "Flow"), ("paypal", "PayPal")],
                db_index=True,
                default="flow",
                help_text="Pasarela que respalda esta suscripción (Flow o PayPal).",
                max_length=20,
                verbose_name="provider",
            ),
        ),
        migrations.AlterField(
            model_name="checkoutsession",
            name="flow_customer_id",
            field=models.CharField(blank=True, max_length=120, verbose_name="Flow customer id"),
        ),
        migrations.AlterField(
            model_name="checkoutsession",
            name="register_token",
            field=models.CharField(
                blank=True, max_length=120, null=True, unique=True, verbose_name="Flow register token"
            ),
        ),
        migrations.AlterField(
            model_name="checkoutsession",
            name="subscription_id",
            field=models.CharField(blank=True, max_length=120, verbose_name="subscription id"),
        ),
    ]
