"""Serializers para ``rest_framework_simplejwt`` (login por token)."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

User = get_user_model()


class FvxTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Igual que el serializer por defecto de SimpleJWT, pero si el usuario existe,
    la contraseña es correcta y ``is_active`` es ``False``, devolvemos un
    error explícito en lugar del mensaje genérico de credenciales (en español
    suele confundirse con “mal password”).
    """

    def validate(self, attrs):
        username = attrs.get(User.USERNAME_FIELD) or attrs.get("username")
        password = attrs.get("password")
        if username and password:
            try:
                user = User._default_manager.get_by_natural_key(username)
            except User.DoesNotExist:
                user = None
            if user is not None and not user.is_active and user.check_password(password):
                raise AuthenticationFailed(
                    _(
                        "Esta cuenta está desactivada (is_active=false). "
                        "Un administrador debe marcar de nuevo «activo» al usuario en Django Admin "
                        "o en la base de datos."
                    ),
                    code="user_inactive",
                )
        return super().validate(attrs)
