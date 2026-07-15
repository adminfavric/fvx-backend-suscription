# El ítem "Historial de correos" quedó con el icono `outgoing_mail`, que no existe
# en la fuente "Material Icons Outlined" (por eso solo se veía al seleccionarlo).
# Se cambia a `history`, que sí renderiza en ambos estados.

from django.db import migrations


def set_icon(apps, schema_editor):
    try:
        MenuItem = apps.get_model("api", "MenuItem")
        MenuItem.objects.filter(route="/historial-correos").update(icon="history")
    except Exception:
        pass


def revert_icon(apps, schema_editor):
    try:
        MenuItem = apps.get_model("api", "MenuItem")
        MenuItem.objects.filter(route="/historial-correos").update(icon="outgoing_mail")
    except Exception:
        pass


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0010_menu_historial_correos"),
    ]

    operations = [migrations.RunPython(set_icon, revert_icon)]
