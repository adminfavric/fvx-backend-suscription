"""Datos de demostración para revisar los listados de Contenido y Programación.

Uso local:  python manage.py shell < seed_demo_content.py

Crea un superusuario de prueba, tres membresías y un puñado de piezas de todos
los tipos, algunas programadas en varias membresías, otra sin programar y una
con el rango ya vencido. NO se usa en producción.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from subscriptions.models import ContentItem, ContentSchedule, Plan

User = get_user_model()
today = timezone.localdate()

if not User.objects.filter(username="admin").exists():
    User.objects.create_superuser(username="admin", email="admin@favric.cl", password="admin1234")

planes = {}
for slug, name, order in [("basica", "Básica", 1), ("oro", "Oro", 2), ("premium", "Premium", 3)]:
    planes[slug], _ = Plan.objects.get_or_create(
        slug=slug,
        defaults={"name": name, "flow_plan_id": f"flow-{slug}", "amount": 9900 * order, "order": order},
    )

PORTADA = "https://picsum.photos/seed/{}/200/200"

piezas = [
    # (título, tipo, planes, desde, hasta, portada)
    ("Meditación guiada de la mañana", "audio", ["basica", "oro", "premium"], -30, None, True),
    ("Taller: el mapa del alma", "zoom", ["oro", "premium"], 12, 12, True),
    ("Cuaderno de trabajo — módulo 1", "pdf", ["oro"], -10, 60, True),
    ("Clase grabada: la sombra", "video", ["premium"], -5, None, False),
    ("Carta de bienvenida", "text", ["basica"], -90, -30, True),
    ("Mandala del mes", "image", ["oro", "premium"], -2, 28, True),
    ("Playlist recomendada", "link", ["basica", "oro"], 3, None, False),
    ("Sesión de octubre (sin programar)", "zoom", [], None, None, True),
]

for i, (titulo, kind, slugs, desde, hasta, con_portada) in enumerate(piezas):
    item, _ = ContentItem.objects.get_or_create(
        title=titulo,
        defaults={
            "kind": kind,
            "order": i,
            "image_url": PORTADA.format(i + 1) if con_portada else "",
            "text": "Contenido de demostración.",
        },
    )
    for slug in slugs:
        ContentSchedule.objects.get_or_create(
            content=item,
            plan=planes[slug],
            defaults={
                "starts_at": today + timedelta(days=desde or 0),
                "ends_at": today + timedelta(days=hasta) if hasta is not None else None,
                "date_mode": "tbd" if kind == "zoom" else "date",
            },
        )

print(f"OK — {ContentItem.objects.count()} piezas, {ContentSchedule.objects.count()} programaciones")
