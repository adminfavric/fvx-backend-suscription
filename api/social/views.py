"""``POST /api/auth/social/google|apple/`` — intercambio de id_token por par JWT (SimpleJWT)."""

from __future__ import annotations

from django.conf import settings
from django.middleware.csrf import get_token
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import (
    AppleIdTokenSerializer,
    GoogleIdTokenSerializer,
    MicrosoftIdTokenSerializer,
)
from .services import (
    apply_oidc_profile_claims,
    get_or_create_user_for_social,
    issue_jwt_pair,
    verify_apple_id_token,
    verify_google_id_token,
    verify_microsoft_id_token,
)
from .throttles import SocialAuthThrottle
from api.models import SocialProvider

_social_token_response = inline_serializer(
    name="SocialTokenResponse",
    fields={
        "detail": serializers.CharField(
            help_text="'OK' on success. JWT access/refresh are set as HttpOnly "
            "cookies (fvx_access / fvx_refresh); they are NOT returned in the body."
        ),
    },
)

_social_forbidden_response = inline_serializer(
    name="SocialAuthForbiddenResponse",
    fields={
        "detail": serializers.CharField(
            help_text="Motivo (cuenta inactiva o pendiente de validación)"
        )
    },
)

_MSG_SOCIAL_PENDING_VALIDATION = (
    "Tu cuenta se ha registrado correctamente y está pendiente de validación por un administrador. "
    "Por favor espera; te notificaremos cuando puedas acceder."
)
_MSG_SOCIAL_ACCOUNT_INACTIVE = (
    "Tu cuenta está inactiva. No puedes iniciar sesión hasta que un administrador la active."
)


