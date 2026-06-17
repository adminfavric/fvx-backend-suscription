from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ..models import ApiKey
from ..permissions import IsAdminOrReadOnly
from ..serializers import ApiKeyCreateSerializer, ApiKeySerializer


class ApiKeyViewSet(viewsets.ModelViewSet):
    """
    Alta y revocación de claves de API (actúan como un ``User`` concreto).
    Solo staff o perfil ADMIN (misma regla que ``IsAdminOrReadOnly``).
    La clave completa solo se devuelve en el ``POST`` de creación.
    """

    queryset = ApiKey.objects.select_related("user", "created_by").order_by("-created")
    permission_classes = [IsAuthenticated, IsAdminOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["user", "is_active"]
    ordering_fields = ["created", "last_used_at", "name", "prefix"]
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_serializer_class(self):
        if self.action == "create":
            return ApiKeyCreateSerializer
        return ApiKeySerializer

    def create(self, request, *args, **kwargs):
        serializer = ApiKeyCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        prefix, secret_hash, full_key = ApiKey.generate_credentials()
        obj = ApiKey.objects.create(
            user=serializer.validated_data["user"],
            created_by=request.user,
            name=serializer.validated_data.get("name") or "",
            expires_at=serializer.validated_data.get("expires_at"),
            scopes=serializer.validated_data.get("scopes") or [],
            prefix=prefix,
            secret_hash=secret_hash,
        )
        data = ApiKeySerializer(obj).data
        data["key"] = full_key
        data["detail"] = "Guarda esta clave ahora; no se volverá a mostrar."
        return Response(data, status=status.HTTP_201_CREATED)

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save(update_fields=["is_active"])
