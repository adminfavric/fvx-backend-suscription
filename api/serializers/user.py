from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from ..choices import ROLE_CHOICES, ROLE_VIEWER
from ..roles import get_effective_role_for_user

User = get_user_model()


def _run_password_validators(password: str, user=None) -> None:
    """Aplica los ``AUTH_PASSWORD_VALIDATORS`` de Django sobre `password`.

    DRF acepta `min_length=8` pero no corre los validators de Django (Common,
    UserAttributeSimilarity, NumericPassword, etc.). Sin esta llamada explícita
    cualquiera puede crear cuentas con ``password``, ``12345678``, ``admin``
    o variantes obvias del username.

    Convierte el ``django.core.exceptions.ValidationError`` (lista de mensajes)
    en uno de DRF para que se vea bien en la respuesta del API.
    """
    try:
        validate_password(password, user=user)
    except DjangoValidationError as e:
        raise serializers.ValidationError(list(e.messages))


def role_label_for_code(code: str) -> str:
    """Human-readable role label for the current request locale (gettext)."""
    return str(dict(ROLE_CHOICES).get(code, code))


class UserSerializer(serializers.ModelSerializer):
    """List/update serializer for ``User``. ``role`` is writable here (admin
    use) — for self-service updates see :class:`MeSerializer`."""

    role = serializers.ChoiceField(choices=ROLE_CHOICES, required=False)
    role_label = serializers.SerializerMethodField()
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "is_active",
            "is_staff",
            "date_joined",
            "role",
            "role_label",
            "menu_slugs",
            "phone",
            "photo_url",
            "verified",
        ]
        read_only_fields = ["date_joined"]

    def get_role_label(self, obj) -> str:
        return role_label_for_code(get_effective_role_for_user(obj))

    def get_full_name(self, obj) -> str:
        # `get_full_name()` de Django ("first last"); fallback al username si no
        # hay nombre, para que el front nunca reciba vacío.
        return obj.get_full_name() or obj.get_username()


class UserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    role = serializers.ChoiceField(
        choices=ROLE_CHOICES,
        required=False,
        default=ROLE_VIEWER,
    )

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "password",
            "is_active",
            "is_staff",
            "role",
            "menu_slugs",
            "phone",
            "photo_url",
        ]

    def validate(self, attrs):
        # Corremos los AUTH_PASSWORD_VALIDATORS con el username/email del payload
        # para que `UserAttributeSimilarityValidator` detecte similitud
        # (ej: username='juan', password='Juan1234').
        password = attrs.get("password")
        if password:
            tentative = User(
                username=attrs.get("username", ""),
                email=attrs.get("email", ""),
                first_name=attrs.get("first_name", ""),
                last_name=attrs.get("last_name", ""),
            )
            _run_password_validators(password, user=tentative)
        return super().validate(attrs)

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, min_length=8)

    def validate_new_password(self, value):
        # `self.context['request'].user` cuando lo invoca la view de cambio de
        # password autenticado; permite que el validator detecte similitud
        # con datos del propio usuario (username, email, nombre).
        user = None
        request = self.context.get("request") if hasattr(self, "context") else None
        if request is not None and getattr(request, "user", None) and request.user.is_authenticated:
            user = request.user
        _run_password_validators(value, user=user)
        return value


class UserDetailSerializer(serializers.ModelSerializer):
    """Read-only detail serializer (drawer, /users/me/, etc.)."""

    role_label = serializers.SerializerMethodField()
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "is_active",
            "is_staff",
            "is_superuser",
            "date_joined",
            "last_login",
            "role",
            "role_label",
            "phone",
            "photo_url",
            "verified",
        ]
        read_only_fields = ["date_joined", "last_login"]

    def get_role_label(self, obj) -> str:
        return role_label_for_code(get_effective_role_for_user(obj))

    def get_full_name(self, obj) -> str:
        return obj.get_full_name() or obj.get_username()


class MeSerializer(serializers.ModelSerializer):
    """Serializer para `GET/PATCH /users/me/`.

    Campos editables por el propio usuario: `first_name`, `last_name`,
    `phone`, `photo_url`. El resto queda explícitamente read-only para
    evitar auto-escalada de privilegios (no se puede cambiar `role`,
    `is_staff`, `verified`, etc.).

    **Lock condicional en first_name/last_name**: política de identidad para
    apps financieras (Wise/Stripe/Mercury) — el nombre se puede llenar la
    primera vez (cuenta nueva sin datos), pero una vez completado no se
    edita desde aquí. Si el usuario necesita corregir un typo o cambio
    legal de nombre, lo hace un admin desde `/users` (override staff).
    """

    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "is_active",
            "is_staff",
            "date_joined",
            "last_login",
            "role",
            "phone",
            "photo_url",
            "verified",
        ]
        read_only_fields = [
            "id",
            "username",
            "email",
            "is_active",
            "is_staff",
            "date_joined",
            "last_login",
            "role",
            "verified",
        ]

    def get_full_name(self, obj) -> str:
        return obj.get_full_name() or obj.get_username()

    def update(self, instance, validated_data):
        # Lock condicional: si ya hay valor, ignoramos el PATCH para ese campo.
        for locked_field in ("first_name", "last_name"):
            if locked_field in validated_data and getattr(instance, locked_field, ""):
                validated_data.pop(locked_field)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance
