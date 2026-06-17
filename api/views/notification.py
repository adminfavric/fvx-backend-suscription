"""
Inbox de notificaciones por usuario.

- ``GET /api/v1/notifications/`` — lista paginada del usuario actual.
- ``GET /api/v1/notifications/?unread=true`` — solo no leídas.
- ``POST /api/v1/notifications/{id}/read/`` — marca una como leída.
- ``POST /api/v1/notifications/mark-all-read/`` — marca todas las no leídas.

Pensado para poll desde el front cada ~60s (ver ``InboxService`` en Angular).
"""

from __future__ import annotations

from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ..models import Notification
from ..serializers import NotificationSerializer


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """Solo lectura + acciones específicas (`mark_read`, `mark_all_read`)."""

    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Notification.objects.filter(user=self.request.user)
        if self.request.query_params.get("unread") in ("true", "1"):
            qs = qs.filter(read_at__isnull=True)
        return qs

    @action(detail=True, methods=["post"], url_path="read")
    def mark_read(self, request, pk=None):
        notification = self.get_object()
        if notification.read_at is None:
            notification.read_at = timezone.now()
            notification.save(update_fields=["read_at", "modified"])
        return Response(NotificationSerializer(notification).data)

    @action(detail=False, methods=["post"], url_path="mark-all-read")
    def mark_all_read(self, request):
        updated = Notification.objects.filter(user=request.user, read_at__isnull=True).update(
            read_at=timezone.now()
        )
        return Response({"updated": updated})
