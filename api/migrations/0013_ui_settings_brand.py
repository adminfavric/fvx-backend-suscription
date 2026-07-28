# El singleton UiSettings tenía app_title="FVX Suscription" (nombre interno del
# template), que se mostraba de cara al cliente (sidebar del panel; antes también
# en la pestaña). Se actualiza a la marca real. Defensiva: nunca rompe el migrate.

from django.db import migrations

OLD = "FVX Suscription"
NEW = "Experiencias Lita Donoso"


def set_brand(apps, schema_editor):
    try:
        UiSettings = apps.get_model("api", "UiSettings")
        # Solo se pisa si sigue con el nombre del template (o vacío); un valor
        # personalizado por el admin se respeta.
        for ui in UiSettings.objects.all():
            if (ui.app_title or "").strip() in ("", OLD):
                ui.app_title = NEW
                ui.save(update_fields=["app_title"])
    except Exception:
        pass


def revert_brand(apps, schema_editor):
    try:
        UiSettings = apps.get_model("api", "UiSettings")
        UiSettings.objects.filter(app_title=NEW).update(app_title=OLD)
    except Exception:
        pass


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0012_user_menu_slugs"),
    ]

    operations = [migrations.RunPython(set_brand, revert_brand)]
