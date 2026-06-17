"""
Endpoint genérico de subida: ``POST /api/v1/uploads/``.

Recibe multipart/form-data con ``file`` y opcionalmente ``path_prefix`` y
``metadata`` (JSON string). El binario se persiste vía ``default_storage`` —
local, S3-compatible o GCS según ``settings.STORAGE_BACKEND`` (ver
``docs/storage.md``). El front mide el progreso con
``HttpClient.reportProgress`` sin conocer el destino real.
"""

from __future__ import annotations

import os

from django.core.files.storage import default_storage
from django.utils.text import get_valid_filename
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..serializers import UploadRequestSerializer, UploadResponseSerializer


def _safe_name(raw: str) -> str:
    """Strip any path component and normalize to a safe filename.

    A client-supplied ``name`` like ``../../etc/x`` or ``a/b.png`` must never
    influence the storage path beyond the explicit ``path_prefix``.
    """
    base = os.path.basename((raw or "").replace("\\", "/"))
    cleaned = get_valid_filename(base) if base else ""
    return cleaned or "upload"


class UploadView(APIView):
    """
    Sube un archivo y devuelve la URL pública (o ``/media/...`` si backend=local).

    El path final es ``{path_prefix}/{name}`` cuando se pasa ``path_prefix``,
    o solo ``{name}`` en caso contrario. ``default_storage.save`` añade sufijo
    si el nombre colisiona — el cliente debe respetar la URL devuelta.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    throttle_scope = "upload"

    def post(self, request):
        serializer = UploadRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        upload = serializer.validated_data["file"]
        path_prefix = serializer.validated_data.get("path_prefix", "")
        metadata = serializer.validated_data.get("metadata", {})

        safe_name = _safe_name(upload.name)
        target = f"{path_prefix}/{safe_name}" if path_prefix else safe_name
        saved_path = default_storage.save(target, upload)
        # URL ABSOLUTA: con FS local, ``default_storage.url`` devuelve algo
        # relativo (``/media/...``) que el front (otro origen/puerto) no podría
        # cargar. ``build_absolute_uri`` lo resuelve contra el host del backend.
        # Si el storage ya devuelve absoluta (S3/GCS), se respeta tal cual.
        public_url = request.build_absolute_uri(default_storage.url(saved_path))

        payload = {
            "url": public_url,
            "path": saved_path,
            "size": upload.size,
            "name": safe_name,
            "mime_type": upload.content_type or "",
            "meta": metadata,
        }
        response = UploadResponseSerializer(payload)
        return Response(response.data, status=status.HTTP_201_CREATED)


class UploadDeleteView(APIView):
    """``DELETE /api/v1/uploads/?path=<storage_path>`` — borra del backend activo."""

    permission_classes = [IsAuthenticated]

    def delete(self, request):
        path = request.query_params.get("path", "").strip()
        if not path:
            return Response({"detail": "path is required"}, status=status.HTTP_400_BAD_REQUEST)
        if ".." in path.split("/"):
            return Response({"detail": "invalid path"}, status=status.HTTP_400_BAD_REQUEST)
        if default_storage.exists(path):
            default_storage.delete(path)
        return Response(status=status.HTTP_204_NO_CONTENT)
