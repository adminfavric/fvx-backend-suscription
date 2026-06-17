"""Serializer para `Notification` (inbox del usuario autenticado)."""

from __future__ import annotations

from rest_framework import serializers

from ..models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = [
            "id",
            "kind",
            "title",
            "body",
            "link",
            "read_at",
            "created",
            "modified",
        ]
        read_only_fields = fields
