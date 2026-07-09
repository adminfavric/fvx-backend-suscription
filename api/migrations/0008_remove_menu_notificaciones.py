# Quita del menú lateral el ítem "Notificaciones" (se retiró el panel de estado).
# Los avisos por correo siguen corriendo por detrás (Celery); solo se elimina la
# pantalla del admin. Defensivo: nunca rompe el migrate.

from django.db import migrations

ROUTES = ["/notificaciones"]


def remove_items(apps, schema_editor):
    try:
        MenuItem = apps.get_model("api", "MenuItem")
        MenuItem.objects.filter(route__in=ROUTES).delete()
    except Exception:
        pass


def noop(apps, schema_editor):
    # No lo recreamos al revertir: el panel ya no existe en el frontend.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0007_menu_notificaciones"),
    ]

    operations = [migrations.RunPython(remove_items, noop)]
