"""
Bitácora de cancelaciones (``SubscriptionCancellation``): al cancelar una
suscripción recurrente debe quedar registrado QUIÉN lo hizo (miembro / admin /
pasarela), CUÁNDO y si fue al final del período, y la lista admin de
suscripciones debe exponerlo (``?include_inactive=1``).

Caso real (ago-2026): una clienta perdió el acceso porque su suscripción Flow
quedó "cancelada al final del período" y no había forma de saber si la canceló
ella, el equipo o Flow sin entrar al panel de la pasarela.
"""

from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse
from rest_framework.test import APIClient

from subscriptions.models import (
    CheckoutSession,
    PaymentProvider,
    Plan,
    SubscriptionCancellation,
)

User = get_user_model()
pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _no_ssl_redirect(settings):
    settings.SECURE_SSL_REDIRECT = False


def _plan(slug="basica"):
    return Plan.objects.create(name=f"Membresía {slug}", slug=slug, flow_plan_id=f"flow-{slug}", amount=9000)


def _flow_session(plan, sub_id="sus_abc", email="marcela@example.com"):
    return CheckoutSession.objects.create(
        plan=plan, provider=PaymentProvider.FLOW, subscription_id=sub_id,
        flow_customer_id="cus_1", name="Marcela", email=email,
        status=CheckoutSession.Status.SUBSCRIBED,
    )


def test_member_cancel_logs_member_actor():
    from subscriptions.services import member_auth

    cs = _flow_session(_plan())
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {member_auth.issue_token(cs.email)}")
    with mock.patch("subscriptions.views.get_flow_client") as gf:
        gf.return_value.cancel_subscription.return_value = {"status": 4}
        resp = api.post(reverse("member-cancel"), {"subscription_id": cs.subscription_id})
    assert resp.status_code == 200

    log = SubscriptionCancellation.objects.get(subscription_id=cs.subscription_id)
    assert log.actor == SubscriptionCancellation.Actor.MEMBER
    assert log.actor_detail == cs.email
    assert log.at_period_end is True
    assert log.session_id == cs.id


def test_admin_cancel_logs_admin_actor_with_who():
    cs = _flow_session(_plan())
    admin = User.objects.create_superuser("boss", "boss@example.com", "clave-secreta-1")
    api = APIClient()
    api.force_authenticate(user=admin)
    with mock.patch("subscriptions.views.get_flow_client") as gf:
        gf.return_value.cancel_subscription.return_value = {}
        resp = api.post(
            reverse("subscriptions-admin-cancel"),
            {"subscription_id": cs.subscription_id, "password": "clave-secreta-1", "reason": "duplicada"},
        )
    assert resp.status_code == 200

    log = SubscriptionCancellation.objects.get(subscription_id=cs.subscription_id)
    assert log.actor == SubscriptionCancellation.Actor.ADMIN
    assert log.actor_detail == "boss@example.com"
    assert log.reason == "duplicada"


def test_sync_logs_gateway_actor_only_if_nobody_cancelled_here():
    plan = _plan()
    unknown = _flow_session(plan, sub_id="sus_unknown", email="a@example.com")
    known = _flow_session(plan, sub_id="sus_known", email="b@example.com")
    # Esta ya fue cancelada por el miembro desde la plataforma: el sync NO debe
    # sobrescribir la autoría con "pasarela".
    SubscriptionCancellation.log(known, actor=SubscriptionCancellation.Actor.MEMBER, actor_detail="b@example.com")

    with mock.patch(
        "subscriptions.management.commands.sync_subscriptions.get_flow_client"
    ) as gf:
        gf.return_value.get_subscription.return_value = {"status": 4}
        call_command("sync_subscriptions")

    unknown.refresh_from_db(); known.refresh_from_db()
    assert unknown.status == CheckoutSession.Status.FAILED
    assert known.status == CheckoutSession.Status.FAILED
    assert SubscriptionCancellation.objects.get(subscription_id="sus_unknown").actor == SubscriptionCancellation.Actor.GATEWAY
    logs_known = SubscriptionCancellation.objects.filter(subscription_id="sus_known")
    assert logs_known.count() == 1 and logs_known.get().actor == SubscriptionCancellation.Actor.MEMBER


def test_admin_list_exposes_cancellation_and_inactive_rows():
    plan = _plan()
    active = _flow_session(plan, sub_id="sus_live", email="viva@example.com")
    dead = _flow_session(plan, sub_id="sus_dead", email="marcela@example.com")
    dead.status = CheckoutSession.Status.FAILED
    dead.save(update_fields=["status"])
    SubscriptionCancellation.log(dead, actor=SubscriptionCancellation.Actor.MEMBER, actor_detail=dead.email)

    admin = User.objects.create_superuser("boss", "boss@example.com", "x")
    api = APIClient()
    api.force_authenticate(user=admin)

    # Por defecto: solo activas.
    rows = api.get(reverse("subscriptions-all")).json()["data"]
    assert [r["subscription_id"] for r in rows] == ["sus_live"]

    # Con inactivas: aparece la cancelada, con su bitácora.
    rows = api.get(reverse("subscriptions-all"), {"include_inactive": "1"}).json()["data"]
    by_id = {r["subscription_id"]: r for r in rows}
    assert set(by_id) == {"sus_live", "sus_dead"}
    assert by_id["sus_live"]["is_active"] is True and by_id["sus_live"]["cancellation"] is None
    d = by_id["sus_dead"]
    assert d["is_active"] is False and d["status"] == "failed"
    assert d["cancellation"]["actor"] == "member"
    assert d["cancellation"]["actor_detail"] == "marcela@example.com"
    assert d["cancellation"]["at_period_end"] is True
