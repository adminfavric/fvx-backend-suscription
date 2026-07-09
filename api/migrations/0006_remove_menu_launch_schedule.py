# Quita del menú lateral (sección Administración) el ítem "Próximas actividades".
# El bloque del sitio ahora se alimenta solo desde la Programación
# (admin/programacion), así que su editor/menú quedó redundante.
# Mismo patrón defensivo que 0005_menu_launch_schedule: nunca rompe el migrate.

import uuid as uuidlib

from django.db import migrations

# route tal como la sembró 0005 (sin dominio ni /admin; el front antepone /admin).
ITEMS = [
    {
        "name": "Próximas actividades",
        "route": "/proximas-actividades",
        "icon": "event_upcoming",
        "slug": "proximas-actividades",
    },
]


def remove_items(apps, schema_editor):
    try:
        MenuItem = apps.get_model("api", "MenuItem")
        MenuItem.objects.filter(route__in=[i["route"] for i in ITEMS]).delete()
    except Exception:
        # Nunca bloquear el deploy por el menú.
        pass


def add_items(apps, schema_editor):
    """Reverso: vuelve a colgar el ítem de la misma sección que Programación."""
    try:
        MenuItem = apps.get_model("api", "MenuItem")
        anchor = (
            MenuItem.objects.filter(route__icontains="programacion").first()
            or MenuItem.objects.filter(route__icontains="content").first()
            or MenuItem.objects.filter(route__icontains="messages").first()
            or MenuItem.objects.filter(route__icontains="plans").first()
        )
        if not anchor:
            return

        section = anchor.section
        roles = list(anchor.allowed_roles or [])
        last = MenuItem.objects.filter(section=section).order_by("-order").first()
        order = last.order if last else 0

        for spec in ITEMS:
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


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0005_menu_launch_schedule"),
    ]

    operations = [migrations.RunPython(remove_items, add_items)]
