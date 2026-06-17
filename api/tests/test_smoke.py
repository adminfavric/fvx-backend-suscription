"""Smoke tests for the FVX template core: custom user, auth, permissions, menu.

These are intentionally minimal — they assert the load-bearing contracts that
every downstream project relies on, and that the stabilization refactor
(custom User, cookie JWT, soft-delete) didn't break. Not exhaustive coverage.
"""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient

from api.choices import ROLE_ADMIN, ROLE_EDITOR, ROLE_VIEWER
from api.models import ApiKey, Menu, MenuItem, MenuSection
from api.serializers import UploadRequestSerializer

User = get_user_model()

pytestmark = pytest.mark.django_db


def _make_user(username="u1", password="testpass123", **extra):
    return User.objects.create_user(
        username=username, email=f"{username}@example.com", password=password, **extra
    )


# ── Custom user / manager (verifies A.3 soft-delete didn't break auth) ──────


def test_create_superuser_works():
    """The combined UserManager must keep create_superuser intact."""
    su = User.objects.create_superuser("root", "root@example.com", "rootpass123")
    assert su.is_staff and su.is_superuser and su.is_active
    assert su.check_password("rootpass123")
    # Default role still applies.
    assert su.role == ROLE_VIEWER


def test_user_fields_are_flat():
    """Profile was folded into User — fields live directly on the model."""
    u = _make_user(role=ROLE_ADMIN, phone="123", verified=True)
    assert u.role == ROLE_ADMIN
    assert u.phone == "123"
    assert u.verified is True
    assert isinstance(u.ui_preferences, dict)
    assert not hasattr(u, "profile")


def test_soft_delete_hides_from_default_manager():
    """DELETE is soft: objects excludes removed rows, all_objects keeps them."""
    u = _make_user("victim")
    pk = u.pk
    u.delete()
    assert User.objects.filter(pk=pk).count() == 0
    assert User.all_objects.filter(pk=pk).count() == 1
    u.refresh_from_db()
    assert u.is_removed is True


def test_get_by_natural_key_excludes_removed():
    """A soft-removed user cannot be resolved for authentication."""
    u = _make_user("ghost")
    u.delete()
    with pytest.raises(User.DoesNotExist):
        User.objects.get_by_natural_key("ghost")


# ── Auth: cookie JWT (verifies the cookie migration end-to-end) ─────────────


def test_login_sets_httponly_cookies():
    _make_user("alice", "alicepass123")
    client = APIClient()
    resp = client.post(
        "/api/auth/token/", {"username": "alice", "password": "alicepass123"}, format="json"
    )
    assert resp.status_code == 200
    assert "fvx_access" in resp.cookies
    assert resp.cookies["fvx_access"]["httponly"] is True
    # Public, JS-readable expiry cookie used by the SPA (hasSession / timeout).
    assert "fvx_access_exp" in resp.cookies
    assert resp.cookies["fvx_access_exp"]["httponly"] == ""  # not HttpOnly
    # Tokens must NOT leak into the JSON body.
    assert "access" not in resp.json()


def test_login_wrong_password_rejected():
    _make_user("bob", "bobpass123")
    client = APIClient()
    resp = client.post("/api/auth/token/", {"username": "bob", "password": "wrong"}, format="json")
    assert resp.status_code == 401


