# Sesión en vivo (Zoom) en ContentItem: número/passcode de la reunión (solo
# servidor) + franja horaria de acceso. Ver subscriptions/models.py y
# services/zoom.py (firma del Meeting SDK).

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0012_paypal_enabled_default_true"),
    ]

    operations = [
        migrations.AddField(
            model_name="contentitem",
            name="zoom_meeting_number",
            field=models.CharField(
                blank=True,
                help_text="ID numérico de la reunión Zoom (Meeting ID, sin espacios). Solo tipo 'zoom'.",
                max_length=64,
                verbose_name="Zoom meeting number",
            ),
        ),
        migrations.AddField(
            model_name="contentitem",
            name="zoom_passcode",
            field=models.CharField(
                blank=True,
                help_text="Clave de la reunión. Se guarda solo en el servidor; el miembro nunca ve el link.",
                max_length=64,
                verbose_name="Zoom passcode",
            ),
        ),
        migrations.AddField(
            model_name="contentitem",
            name="live_start",
            field=models.DateTimeField(
                blank=True,
                help_text="Inicio de la sesión en vivo. El acceso se abre unos minutos antes.",
                null=True,
                verbose_name="live start",
            ),
        ),
        migrations.AddField(
            model_name="contentitem",
            name="live_end",
            field=models.DateTimeField(
                blank=True,
                help_text="Fin de la sesión. Vacío = se usa una duración por defecto desde el inicio.",
                null=True,
                verbose_name="live end",
            ),
        ),
    ]
