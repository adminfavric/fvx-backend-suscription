# Agrega al menú lateral (sección Administración) el ítem "Próximas actividades",
# que abre el editor visual del bloque de lanzamiento del sitio público.
# Mismo patrón defensivo que 0004_menu_admin_items: nunca rompe el migrate.

import uuid as uuidlib

from django.db import migrations

# route sin dominio ni /admin (el frontend antepone /admin al normalizar).
NEW_ITEMS = [
    {
        "name": "Próximas actividades",
        "route": "/proximas-actividades",
        "icon": "event_upcoming",
        "slug": "proximas-actividades",
    },
]


def add_items(apps, schema_editor):
    try:
        MenuItem = apps.get_model("api", "MenuItem")
        # Ancla: la sección que ya contiene Programación/Contenido (= Administración).
        anchor = (
            MenuItem.objects.filter(route__icontains="programacion").first()
            or MenuItem.objects.filter(route__icontains="content").first()
            or MenuItem.objects.filter(route__icontains="messages").first()
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
        # Nunca bloquear el deploy por el menú; se puede agregar por el admin de Django.
        pass


def remove_items(apps, schema_editor):
    try:
        MenuItem = apps.get_model("api", "MenuItem")
        MenuItem.objects.filter(route__in=[i["route"] for i in NEW_ITEMS]).delete()
    except Exception:
        pass


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0004_menu_admin_items"),
    ]

    operations = [migrations.RunPython(add_items, remove_items)]
