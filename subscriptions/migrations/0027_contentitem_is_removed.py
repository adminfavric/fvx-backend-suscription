"""Borrado lógico de las piezas de la biblioteca.

``ContentItem`` pasa a heredar de ``SoftDeletableModel``: eliminar desde el
admin ya no borra la fila, solo marca ``is_removed=True``. Así no se pierden
las programaciones, los recordatorios enviados ni el historial asociado.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0026_subscriptioncancellation"),
    ]

    operations = [
        migrations.AddField(
            model_name="contentitem",
            name="is_removed",
            field=models.BooleanField(default=False),
        ),
        migrations.AddIndex(
            model_name="contentitem",
            index=models.Index(fields=["is_removed"], name="contentitem_is_removed_idx"),
        ),
    ]
