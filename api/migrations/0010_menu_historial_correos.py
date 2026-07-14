# Agrega al menú lateral (sección Administración) el ítem "Historial de correos",
# que abre el registro de auditoría de correos salientes (quién envió qué).
# Mismo patrón defensivo que 0004/0007/0009: nunca rompe el migrate.

import uuid as uuidlib

from django.db import migrations

NEW_ITEMS = [
    {
        "name": "Historial de correos",
        "route": "/historial-correos",
        "icon": "outgoing_mail",
        "slug": "historial-correos",
    },
]


def add_items(apps, schema_editor):
    try:
        MenuItem = apps.get_model("api", "MenuItem")
        anchor = (
            MenuItem.objects.filter(route__icontains="correos").first()
            or MenuItem.objects.filter(route__icontains="messages").first()
            or MenuItem.objects.filter(route__icontains="programacion").first()
            or MenuItem.objects.filter(route__icontains="plans").first()
        )
        if not anchor:
            return  # menú no sembrado: nada que hacer

        section = anchor.section
        roles = list(anchor.allowed_roles or [])
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
                allowed_roles=roles,
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
        ("api", "0009_menu_usuarios"),
    ]

    operations = [migrations.RunPython(add_items, remove_items)]
