"""Verificación de id_token (Google, Apple, Microsoft) y obtención/creación de User."""

from __future__ import annotations

import re
from typing import Any

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Q
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from jwt import PyJWKClient

from api.models import SocialAccount

User = get_user_model()

APPLE_ISSUER = "https://appleid.apple.com"
APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"

_jwk_client_apple: PyJWKClient | None = None
_jwk_client_microsoft: PyJWKClient | None = None


def _apple_jwk_client() -> PyJWKClient:
    global _jwk_client_apple
    if _jwk_client_apple is None:
        _jwk_client_apple = PyJWKClient(APPLE_JWKS_URL)
    return _jwk_client_apple


def _microsoft_tenant() -> str:
    """
    Tenant de Entra ID. ``common`` permite cuentas de cualquier organización +
    personales; un GUID/dominio concreto restringe a ese tenant. El issuer y el
    JWKS dependen de este valor, así que debe coincidir con el del id_token.
    """
    return (settings.MICROSOFT_OAUTH_TENANT_ID or "common").strip()


def _microsoft_jwk_client() -> PyJWKClient:
    global _jwk_client_microsoft
    if _jwk_client_microsoft is None:
        tenant = _microsoft_tenant()
        _jwk_client_microsoft = PyJWKClient(
            f"https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys"
        )
    return _jwk_client_microsoft


def verify_google_id_token(raw: str) -> dict[str, Any]:
    if not settings.GOOGLE_OAUTH_CLIENT_ID:
        raise ValueError("GOOGLE_OAUTH_CLIENT_ID is not configured")
    return google_id_token.verify_oauth2_token(
        raw,
        google_requests.Request(),
        settings.GOOGLE_OAUTH_CLIENT_ID,
    )


def verify_apple_id_token(raw: str) -> dict[str, Any]:
    if not settings.APPLE_CLIENT_ID:
        raise ValueError("APPLE_CLIENT_ID is not configured")
    client = _apple_jwk_client()
    key = client.get_signing_key_from_jwt(raw)
    return jwt.decode(
        raw,
        key.key,
        algorithms=["RS256"],
        audience=settings.APPLE_CLIENT_ID,
        issuer=APPLE_ISSUER,
    )


_MICROSOFT_MULTI_TENANT = {"common", "organizations", "consumers"}


def verify_microsoft_id_token(raw: str) -> dict[str, Any]:
    """
    Verifica un id_token de Microsoft Entra ID (OIDC v2.0).

    Igual que Apple, es un JWT RS256 validado contra el JWKS del proveedor. La
    diferencia está en el ``iss``: con un tenant concreto (GUID/dominio) el issuer
    es estable y se valida por igualdad; con multi-tenant (``common`` /
    ``organizations`` / ``consumers``) cada usuario trae el GUID de SU tenant en
    el ``iss``, así que ahí solo se valida el patrón (host + sufijo ``/v2.0``).
    """
    if not settings.MICROSOFT_OAUTH_CLIENT_ID:
        raise ValueError("MICROSOFT_OAUTH_CLIENT_ID is not configured")
    client = _microsoft_jwk_client()
    key = client.get_signing_key_from_jwt(raw)
    tenant = _microsoft_tenant()

    decode_kwargs: dict[str, Any] = {
        "algorithms": ["RS256"],
        "audience": settings.MICROSOFT_OAUTH_CLIENT_ID,
    }
    if tenant.lower() in _MICROSOFT_MULTI_TENANT:
        # El issuer trae el GUID del tenant del usuario → no se puede fijar; lo
        # validamos manualmente tras decodificar.
        decode_kwargs["options"] = {"verify_iss": False}
    else:
        decode_kwargs["issuer"] = f"https://login.microsoftonline.com/{tenant}/v2.0"

    claims = jwt.decode(raw, key.key, **decode_kwargs)

    if tenant.lower() in _MICROSOFT_MULTI_TENANT:
        iss = str(claims.get("iss", ""))
        if not (iss.startswith("https://login.microsoftonline.com/") and iss.endswith("/v2.0")):
            raise ValueError("Microsoft token issuer is not trusted.")

    return claims


def _normalize_email(email: str | None) -> str | None:
    if not email or not str(email).strip():
        return None
    return str(email).strip().lower()


def _find_user_for_social_email(email_norm: str) -> User | None:
    """Usuario existente por ``email`` o por ``username`` igual al correo (login típico)."""
    return User.objects.filter(Q(email__iexact=email_norm) | Q(username__iexact=email_norm)).first()


