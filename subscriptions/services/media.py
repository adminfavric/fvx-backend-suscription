"""
URLs firmadas de vida corta para servir archivos protegidos (video/audio/imagen)
del área de miembros.

El objetivo: que el archivo NUNCA se sirva con su URL pública permanente. En su
lugar, cada reproducción pide al backend una URL FIRMADA que caduca en minutos y
solo se entrega a un miembro con membresía activa. Copiar esa URL desde DevTools
sirve unos pocos minutos y luego expira → no se puede compartir ni "robar" el link
para verlo fuera de la plataforma.

Requisito para que el candado sea real: el bucket S3/B2 debe ser PRIVADO (sin
lectura pública). Con el bucket público, la URL permanente seguiría funcionando si
alguien la conociera; aquí ya no la exponemos, pero conviene cerrarla en el bucket.

Con ``STORAGE_BACKEND`` != ``s3`` (local/gcs en dev) se devuelve la URL tal cual:
no hay firma que aplicar y el entorno no es productivo.
"""

from __future__ import annotations

from urllib.parse import unquote, urlparse

from django.conf import settings

# Vida por defecto de la URL firmada (segundos). 2 horas: suficiente para ver
# videos largos sin que la firma expire a mitad (aunque se pause y se adelante).
# Ajustable por env ``MEDIA_SIGNED_URL_EXPIRE``.
DEFAULT_EXPIRE = getattr(settings, "MEDIA_SIGNED_URL_EXPIRE", 7200)


def _bucket_key_from_url(url: str) -> tuple[str, str]:
    """Deriva ``(bucket, key)`` del objeto a partir de su URL (estilo path).

    Backblaze/S3 path-style: ``https://s3.region.backblazeb2.com/<bucket>/<key>``
    → el primer segmento del path es el bucket y el resto la key. Así se firma
    contra el bucket REAL donde está el archivo (público viejo o privado nuevo),
    sin depender de una config fija.
    """
    path = unquote(urlparse(url).path).lstrip("/")
    parts = path.split("/", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return "", path


def signed_media_url(file_url: str, expires: int | None = None) -> str:
    """Devuelve una URL firmada de vida corta para ``file_url``.

    Si el almacenamiento no es S3 o algo falla, cae a la URL original (best-effort):
    preferimos que el miembro pueda ver el contenido a romper la reproducción.
    """
    if not file_url:
        return file_url
    if getattr(settings, "STORAGE_BACKEND", "local") != "s3":
        return file_url

    try:
        import boto3
        from botocore.client import Config

        bucket, key = _bucket_key_from_url(file_url)
        if not bucket or not key:
            return file_url

        client = boto3.client(
            "s3",
            endpoint_url=getattr(settings, "AWS_S3_ENDPOINT_URL", None),
            aws_access_key_id=getattr(settings, "AWS_ACCESS_KEY_ID", ""),
            aws_secret_access_key=getattr(settings, "AWS_SECRET_ACCESS_KEY", ""),
            region_name=getattr(settings, "AWS_S3_REGION_NAME", "us-east-1"),
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires or DEFAULT_EXPIRE,
        )
    except Exception:
        # Sin boto3 / mala config / URL externa: devolver la original.
        return file_url
