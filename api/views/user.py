from django.contrib.auth import get_user_model
from django.middleware.csrf import get_token
from django.utils.translation import gettext_lazy as _
from django_filters.rest_framework import DjangoFilterBackend
from django.contrib.auth.models import Group
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ..permissions import IsAdminOrReadOnly
from ..serializers import (
    ChangePasswordSerializer,
    GroupSerializer,
    MeSerializer,
    UserCreateSerializer,
    UserDetailSerializer,
    UserSerializer,
)

User = get_user_model()


class GroupViewSet(viewsets.ModelViewSet):
    queryset = Group.objects.all().order_by("name")
    serializer_class = GroupSerializer
    permission_classes = [IsAuthenticated, IsAdminOrReadOnly]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name"]
    ordering_fields = ["name"]


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all().order_by("username")
    permission_classes = [IsAuthenticated, IsAdminOrReadOnly]
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = ["is_active", "is_staff"]
    search_fields = ["username", "email", "first_name", "last_name"]
    ordering_fields = ["username", "email", "first_name", "last_name", "date_joined"]

    def get_serializer_class(self):
        if self.action == "create":
            return UserCreateSerializer
        if self.action in ["retrieve", "list", "me", "detail_view"]:
            return UserDetailSerializer
        return UserSerializer

    def perform_create(self, serializer):
        """Privilege fields (``is_staff``, ``role``) solo los asigna ``is_staff``.

        Sin esto, un ADMIN no-staff (que ``IsAdminOrReadOnly`` deja escribir)
        podría crear cuentas con rol ADMIN o flag staff → escalada horizontal.
        """
        if not self.request.user.is_staff:
            serializer.validated_data.pop("is_staff", None)
            serializer.validated_data.pop("role", None)
            serializer.validated_data.pop("menu_slugs", None)
        serializer.save()

    def perform_update(self, serializer):
        """Evita quedar fuera del sistema y escalada de privilegios: ``is_staff``
        y ``role`` solo los cambia staff; no auto-desactivación; no dejar al
        último superusuario inactivo."""
        if not self.request.user.is_staff:
            serializer.validated_data.pop("is_staff", None)
            serializer.validated_data.pop("role", None)
            serializer.validated_data.pop("menu_slugs", None)
        instance = serializer.instance
        validated = serializer.validated_data
        if validated.get("is_active") is False:
            if instance.pk == self.request.user.pk:
                raise ValidationError(
                    {
                        "is_active": _(
                            "No puede desactivar su propia cuenta mientras está autenticado."
                        )
                    },
                )
            if instance.is_superuser:
                other_active = (
                    User.objects.filter(is_superuser=True, is_active=True)
                    .exclude(pk=instance.pk)
                    .exists()
                )
                if not other_active:
                    raise ValidationError(
                        {
                            "is_active": _(
                                "Debe permanecer al menos un superusuario activo. "
                                "Active otro superusuario antes de desactivar este."
                            ),
                        },
                    )
        serializer.save()

    @action(
        detail=False,
        methods=["get", "patch"],
        permission_classes=[IsAuthenticated],
    )
    def me(self, request):
        """Devuelve/actualiza la ficha del **usuario autenticado**.

        `GET` → perfil completo (``UserDetailSerializer``).
        `PATCH` → permite cambiar `first_name`, `last_name` y los campos
        editables del perfil (ver :class:`MeSerializer`). Bloquea identidad
        (`username`, `email`), flags admin (`is_staff`, `is_active`) y el
        rol, de modo que ningún usuario puede auto-escalarse privilegios.
        """
        # El SPA llama GET /users/me/ en cada bootstrap (tras login y al
        # restaurar sesión por cookie). Emitimos aquí la cookie `csrftoken`
        # para que siempre tenga el token del double-submit antes de mutar,
        # incluso en sesiones que regresan sin pasar por /token/.
        get_token(request)
        if request.method.lower() == "patch":
            serializer = MeSerializer(request.user, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(UserDetailSerializer(request.user).data)
        return Response(UserDetailSerializer(request.user).data)

    @action(detail=False, methods=["put"], permission_classes=[IsAuthenticated])
    def change_password(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if not request.user.check_password(serializer.validated_data["old_password"]):
            return Response(
                {"old_password": "Current password is incorrect."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        request.user.set_password(serializer.validated_data["new_password"])
        request.user.save()
        return Response({"detail": "Password updated."})

    @action(detail=True, methods=["get"], url_path="detail-view")
    def detail_view(self, request, pk=None):
        user = self.get_object()
        serializer = UserDetailSerializer(user)
        return Response(serializer.data)
