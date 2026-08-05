"""
Tests de regresión del ciclo de vida de suscripciones (Flow y PayPal).

Cubren el bug de agosto 2026: las cancelaciones de PayPal no se reflejaban en el
espejo local (``CheckoutSession``) y el admin mostraba "Activa" mientras el
miembro veía "Inactiva". Tres frentes:

1. El webhook de PayPal debe verificar la firma con las cabeceras tal como las
   entrega Django ("Paypal-Auth-Algo"), y aplicar los eventos de cancelación.
2. Cancelar (miembro o admin) debe marcar la sesión local 'failed' de inmediato.
3. ``sync_subscriptions`` debe reconciliar el espejo local con ambas pasarelas.
"""

import json
from io import StringIO
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse
from rest_framework.test import APIClient

from subscriptions.models import CheckoutSession, PaymentProvider, Plan
from subscriptions.services.paypal import PayPalClient

User = get_user_model()

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _no_ssl_redirect(settings):
    # En producción SECURE_SSL_REDIRECT=True (via .env) convierte todo request de
    # test en un 301 a https; los tests hablan HTTP plano contra el testserver.
    settings.SECURE_SSL_REDIRECT = False


def _plan(slug="oro", **extra):
    return Plan.objects.create(
        name=f"Membresía {slug}", slug=slug, flow_plan_id=f"flow-{slug}",
        amount=30000, **extra,
    )


def _session(plan, *, provider=PaymentProvider.PAYPAL, sub_id="I-TEST123",
             email="cliente@example.com", status=CheckoutSession.Status.SUBSCRIBED):
    return CheckoutSession.objects.create(
        plan=plan, provider=provider, subscription_id=sub_id,
        name="Cliente Test", email=email, status=status,
    )


# ── 1. Webhook PayPal ────────────────────────────────────────────────────────


def test_verify_webhook_accepts_django_header_casing():
    """Regresión: Django entrega 'Paypal-Auth-Algo' (título), no 'PAYPAL-AUTH-ALGO'.
    La verificación debe encontrar las cabeceras igual (antes llegaban None y
    PayPal rechazaba la firma → todos los webhooks devolvían 400)."""
    client = PayPalClient.__new__(PayPalClient)  # sin __init__: no requiere credenciales
    captured = {}

    def fake_request(method, path, json=None, **kw):
        captured.update(json or {})
        return {"verification_status": "SUCCESS"}

    client._request = fake_request
    django_style_headers = {
        "Paypal-Auth-Algo": "SHA256withRSA",
        "Paypal-Cert-Url": "https://api.paypal.com/cert",
        "Paypal-Transmission-Id": "trans-1",
        "Paypal-Transmission-Sig": "sig==",
        "Paypal-Transmission-Time": "2026-08-05T00:00:00Z",
    }
    assert client.verify_webhook(headers=django_style_headers, body="{}", webhook_id="WH-1")
    assert captured["auth_algo"] == "SHA256withRSA"
    assert captured["cert_url"] == "https://api.paypal.com/cert"
    assert captured["transmission_id"] == "trans-1"
    assert captured["transmission_sig"] == "sig=="
    assert captured["transmission_time"] == "2026-08-05T00:00:00Z"


def _post_webhook(client, event):
    return client.post(
        reverse("paypal-webhook"), data=json.dumps(event), content_type="application/json"
    )


def test_webhook_cancelled_marks_session_failed(settings, client):
    settings.PAYPAL_WEBHOOK_ID = ""  # sin verificación de firma en el test
    cs = _session(_plan())
    resp = _post_webhook(client, {
        "event_type": "BILLING.SUBSCRIPTION.CANCELLED",
        "resource": {"id": cs.subscription_id},
    })
    assert resp.status_code == 200
    cs.refresh_from_db()
    assert cs.status == CheckoutSession.Status.FAILED


def test_webhook_activated_creates_missing_session(settings, client):
    """Red de seguridad: si el navegador nunca registró la suscripción, el evento
    ACTIVATED debe crearla server-to-server."""
    settings.PAYPAL_WEBHOOK_ID = ""
    plan = _plan()
    plan.paypal_plan_id = "P-XYZ"
    plan.save(update_fields=["paypal_plan_id"])
    resp = _post_webhook(client, {
        "event_type": "BILLING.SUBSCRIPTION.ACTIVATED",
        "resource": {
            "id": "I-NUEVA",
            "plan_id": "P-XYZ",
            "subscriber": {
                "email_address": "nueva@example.com",
                "name": {"given_name": "Nueva", "surname": "Clienta"},
            },
        },
    })
    assert resp.status_code == 200
    cs = CheckoutSession.objects.get(subscription_id="I-NUEVA")
    assert cs.status == CheckoutSession.Status.SUBSCRIBED
    assert cs.email == "nueva@example.com"
    assert cs.plan == plan


