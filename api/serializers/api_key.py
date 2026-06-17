from django.contrib.auth import get_user_model
from rest_framework import serializers

from ..models import ApiKey

User = get_user_model()


class ApiKeySerializer(serializers.ModelSerializer):
    user_username = serializers.CharField(source="user.username", read_only=True)
    created_by_username = serializers.SerializerMethodField()

    class Meta:
        model = ApiKey
        fields = [
            "id",
            "name",
            "prefix",
            "user",
            "user_username",
            "created_by",
            "created_by_username",
            "last_used_at",
            "is_active",
            "expires_at",
            "scopes",
            "created",
            "modified",
        ]
        read_only_fields = fields

    def get_created_by_username(self, obj):
        if obj.created_by_id:
            return obj.created_by.get_username()
        return None


class ApiKeyCreateSerializer(serializers.Serializer):
    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())
    name = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    # Opcionales: vencimiento y scopes de la llave (ver modelo ApiKey).
    expires_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
    scopes = serializers.ListField(
        child=serializers.CharField(max_length=100),
        required=False,
        default=list,
    )
