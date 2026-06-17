"""Serializers para el endpoint genérico de subida (``POST /api/v1/uploads/``)."""

from __future__ import annotations

import json
import os

from django.conf import settings
from rest_framework import serializers


def _ext(filename: str) -> str:
    return os.path.splitext(filename or "")[1].lower().lstrip(".")


def _validate_path_prefix(value: str) -> str:
    """Evita traversal y normaliza separadores (``./``, ``..``, leading ``/``)."""
    cleaned = (value or "").strip().strip("/").strip("\\")
    if not cleaned:
        return ""
    if ".." in cleaned.split("/"):
        raise serializers.ValidationError('path_prefix may not contain "..".')
    return cleaned


class UploadRequestSerializer(serializers.Serializer):
    """
    Body del POST multipart. El binario va en ``file``; el resto son metadatos
    opcionales que ayudan a construir la ruta de destino y a propagar metadata.
    """

    file = serializers.FileField()
    path_prefix = serializers.CharField(required=False, allow_blank=True, max_length=200)
    metadata = serializers.CharField(required=False, allow_blank=True, max_length=2000)

    def validate_file(self, value):
        limit = getattr(settings, "UPLOAD_MAX_BYTES", 25 * 1024 * 1024)
        if value.size > limit:
            mb = limit // (1024 * 1024)
            raise serializers.ValidationError(f"File exceeds the maximum size of {mb} MB.")

        # Allow-list dura por extensión (bloquea .html/.svg/.js/etc.).
        allowed_ext = getattr(settings, "UPLOAD_ALLOWED_EXTENSIONS", None)
        if allowed_ext is not None:
            ext = _ext(value.name)
            if ext not in allowed_ext:
                raise serializers.ValidationError(
                    f'File type ".{ext or "?"}" is not allowed. '
                    f"Allowed: {', '.join(sorted(allowed_ext))}."
                )

        # Si el cliente declara content-type, también debe estar permitido
        # (defensa adicional; spoofeable, por eso la extensión es el control duro).
        allowed_ct = getattr(settings, "UPLOAD_ALLOWED_CONTENT_TYPES", None)
        ct = getattr(value, "content_type", None)
        if allowed_ct and ct and ct not in allowed_ct:
            raise serializers.ValidationError(f'Content type "{ct}" is not allowed.')
        return value

    def validate_path_prefix(self, value: str) -> str:
        return _validate_path_prefix(value)

    def validate_metadata(self, value: str) -> dict:
        # Front envía metadata como JSON string (form-data no anida bien).
        # Se valida aquí y se devuelve dict; la vista lo guarda como quiera.
        if not value:
            return {}
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as e:
            raise serializers.ValidationError(f"metadata must be valid JSON: {e}")
        if not isinstance(parsed, dict):
            raise serializers.ValidationError("metadata must be a JSON object.")
        return parsed


class UploadResponseSerializer(serializers.Serializer):
    """Contrato de respuesta. El front mapea esto a ``FileUploadResult``."""

    url = serializers.URLField()
    path = serializers.CharField()
    size = serializers.IntegerField()
    name = serializers.CharField()
    mime_type = serializers.CharField(required=False, allow_blank=True)
    meta = serializers.DictField(required=False)
