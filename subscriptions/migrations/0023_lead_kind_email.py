# Nuevo tipo de Lead: "email" — respuesta recibida por correo (ingesta IMAP de
# la casilla del admin). Solo amplía los choices (sin cambio de columna real).

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0022_emaillog"),
    ]

    operations = [
        migrations.AlterField(
            model_name="lead",
            name="kind",
            field=models.CharField(
                choices=[
                    ("newsletter", "Newsletter"),
                    ("contact", "Contact"),
                    ("maraton", "Maratón / event"),
                    ("email", "Correo (respuesta)"),
                ],
                default="newsletter",
                max_length=20,
                verbose_name="kind",
            ),
        ),
    ]