# ── 2. Cancelaciones actualizan el espejo local de inmediato ─────────────────


def test_member_cancel_paypal_marks_local_failed():
    from subscriptions.services import member_auth

    cs = _session(_plan(), email="socia@example.com")
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {member_auth.issue_token('socia@example.com')}")
    with mock.patch("subscriptions.views.get_paypal_client") as gp:
        gp.return_value.cancel_subscription.return_value = {}
        resp = api.post(reverse("member-cancel"), {"subscription_id": cs.subscription_id})
    assert resp.status_code == 200
    cs.refresh_from_db()
    assert cs.status == CheckoutSession.Status.FAILED


def test_admin_cancel_paypal_marks_local_failed():
    cs = _session(_plan())
    admin = User.objects.create_superuser("boss", "boss@example.com", "clave-secreta-1")
    api = APIClient()
    api.force_authenticate(user=admin)
    with mock.patch("subscriptions.views.get_paypal_client") as gp:
        gp.return_value.cancel_subscription.return_value = {}
        resp = api.post(
            reverse("subscriptions-admin-cancel"),
            {"subscription_id": cs.subscription_id, "password": "clave-secreta-1"},
        )
    assert resp.status_code == 200
    cs.refresh_from_db()
    assert cs.status == CheckoutSession.Status.FAILED


def test_member_cancel_flow_keeps_access_until_period_end():
    """Flow cancela al FINAL del período: la sesión local sigue 'subscribed' (el
    acceso vigente lo decide la verificación en vivo); la reconciliación diaria
    la marcará 'failed' cuando Flow reporte que ya no está activa."""
    from subscriptions.services import member_auth

    cs = _session(_plan("flowplan"), provider=PaymentProvider.FLOW, sub_id="sus_1",
                  email="socia@example.com")
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {member_auth.issue_token('socia@example.com')}")
    with mock.patch("subscriptions.views.get_flow_client") as gf:
        gf.return_value.cancel_subscription.return_value = {"status": 1}
        resp = api.post(reverse("member-cancel"), {"subscription_id": "sus_1"})
    assert resp.status_code == 200
    cs.refresh_from_db()
    assert cs.status == CheckoutSession.Status.SUBSCRIBED


# ── 3. Reconciliación diaria (sync_subscriptions) ────────────────────────────


def _run_sync(*args):
    out = StringIO()
    call_command("sync_subscriptions", *args, stdout=out, stderr=out)
    return out.getvalue()


def test_sync_marks_cancelled_paypal_and_flow_as_failed():
    plan = _plan()
    pp_dead = _session(plan, sub_id="I-DEAD")
    pp_alive = _session(plan, sub_id="I-ALIVE", email="viva@example.com")
    fl_dead = _session(plan, provider=PaymentProvider.FLOW, sub_id="sus_dead",
                       email="flow@example.com")
    manual = CheckoutSession.objects.create(  # por período: no se toca nunca
        plan=plan, provider=PaymentProvider.MANUAL, name="Manual", email="m@example.com",
        status=CheckoutSession.Status.SUBSCRIBED,
    )

    paypal_states = {"I-DEAD": "CANCELLED", "I-ALIVE": "ACTIVE"}
    with mock.patch(
        "subscriptions.management.commands.sync_subscriptions.get_paypal_client"
    ) as gp, mock.patch(
        "subscriptions.management.commands.sync_subscriptions.get_flow_client"
    ) as gf:
        gp.return_value.get_subscription.side_effect = lambda sid: {"status": paypal_states[sid]}
        gf.return_value.get_subscription.return_value = {"status": 4}  # cancelada en Flow
        _run_sync()

    pp_dead.refresh_from_db(); pp_alive.refresh_from_db()
    fl_dead.refresh_from_db(); manual.refresh_from_db()
    assert pp_dead.status == CheckoutSession.Status.FAILED
    assert fl_dead.status == CheckoutSession.Status.FAILED
    assert pp_alive.status == CheckoutSession.Status.SUBSCRIBED
    assert manual.status == CheckoutSession.Status.SUBSCRIBED


def test_sync_dry_run_changes_nothing():
    cs = _session(_plan(), sub_id="I-DEAD")
    with mock.patch(
        "subscriptions.management.commands.sync_subscriptions.get_paypal_client"
    ) as gp:
        gp.return_value.get_subscription.return_value = {"status": "CANCELLED"}
        out = _run_sync("--dry-run")
    cs.refresh_from_db()
    assert cs.status == CheckoutSession.Status.SUBSCRIBED
    assert "por corregir" in out
