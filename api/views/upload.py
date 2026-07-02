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
import secrets

from django.conf import settings
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


def _ext(name: str) -> str:
    return os.path.splitext(name or "")[1].lower().lstrip(".")


class SignedUrlUploadView(APIView):
    """
    Subida DIRECTA al bucket (S3/Backblaze) sin pasar por el backend.

    ``POST /api/v1/uploads/signed-url/`` con ``{filename, mime_type, size,
    path_prefix?}`` → devuelve un ``upload_url`` (presigned PUT) al que el
    navegador sube el archivo directamente, y el ``public_url`` que se guarda como
    referencia. Ideal para videos grandes: no consume el timeout ni el ancho de
    banda del servidor. La reproducción sigue firmándose por sesión (``/media/``).

    Requiere ``STORAGE_BACKEND=s3``. En local (dev) no aplica: se responde 400 y el
    front puede caer al provider normal.
    """

    permission_classes = [IsAuthenticated]

    def _client(self):
        import boto3
        from botocore.client import Config

        return boto3.client(
            "s3",
            endpoint_url=getattr(settings, "AWS_S3_ENDPOINT_URL", None),
            aws_access_key_id=getattr(settings, "AWS_ACCESS_KEY_ID", ""),
            aws_secret_access_key=getattr(settings, "AWS_SECRET_ACCESS_KEY", ""),
            region_name=getattr(settings, "AWS_S3_REGION_NAME", "us-east-1"),
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def post(self, request):
        if getattr(settings, "STORAGE_BACKEND", "local") != "s3":
            return Response(
                {"detail": "La subida directa requiere almacenamiento S3."}, status=400
            )

        data = request.data
        filename = _safe_name(data.get("filename") or "")
        size = int(data.get("size") or 0)
        prefix = (data.get("path_prefix") or "").strip().strip("/")
        if ".." in prefix.split("/"):
            return Response({"detail": "path_prefix inválido."}, status=400)

        # Validaciones equivalentes al upload por backend (tipo + tamaño).
        allowed_ext = getattr(settings, "UPLOAD_ALLOWED_EXTENSIONS", None)
        if allowed_ext is not None and _ext(filename) not in allowed_ext:
            return Response(
                {"detail": f'Tipo ".{_ext(filename) or "?"}" no permitido.'}, status=400
            )
        limit = getattr(settings, "UPLOAD_MAX_BYTES", 500 * 1024 * 1024)
        if size and size > limit:
            mb = limit // (1024 * 1024)
            return Response({"detail": f"El archivo supera el máximo de {mb} MB."}, status=400)

        # Bucket destino: el PRIVADO de media si está configurado (videos/audios),
        # si no, el bucket por defecto. Con bucket dedicado NO anteponemos
        # AWS_LOCATION (evita un prefijo redundante tipo ``suscription/suscription/``).
        media_bucket = getattr(settings, "MEDIA_PRIVATE_BUCKET", "") or settings.AWS_STORAGE_BUCKET_NAME
        location = (
            ""
            if getattr(settings, "MEDIA_PRIVATE_BUCKET", "")
            else (getattr(settings, "AWS_LOCATION", "") or "").strip("/")
        )
        # Key: [<AWS_LOCATION>/]<path_prefix>/<aleatorio>-<nombre>. El sufijo evita
        # que dos archivos con el mismo nombre se pisen (no hay chequeo de colisión).
        unique = f"{secrets.token_hex(4)}-{filename}"
        key = "/".join(p for p in (location, prefix, unique) if p)

        bucket = media_bucket
        try:
            upload_url = self._client().generate_presigned_url(
                "put_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=getattr(settings, "UPLOAD_SIGNED_URL_EXPIRE", 3600),
            )
        except Exception:
            return Response({"detail": "No se pudo firmar la subida."}, status=502)

        endpoint = (getattr(settings, "AWS_S3_ENDPOINT_URL", "") or "").rstrip("/")
        public_url = f"{endpoint}/{bucket}/{key}" if endpoint else key

        return Response(
            {
                "upload_url": upload_url,
                "upload_headers": {},
                "storage_path": key,
                "public_url": public_url,
            }
        )

    def delete(self, request):
        """``DELETE /uploads/signed-url/?path=<key>`` — borra el objeto del bucket."""
        path = (request.query_params.get("path") or "").strip()
        if not path or ".." in path.split("/"):
            return Response({"detail": "path inválido."}, status=400)
        if getattr(settings, "STORAGE_BACKEND", "local") != "s3":
            return Response(status=status.HTTP_204_NO_CONTENT)
        media_bucket = getattr(settings, "MEDIA_PRIVATE_BUCKET", "") or settings.AWS_STORAGE_BUCKET_NAME
        try:
            self._client().delete_object(Bucket=media_bucket, Key=path)
        except Exception:
            pass
        return Response(status=status.HTTP_204_NO_CONTENT)


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
