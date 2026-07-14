# Agrega al menú lateral (sección Administración) el ítem "Usuarios", que abre la
# gestión de credenciales del panel (crear/editar usuarios con email, contraseña y
# rol). Restringido a rol ADMIN (staff igual lo ve). Mismo patrón defensivo que
# 0004/0007: nunca rompe el migrate.

import uuid as uuidlib

from django.db import migrations

NEW_ITEMS = [
    {
        "name": "Usuarios",
        "route": "/usuarios",
        "icon": "manage_accounts",
        "slug": "usuarios",
        "allowed_roles": ["ADMIN"],
    },
]


def add_items(apps, schema_editor):
    try:
        MenuItem = apps.get_model("api", "MenuItem")
        anchor = (
            MenuItem.objects.filter(route__icontains="acceso-cortesia").first()
            or MenuItem.objects.filter(route__icontains="messages").first()
            or MenuItem.objects.filter(route__icontains="programacion").first()
            or MenuItem.objects.filter(route__icontains="plans").first()
        )
        if not anchor:
            return  # menú no sembrado: nada que hacer

        section = anchor.section
        last = MenuItem.objects.filter(section=section).order_by("-order").first()
        order = last.order if last else 0

        for spec in NEW_ITEMS:
            order += 1
            if MenuItem.objects.filter(section=section, route=spec["route"]).exists():
                continue
            slug = spec["slug"]
            n = 1
            while MenuItem.objects.filter(slug=slug).exists():
                n += 1
                slug = f'{spec["slug"]}-{n}'
            MenuItem.objects.create(
                section=section,
                name=spec["name"],
                route=spec["route"],
                icon=spec["icon"],
                order=order,
                allowed_roles=spec["allowed_roles"],
                is_active=True,
                slug=slug,
                uuid=f"MEN-{uuidlib.uuid4()}",
            )
    except Exception:
        pass


def remove_items(apps, schema_editor):
    try:
        MenuItem = apps.get_model("api", "MenuItem")
        MenuItem.objects.filter(route__in=[i["route"] for i in NEW_ITEMS]).delete()
    except Exception:
        pass


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0008_remove_menu_notificaciones"),
    ]

    operations = [migrations.RunPython(add_items, remove_items)]
