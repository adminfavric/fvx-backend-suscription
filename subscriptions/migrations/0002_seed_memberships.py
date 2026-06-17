"""Seed the public membership cards as draft Plan rows.

Mirrors the former hardcoded ``catalog.ts`` so the public site can read them
from the backend. Seeded as drafts (``amount=None`` → 'Valor por confirmar');
set a price in the admin to publish each one to Flow. Idempotent on ``slug``.
"""

import uuid as uuid_lib

from django.db import migrations

MEMBERSHIPS = [
    {
        "slug": "escuela-de-alkymistas",
        "name": "Escuela de Alkymistas",
        "tagline": "Sesión mensual · curso anual",
        "description": (
            "Un espacio destinado a la auto maestría y el avance personal, en base al "
            "estudio y prácticas de enseñanzas que combinan textos de grandes maestros "
            "(Ramtha y María Magdalena, entre otros) con el Método Alkymia Solar, creado "
            "por Lita Donoso."
        ),
        "cadence": "Sesión mensual (curso anual)",
        "recorded": False,
        "features": [
            "Sesión en vivo cada mes",
            "Programa anual de auto maestría",
            "Estudio guiado de grandes maestros",
            "Prácticas del Método Alkymia Solar",
        ],
        "icon": "auto_awesome",
        "featured": True,
    },
    {
        "slug": "psicologia-transpersonal",
        "name": "Taller de Psicología Transpersonal",
        "tagline": "Uno por mes · online en vivo · queda grabado",
        "description": (
            "Talleres enfocados en la auto observación y la auto sanación, potenciales del "
            "ser humano que se activan con el Método Alkymia. Cada tema se desarrolla con "
            "una parte teórica y una parte experiencial, en base a ejercicios creados por "
            "la autora para cada módulo, de alto impacto transformacional."
        ),
        "cadence": "Un taller por mes (online en vivo)",
        "recorded": True,
        "features": [
            "Estreno de un taller cada mes",
            "Presencial online en vivo",
            "Parte teórica + parte experiencial",
            "Queda grabado para volver a verlo",
        ],
        "icon": "self_improvement",
        "featured": False,
    },
    {
        "slug": "podcast-encuentro-alkymistas",
        "name": "Podcast Encuentro de Alkymistas",
        "tagline": "Una vez por mes · queda grabado",
        "description": (
            "Encuentros donde se desarrollan temas de interés para las mentes pensantes de "
            "los Alkymistas: contenidos que no son tratados en los medios convencionales o "
            "que no tienen la difusión que merecen. Son interactivos: los participantes "
            "pueden compartir sus comentarios."
        ),
        "cadence": "Un encuentro por mes",
        "recorded": True,
        "features": [
            "Un encuentro en vivo al mes",
            "Temas fuera de los medios convencionales",
            "Espacio interactivo y participativo",
            "Queda grabado",
        ],
        "icon": "podcasts",
        "featured": False,
    },
    {
        "slug": "metodo-alkymia-paso-a-paso",
        "name": "Método Alkymia paso a paso",
        "tagline": "Un módulo por mes",
        "description": (
            'Contenidos que permiten a la persona transformarse en Alkymista Solar. Están '
            'basados en el libro de la autora "Alquimia para los tiempos que corren" '
            "(Editorial PRH). Cada módulo incluye un resumen de la maestría correspondiente "
            "más un audio de ejercicios para cada sesión."
        ),
        "cadence": "Un módulo nuevo por mes",
        "recorded": True,
        "features": [
            "Un módulo nuevo cada mes",
            'Basado en el libro "Alquimia para los tiempos que corren"',
            "Resumen de cada maestría",
            "Audios de ejercicios por sesión",
        ],
        "icon": "menu_book",
        "featured": False,
    },
]


def seed(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")
    for order, m in enumerate(MEMBERSHIPS):
        Plan.objects.get_or_create(
            slug=m["slug"],
            defaults={
                "uuid": f"PLN-{uuid_lib.uuid4()}",
                "flow_plan_id": m["slug"],
                "name": m["name"],
                "tagline": m["tagline"],
                "description": m["description"],
                "cadence": m["cadence"],
                "recorded": m["recorded"],
                "features": m["features"],
                "icon": m["icon"],
                "featured": m["featured"],
                "is_public": True,
                "is_active": True,
                "order": order,
                "interval": 3,  # monthly
                "currency": "CLP",
                "amount": None,  # draft → "Valor por confirmar"
            },
        )


def unseed(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "Plan")
    Plan.objects.filter(slug__in=[m["slug"] for m in MEMBERSHIPS]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