def _ensure_social_link(
    user: User,
    *,
    provider: str,
    uid: str,
    email_norm: str,
) -> None:
    """
    Garantiza una sola fila por (user, provider). Evita insertar otra si ya existe
    (p. ej. ``sub`` distinto al guardado, o carrera entre peticiones).
    """
    row = SocialAccount.objects.filter(user=user, provider__iexact=provider).first()
    if row:
        if row.uid != uid:
            conflict = (
                SocialAccount.objects.filter(provider__iexact=provider, uid=uid)
                .exclude(pk=row.pk)
                .first()
            )
            if conflict:
                raise ValueError("social_uid_conflict")
            row.uid = uid
        row.email = email_norm
        row.save(update_fields=["uid", "email", "modified"])
        return

    taken = SocialAccount.objects.filter(provider__iexact=provider, uid=uid).first()
    if taken:
        if taken.user_id != user.pk:
            raise ValueError("social_uid_linked_other_user")
        return

    try:
        # Con ATOMIC_REQUESTS=True el INSERT debe estar en su propio atomic;
        # si falla, el except ejecuta queries tras rollback del savepoint.
        with transaction.atomic():
            SocialAccount.objects.create(
                user=user,
                provider=provider,
                uid=uid,
                email=email_norm,
            )
    except IntegrityError:
        row = SocialAccount.objects.filter(user=user, provider__iexact=provider).first()
        if row:
            if row.uid != uid:
                conflict = (
                    SocialAccount.objects.filter(provider__iexact=provider, uid=uid)
                    .exclude(pk=row.pk)
                    .first()
                )
                if conflict:
                    raise ValueError("social_uid_conflict") from None
                row.uid = uid
            row.email = email_norm
            row.save(update_fields=["uid", "email", "modified"])
            return
        again = (
            SocialAccount.objects.filter(provider__iexact=provider, uid=uid)
            .select_related("user")
            .first()
        )
        if again:
            if again.user_id == user.pk:
                return
            raise ValueError("social_uid_linked_other_user") from None
        raise


def _username_from_email(email: str) -> str:
    base = email.strip().lower()[:150]
    if User.objects.filter(username=base).exists():
        for n in range(1, 1000):
            candidate = f"{base[:140]}_{n}"[:150]
            if not User.objects.filter(username=candidate).exists():
                return candidate
    return base


def _username_from_sub(provider: str, sub: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9_]", "_", f"{provider}_{sub}")[:150]
    if not User.objects.filter(username=clean).exists():
        return clean
    for n in range(1, 10000):
        c = f"{clean[:140]}_{n}"[:150]
        if not User.objects.filter(username=c).exists():
            return c
    return clean


def get_or_create_user_for_social(
    *,
    provider: str,
    uid: str,
    email: str | None,
) -> tuple[User, bool]:
    """
    Busca ``SocialAccount`` (provider+uid), o enlaza por email, o crea ``User`` con
    contraseña inutilizable.

    Returns:
        ``(user, is_new_social_registration)``. El segundo valor es ``True`` solo cuando
        en esta petición se creó un usuario **nuevo** vía redes sociales (email inédito);
        esos usuarios se crean con ``is_active=False`` hasta validación administrativa.
    """
    email_norm = _normalize_email(email)

    existing = (
        SocialAccount.objects.filter(provider__iexact=provider, uid=uid)
        .select_related("user")
        .first()
    )
    if existing:
        return existing.user, False

    if not email_norm:
        raise ValueError("email_required")

    user = _find_user_for_social_email(email_norm)
    if user:
        if (
            not (user.email or "").strip()
            and not User.objects.filter(email__iexact=email_norm).exclude(pk=user.pk).exists()
        ):
            user.email = email_norm
            user.save(update_fields=["email"])
        _ensure_social_link(user, provider=provider, uid=uid, email_norm=email_norm)
        return user, False

    uname = _username_from_email(email_norm)
    try:
        with transaction.atomic():
            user = User.objects.create_user(
                username=uname,
                email=email_norm,
                password=None,
                is_active=False,
            )
            _ensure_social_link(user, provider=provider, uid=uid, email_norm=email_norm)
    except IntegrityError:
        # Carrera: otro proceso creó el usuario con ese email, o el enlace social.
        user = _find_user_for_social_email(email_norm)
        if user:
            _ensure_social_link(user, provider=provider, uid=uid, email_norm=email_norm)
            return user, False
        again = (
            SocialAccount.objects.filter(provider__iexact=provider, uid=uid)
            .select_related("user")
            .first()
        )
        if again:
            return again.user, False
        raise

    return user, True


def apply_oidc_profile_claims(user: User, claims: dict[str, Any]) -> None:
    """
    Actualiza ``User`` (nombre, foto) con datos del id_token ya verificado.
    Solo escribe campos cuando el claim trae un string no vacío; no borra
    datos si el claim falta.
    """
    user_fields: list[str] = []
    given = claims.get("given_name")
    family = claims.get("family_name")
    full = claims.get("name")

    if isinstance(given, str) and given.strip():
        user.first_name = given.strip()[:150]
        user_fields.append("first_name")
    if isinstance(family, str) and family.strip():
        user.last_name = family.strip()[:150]
        user_fields.append("last_name")
    if not user_fields and isinstance(full, str) and full.strip():
        parts = full.strip().split(None, 1)
        user.first_name = parts[0][:150]
        user.last_name = (parts[1] if len(parts) > 1 else "")[:150]
        user_fields.extend(["first_name", "last_name"])

    picture = claims.get("picture")
    if isinstance(picture, str) and picture.strip():
        url = picture.strip()[:500]
        # Política: la foto de Google solo se usa como DEFAULT en el primer
        # login. Si el usuario ya tiene un `photo_url` (sea Google previo o
        # un upload custom), respetamos su elección y NO sobrescribimos —
        # patrón estándar de Notion/Slack/Linear: custom siempre gana.
        # Para "volver a la foto de Google" el usuario borra la actual desde
        # el profile editor; en el próximo login se vuelve a llenar.
        if not user.photo_url:
            user.photo_url = url
            user_fields.append("photo_url")

    if user_fields:
        user.save(update_fields=list(dict.fromkeys(user_fields)))


def issue_jwt_pair(user: User) -> dict[str, str]:
    from rest_framework_simplejwt.tokens import RefreshToken

    refresh = RefreshToken.for_user(user)
    return {
        "access": str(refresh.access_token),
        "refresh": str(refresh),
    }