@extend_schema(
    summary="Intercambiar id_token de Google por JWT",
    request=GoogleIdTokenSerializer,
    responses={
        200: _social_token_response,
        403: _social_forbidden_response,
    },
    tags=["auth"],
)
class GoogleSocialAuthView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [SocialAuthThrottle]

    def post(self, request):
        if not settings.SOCIAL_AUTH_GOOGLE_ENABLED:
            return Response(
                {"detail": "Google sign-in is disabled for this environment."},
                status=status.HTTP_403_FORBIDDEN,
            )
        ser = GoogleIdTokenSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        raw = ser.validated_data["id_token"]
        try:
            claims = verify_google_id_token(raw)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception:
            return Response(
                {"detail": "Invalid Google id_token."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        sub = claims.get("sub")
        email = claims.get("email")
        if not sub:
            return Response(
                {"detail": "Token missing sub."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if email and not claims.get("email_verified", True):
            return Response(
                {"detail": "Google email not verified."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return self._issue(
            request,
            user_email=email,
            sub=sub,
            provider=SocialProvider.GOOGLE,
            oidc_claims=claims,
        )

    def _issue(
        self,
        request,
        *,
        user_email,
        sub,
        provider,
        oidc_claims: dict | None = None,
    ) -> Response:
        try:
            user, is_new_social_registration = get_or_create_user_for_social(
                provider=provider,
                uid=sub,
                email=user_email,
            )
        except ValueError as e:
            if str(e) == "email_required":
                return Response(
                    {
                        "detail": "Cannot create account: email is missing from token (Sign in with Apple: use first sign-in or enable email scope)."
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        if oidc_claims:
            apply_oidc_profile_claims(user, oidc_claims)
        if not user.is_active:
            detail = (
                _MSG_SOCIAL_PENDING_VALIDATION
                if is_new_social_registration
                else _MSG_SOCIAL_ACCOUNT_INACTIVE
            )
            return Response({"detail": detail}, status=status.HTTP_403_FORBIDDEN)
        # Set tokens en cookies HttpOnly (mismo flujo que /api/auth/token/);
        # body sin tokens para evitar leak vía JS.
        from api.jwt.cookies import set_auth_cookies

        pair = issue_jwt_pair(user)
        response = Response({"detail": "OK"}, status=status.HTTP_200_OK)
        set_auth_cookies(response, pair["access"], pair["refresh"])
        get_token(request)  # cookie csrftoken para el double-submit del SPA
        return response


@extend_schema(
    summary="Intercambiar id_token de Apple por JWT",
    request=AppleIdTokenSerializer,
    responses={
        200: _social_token_response,
        403: _social_forbidden_response,
    },
    tags=["auth"],
)
class AppleSocialAuthView(GoogleSocialAuthView):
    throttle_classes = [SocialAuthThrottle]

    def post(self, request):
        if not settings.SOCIAL_AUTH_APPLE_ENABLED:
            return Response(
                {"detail": "Apple sign-in is disabled for this environment."},
                status=status.HTTP_403_FORBIDDEN,
            )
        ser = AppleIdTokenSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        raw = ser.validated_data["id_token"]
        try:
            claims = verify_apple_id_token(raw)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception:
            return Response(
                {"detail": "Invalid Apple id_token."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        sub = claims.get("sub")
        email = claims.get("email")
        if not sub:
            return Response(
                {"detail": "Token missing sub."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not email:
            from api.models import SocialAccount

            link = (
                SocialAccount.objects.filter(provider__iexact=SocialProvider.APPLE, uid=sub)
                .select_related("user")
                .first()
            )
            if link:
                u = link.user
                apply_oidc_profile_claims(u, claims)
                if not u.is_active:
                    return Response(
                        {"detail": _MSG_SOCIAL_ACCOUNT_INACTIVE},
                        status=status.HTTP_403_FORBIDDEN,
                    )
                # Re-login Apple (sin email): este es el camino NORMAL de un
                # usuario Apple recurrente (Apple omite el email tras el primer
                # sign-in). Debe seguir el mismo flujo de cookies HttpOnly que
                # el resto de los logins: tokens en cookies, body sin tokens
                # (evita leak vía JS y un 401 en /me/ porque el front confía
                # en la cookie, no en el body).
                from api.jwt.cookies import set_auth_cookies

                pair = issue_jwt_pair(u)
                response = Response({"detail": "OK"}, status=status.HTTP_200_OK)
                set_auth_cookies(response, pair["access"], pair["refresh"])
                get_token(request)  # cookie csrftoken para el double-submit
                return response
            return Response(
                {
                    "detail": "Email missing from token and no existing social link; cannot create a new user.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return self._issue(
            request,
            user_email=email,
            sub=sub,
            provider=SocialProvider.APPLE,
            oidc_claims=claims,
        )


@extend_schema(
    summary="Intercambiar id_token de Microsoft por JWT",
    request=MicrosoftIdTokenSerializer,
    responses={
        200: _social_token_response,
        403: _social_forbidden_response,
    },
    tags=["auth"],
)
class MicrosoftSocialAuthView(GoogleSocialAuthView):
    """
    Entra ID (OIDC v2.0). Estructuralmente igual a Apple: valida un JWT contra el
    JWKS de Microsoft y delega en ``_issue``. El email llega en ``email`` (optional
    claim) o, en su defecto, en ``preferred_username`` (UPN, normalmente el correo).
    """

    throttle_classes = [SocialAuthThrottle]

    def post(self, request):
        if not settings.SOCIAL_AUTH_MICROSOFT_ENABLED:
            return Response(
                {"detail": "Microsoft sign-in is disabled for this environment."},
                status=status.HTTP_403_FORBIDDEN,
            )
        ser = MicrosoftIdTokenSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        raw = ser.validated_data["id_token"]
        try:
            claims = verify_microsoft_id_token(raw)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception:
            return Response(
                {"detail": "Invalid Microsoft id_token."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        sub = claims.get("sub")
        # Entra: ``email`` solo si está el optional claim; ``preferred_username``
        # suele ser el UPN (correo). Solo lo aceptamos si parece un email.
        email = claims.get("email")
        if not email:
            upn = claims.get("preferred_username")
            if isinstance(upn, str) and "@" in upn:
                email = upn
        if not sub:
            return Response(
                {"detail": "Token missing sub."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return self._issue(
            request,
            user_email=email,
            sub=sub,
            provider=SocialProvider.MICROSOFT,
            oidc_claims=claims,
        )
