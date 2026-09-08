"""
Biblioteca de contenido y Programación desde el panel admin.

Cubre lo que el listado promete a la clienta:

* **Eliminar no borra.** ``ContentItem`` es de borrado lógico: la fila
  sobrevive, desaparece de la biblioteca y arrastra sus programaciones fuera de
  la vista (la CASCADE de la FK NO se dispara con el borrado lógico, así que si
  esto se rompe quedan filas huérfanas visibles apuntando a un contenido que ya
  no existe para nadie).
* **La columna "Membresías"** sale del backend ya sin repetir y ordenada.
* **Los filtros y el ordenamiento** de ambas tablas: por membresía en la
  biblioteca; por tipo, y ordenando por título de contenido, en la programación.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient

from subscriptions.models import ContentItem, ContentSchedule, Plan

User = get_user_model()
pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _no_ssl_redirect(settings):
    settings.SECURE_SSL_REDIRECT = False


@pytest.fixture()
def admin_api():
    user = User.objects.create_superuser(username="lita", email="lita@example.com", password="x")
    api = APIClient()
    api.force_authenticate(user=user)
    return api


def _plan(slug, name):
    return Plan.objects.create(name=name, slug=slug, flow_plan_id=f"flow-{slug}", amount=9000)


def _item(title, kind=ContentItem.Kind.VIDEO, order=0):
    return ContentItem.objects.create(title=title, kind=kind, order=order)


def _results(resp):
    return resp.json()["results"]


# ── Borrado lógico ────────────────────────────────────────────────────────

def test_delete_marks_as_removed_instead_of_deleting_the_row(admin_api):
    item = _item("Meditación de la mañana")

    resp = admin_api.delete(reverse("content-item-detail", args=[item.id]))
    assert resp.status_code == 204

    # La fila sigue ahí, solo marcada.
    item.refresh_from_db()
    assert item.is_removed is True
    assert ContentItem.all_objects.filter(id=item.id).exists()
    # Y ya no la ve nadie a través del manager por defecto.
    assert not ContentItem.objects.filter(id=item.id).exists()
    assert _results(admin_api.get(reverse("content-item-list"))) == []


def test_removing_content_hides_its_schedules(admin_api):
    """La CASCADE no corre con el borrado lógico: la programación de una pieza
    borrada NO puede seguir apareciendo en el listado."""
    item = _item("Taller de octubre")
    ContentSchedule.objects.create(content=item, plan=_plan("oro", "Oro"))
    assert len(_results(admin_api.get(reverse("content-schedule-list")))) == 1

    admin_api.delete(reverse("content-item-detail", args=[item.id]))

    assert _results(admin_api.get(reverse("content-schedule-list"))) == []
    # La fila de programación no se perdió: vuelve si se recupera el contenido.
    assert ContentSchedule.objects.filter(content_id=item.id).exists()


# ── Columna "Membresías" ──────────────────────────────────────────────────

def test_plan_names_are_deduplicated_and_sorted(admin_api):
    item = _item("Audio de bienvenida", kind=ContentItem.Kind.AUDIO)
    ContentSchedule.objects.create(content=item, plan=_plan("premium", "Premium"))
    ContentSchedule.objects.create(content=item, plan=_plan("oro", "Oro"))

    row = _results(admin_api.get(reverse("content-item-list")))[0]
    assert row["plan_names"] == ["Oro", "Premium"]


def test_content_without_schedule_has_no_plan_names(admin_api):
    _item("PDF suelto", kind=ContentItem.Kind.PDF)

    row = _results(admin_api.get(reverse("content-item-list")))[0]
    assert row["plan_names"] == []


# ── Filtros y ordenamiento ────────────────────────────────────────────────

def test_library_filters_by_membership(admin_api):
    oro, premium = _plan("oro", "Oro"), _plan("premium", "Premium")
    en_oro, en_premium = _item("Sólo Oro"), _item("Sólo Premium")
    ContentSchedule.objects.create(content=en_oro, plan=oro)
    ContentSchedule.objects.create(content=en_premium, plan=premium)

    resp = admin_api.get(reverse("content-item-list"), {"schedules__plan": oro.id})
    assert [r["title"] for r in _results(resp)] == ["Sólo Oro"]


def test_schedules_filter_by_content_kind(admin_api):
    plan = _plan("oro", "Oro")
    ContentSchedule.objects.create(content=_item("Sesión en vivo", ContentItem.Kind.ZOOM), plan=plan)
    ContentSchedule.objects.create(content=_item("Clase grabada", ContentItem.Kind.VIDEO), plan=plan)

    resp = admin_api.get(reverse("content-schedule-list"), {"content__kind": "zoom"})
    assert [r["content_title"] for r in _results(resp)] == ["Sesión en vivo"]


def test_schedules_order_by_content_title(admin_api):
    plan = _plan("oro", "Oro")
    for title in ("Zapatos", "Abrigo", "Manta"):
        ContentSchedule.objects.create(content=_item(title), plan=plan)

    resp = admin_api.get(reverse("content-schedule-list"), {"ordering": "content_title"})
    assert [r["content_title"] for r in _results(resp)] == ["Abrigo", "Manta", "Zapatos"]

    resp = admin_api.get(reverse("content-schedule-list"), {"ordering": "-content_title"})
    assert [r["content_title"] for r in _results(resp)] == ["Zapatos", "Manta", "Abrigo"]
