from rest_framework import serializers


class GoogleIdTokenSerializer(serializers.Serializer):
    id_token = serializers.CharField(required=True, write_only=True, trim_whitespace=False)


class AppleIdTokenSerializer(serializers.Serializer):
    id_token = serializers.CharField(required=True, write_only=True, trim_whitespace=False)
    # Primer inicio: Apple envía ``user`` (JSON) con nombre; re-logins a veces sin email.
    user = serializers.JSONField(required=False, allow_null=True)


class MicrosoftIdTokenSerializer(serializers.Serializer):
    id_token = serializers.CharField(required=True, write_only=True, trim_whitespace=False)
