# -*- coding: utf-8 -*-
"""Seed de las 3 membresías reales de Lita Donoso + sync a Flow. Idempotente."""
from subscriptions.models import Plan
from subscriptions.services import sync_plan_to_flow
from subscriptions.services.flow import FlowError

PLANES = [
    dict(
        name="Membresía Oro", amount=49000, interval=3, featured=True, order=1,
        tagline="Todo incluido · acceso completo",
        cadence="Mensual",
        features=[
            "Escuela Anual de Alkymistas",
            "Taller mensual",
            "Podcast mensual",
            "Alkymia para principiantes",
            "Acceso a la biblioteca",
        ],
        icon="auto_awesome",
    ),
    dict(
        name="Membresía Premium", amount=29000, interval=3, order=2,
        tagline="Todo menos la Escuela Anual",
        cadence="Mensual",
        features=[
            "Taller mensual",
            "Podcast mensual",
            "Alkymia para principiantes",
            "Acceso a la biblioteca",
        ],
        icon="self_improvement",
    ),
    dict(
        name="Membresía Básica", amount=9000, interval=3, order=3,
        tagline="Para comenzar tu camino",
        cadence="Mensual",
        features=["Alkymia para principiantes"],
        icon="spa",
    ),
]

for data in PLANES:
    plan, created = Plan.objects.get_or_create(name=data["name"], defaults=data)
    if not created:
        for k, v in data.items():
            setattr(plan, k, v)
    plan.is_public = True
    plan.is_active = True
    plan.save()
    try:
        sync_plan_to_flow(plan)
        print(f"OK {plan.name} (${plan.amount}) flow_id={plan.flow_plan_id} status={plan.flow_status}")
    except FlowError as e:
        print(f"FLOW ERROR {plan.name}: {e}")