def test_me_returns_flat_role():
    u = _make_user("carol", role=ROLE_ADMIN)
    client = APIClient()
    client.force_authenticate(user=u)
    resp = client.get("/api/v1/users/me/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["role"] == ROLE_ADMIN
    assert "profile" not in body  # flattened
    assert body["full_name"] == "carol"  # get_full_name() vacío → fallback al username


# ── Permissions: IsAdminOrReadOnly ──────────────────────────────────────────


def test_viewer_can_read_but_not_write_groups():
    viewer = _make_user("viewer", role=ROLE_VIEWER)
    client = APIClient()
    client.force_authenticate(user=viewer)
    assert client.get("/api/v1/groups/").status_code == 200
    assert client.post("/api/v1/groups/", {"name": "g1"}, format="json").status_code == 403


def test_admin_role_can_write_groups():
    admin = _make_user("adminuser", role=ROLE_ADMIN)
    client = APIClient()
    client.force_authenticate(user=admin)
    resp = client.post("/api/v1/groups/", {"name": "g-admin"}, format="json")
    assert resp.status_code == 201
    assert Group.objects.filter(name="g-admin").exists()


# ── Self-protection on UserViewSet ──────────────────────────────────────────


def test_cannot_deactivate_own_account():
    staff = _make_user("selfstaff", is_staff=True)
    client = APIClient()
    client.force_authenticate(user=staff)
    resp = client.patch(f"/api/v1/users/{staff.pk}/", {"is_active": False}, format="json")
    assert resp.status_code == 400
    staff.refresh_from_db()
    assert staff.is_active is True


# ── Menu tree: server-side role filtering + resolution ──────────────────────


def test_nonstaff_admin_cannot_set_role_on_create():
    """A non-staff ADMIN can write users (IsAdminOrReadOnly) but must NOT be
    able to mint privileged roles — perform_create strips ``role``."""
    admin = _make_user("creator", role=ROLE_ADMIN)  # not staff
    client = APIClient()
    client.force_authenticate(user=admin)
    resp = client.post(
        "/api/v1/users/",
        {
            "username": "newbie",
            "email": "newbie@example.com",
            "first_name": "New",
            "last_name": "Bie",
            "password": "Zx9kq-we72LP",
            "role": ROLE_ADMIN,  # attempted escalation
        },
        format="json",
    )
    assert resp.status_code == 201
    created = User.objects.get(username="newbie")
    assert created.role == ROLE_VIEWER  # escalation blocked → default role


def test_nonstaff_admin_cannot_change_others_role():
    admin = _make_user("editor_admin", role=ROLE_ADMIN)
    target = _make_user("target", role=ROLE_VIEWER)
    client = APIClient()
    client.force_authenticate(user=admin)
    resp = client.patch(f"/api/v1/users/{target.pk}/", {"role": ROLE_ADMIN}, format="json")
    assert resp.status_code in (200, 202)
    target.refresh_from_db()
    assert target.role == ROLE_VIEWER  # unchanged


def test_staff_can_set_role():
    staff = _make_user("rootstaff", is_staff=True)
    target = _make_user("target2", role=ROLE_VIEWER)
    client = APIClient()
    client.force_authenticate(user=staff)
    resp = client.patch(f"/api/v1/users/{target.pk}/", {"role": ROLE_EDITOR}, format="json")
    assert resp.status_code in (200, 202)
    target.refresh_from_db()
    assert target.role == ROLE_EDITOR


# ── Upload allow-list (#6) ──────────────────────────────────────────────────


def test_upload_rejects_dangerous_extension():
    f = SimpleUploadedFile("evil.html", b"<script>alert(1)</script>", content_type="text/html")
    ser = UploadRequestSerializer(data={"file": f})
    assert not ser.is_valid()
    assert "file" in ser.errors


def test_upload_rejects_svg():
    f = SimpleUploadedFile("logo.svg", b"<svg onload=alert(1)>", content_type="image/svg+xml")
    ser = UploadRequestSerializer(data={"file": f})
    assert not ser.is_valid()


def test_upload_accepts_allowed_image():
    f = SimpleUploadedFile("pic.png", b"\x89PNG\r\n\x1a\n", content_type="image/png")
    ser = UploadRequestSerializer(data={"file": f})
    assert ser.is_valid(), ser.errors


# ── CSRF on cookie auth (#4) ────────────────────────────────────────────────
# These exercise the REAL cookie path (login → cookies in the jar), unlike the
# force_authenticate tests above which bypass the auth class entirely. The
# client must enforce CSRF (the test client disables it by default).


def test_cookie_mutation_blocked_without_csrf_token():
    _make_user("csrfadmin", password="csrfpass123", role=ROLE_ADMIN)
    client = APIClient(enforce_csrf_checks=True)
    login = client.post(
        "/api/auth/token/",
        {"username": "csrfadmin", "password": "csrfpass123"},
        format="json",
    )
    assert login.status_code == 200
    assert "fvx_access" in client.cookies
    assert "csrftoken" in client.cookies  # double-submit token issued at login
    # Mutation authenticated by the ambient cookie but WITHOUT the X-CSRFToken
    # header → must be rejected (this is the forged-request scenario).
    blocked = client.post("/api/v1/groups/", {"name": "g-nocsrf"}, format="json")
    assert blocked.status_code == 403


def test_cookie_mutation_allowed_with_csrf_token():
    _make_user("csrfadmin2", password="csrfpass123", role=ROLE_ADMIN)
    client = APIClient(enforce_csrf_checks=True)
    client.post(
        "/api/auth/token/",
        {"username": "csrfadmin2", "password": "csrfpass123"},
        format="json",
    )
    token = client.cookies["csrftoken"].value
    ok = client.post(
        "/api/v1/groups/",
        {"name": "g-csrf"},
        format="json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert ok.status_code == 201


def test_safe_get_not_blocked_by_csrf():
    _make_user("csrfget", password="csrfpass123", role=ROLE_VIEWER)
    client = APIClient(enforce_csrf_checks=True)
    client.post(
        "/api/auth/token/",
        {"username": "csrfget", "password": "csrfpass123"},
        format="json",
    )
    # GET is a safe method → never requires a CSRF token even via cookie auth.
    assert client.get("/api/v1/users/me/").status_code == 200


# ── Menu tree: server-side role filtering + resolution ──────────────────────


def test_menu_tree_filters_items_by_role():
    menu = Menu.objects.create(name="Main", is_default=True)
    section = MenuSection.objects.create(menu=menu, name="Admin", order=1)
    MenuItem.objects.create(
        section=section, name="Users", route="/users", order=1, allowed_roles=["ADMIN"]
    )
    MenuItem.objects.create(
        section=section, name="Everyone", route="/dash", order=2, allowed_roles=["VIEWER", "ADMIN"]
    )

    viewer = _make_user("mviewer", role=ROLE_VIEWER)
    client = APIClient()
    client.force_authenticate(user=viewer)
    resp = client.get("/api/v1/menus/tree/")
    assert resp.status_code == 200
    routes = {it["route"] for sec in resp.json().get("sections", []) for it in sec.get("items", [])}
    # VIEWER sees the shared item, never the ADMIN-only one.
    assert "/dash" in routes
    assert "/users" not in routes


def test_menu_tree_cache_invalidates_on_change():
    """The tree is cached, but editing a MenuItem must invalidate it (version
    bump via signal) — a stale menu after an admin edit would be a real bug."""
    menu = Menu.objects.create(name="M", is_default=True)
    section = MenuSection.objects.create(menu=menu, name="S", order=1)
    MenuItem.objects.create(
        section=section, name="A", route="/a", order=1, allowed_roles=["VIEWER"]
    )
    admin = _make_user("cacheadmin", is_staff=True)
    client = APIClient()
    client.force_authenticate(user=admin)

    def routes():
        r = client.get("/api/v1/menus/tree/")
        return {it["route"] for sec in r.json().get("sections", []) for it in sec.get("items", [])}

    assert "/a" in routes()  # first GET populates the cache
    MenuItem.objects.create(
        section=section, name="B", route="/b", order=2, allowed_roles=["VIEWER"]
    )
    assert "/b" in routes()  # cache invalidated → new item appears


# ── API keys: expiry (audit #16) ────────────────────────────────────────────


def test_api_key_authenticates_and_expired_is_rejected():
    u = _make_user("apiuser")
    prefix, secret_hash, full_key = ApiKey.generate_credentials()
    key = ApiKey.objects.create(user=u, prefix=prefix, secret_hash=secret_hash)

    client = APIClient()
    client.credentials(HTTP_X_API_KEY=full_key)

    # Llave válida → autentica como su usuario.
    assert client.get("/api/v1/users/me/").status_code == 200

    # Llave vencida → rechazada (no autentica).
    key.expires_at = timezone.now() - timedelta(minutes=1)
    key.save(update_fields=["expires_at"])
    assert client.get("/api/v1/users/me/").status_code in (401, 403)
