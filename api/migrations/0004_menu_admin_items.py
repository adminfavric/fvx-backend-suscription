# Agrega al menú lateral (sección Administración) los ítems "Correos masivos" y
# "Accesos de cortesía". El menú vive en la BD; esta migración lo siembra para que
# aparezcan tras un git pull + migrate (y el guard de rutas permita esas páginas).
#
# Defensiva: si el menú no está sembrado o algo no calza, NO rompe el migrate
# (queda como no-op y el alta se puede hacer a mano por el admin de Django).

import uuid as uuidlib

from django.db import migrations

# route sin dominio ni /admin (el frontend antepone /admin al normalizar).
NEW_ITEMS = [
    {"name": "Correos masivos", "route": "/correos", "icon": "campaign", "slug": "correos-masivos"},
    {"name": "Accesos de cortesía", "route": "/acceso-cortesia", "icon": "vpn_key", "slug": "accesos-de-cortesia"},
]


def add_items(apps, schema_editor):
    try:
        MenuItem = apps.get_model("api", "MenuItem")
        # Ancla: la sección que ya contiene Contenido/Programación/Mensajes
        # (= Administración). Copiamos su ``allowed_roles`` para igual visibilidad.
        anchor = (
            MenuItem.objects.filter(route__icontains="content").first()
            or MenuItem.objects.filter(route__icontains="programacion").first()
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
        # Nunca bloquear el deploy por el menú; se puede agregar por el admin.
        pass


def remove_items(apps, schema_editor):
    try:
        MenuItem = apps.get_model("api", "MenuItem")
        MenuItem.objects.filter(route__in=[i["route"] for i in NEW_ITEMS]).delete()
    except Exception:
        pass


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0003_apikey_expires_at_apikey_scopes"),
    ]

    operations = [migrations.RunPython(add_items, remove_items)]
