"""
Configura el CORS del bucket PRIVADO de media para permitir la **subida directa**
desde el navegador (presigned PUT).

Necesario porque el panel web de Backblaze solo ofrece CORS de *descarga*; la
subida (``s3_put`` / método PUT) requiere una regla personalizada. Este comando
la aplica con boto3 usando las credenciales S3 ya configuradas — se corre dentro
del contenedor, sin instalar CLIs extra:

    docker compose -f docker-compose.yml -f docker-compose.prod.yml \\
        exec web python manage.py set_media_cors

Orígenes por defecto: FRONTEND_BASE_URL + dominios de la plataforma. Se pueden
pasar otros con ``--origins https://a.com https://b.com`` y el bucket con
``--bucket nombre``.
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Configura el CORS del bucket privado de media (permite subida directa PUT)."

    def add_arguments(self, parser):
        parser.add_argument("--bucket", default=None, help="Bucket (default: MEDIA_PRIVATE_BUCKET o el por defecto).")
        parser.add_argument("--origins", nargs="+", default=None, help="Orígenes HTTPS permitidos.")

    def handle(self, *args, **opts):
        if getattr(settings, "STORAGE_BACKEND", "local") != "s3":
            raise CommandError("STORAGE_BACKEND no es 's3'; no hay bucket que configurar.")

        bucket = (
            opts["bucket"]
            or getattr(settings, "MEDIA_PRIVATE_BUCKET", "")
            or getattr(settings, "AWS_STORAGE_BUCKET_NAME", "")
        )
        if not bucket:
            raise CommandError("No hay bucket definido (MEDIA_PRIVATE_BUCKET / AWS_STORAGE_BUCKET_NAME).")

        origins = opts["origins"] or [
            o for o in [
                (getattr(settings, "FRONTEND_BASE_URL", "") or "").rstrip("/"),
                "https://experienciaslitadonoso.com",
                "https://exp-lita.web.app",
            ] if o
        ]
        origins = list(dict.fromkeys(origins))  # dedupe, preserva orden

        import boto3
        from botocore.client import Config

        client = boto3.client(
            "s3",
            endpoint_url=getattr(settings, "AWS_S3_ENDPOINT_URL", None),
            aws_access_key_id=getattr(settings, "AWS_ACCESS_KEY_ID", ""),
            aws_secret_access_key=getattr(settings, "AWS_SECRET_ACCESS_KEY", ""),
            region_name=getattr(settings, "AWS_S3_REGION_NAME", "us-east-1"),
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

        rules = [{
            "AllowedOrigins": origins,
            "AllowedMethods": ["PUT", "GET", "HEAD"],
            "AllowedHeaders": ["*"],
            "ExposeHeaders": ["ETag"],
            "MaxAgeSeconds": 3600,
        }]

        try:
            client.put_bucket_cors(Bucket=bucket, CORSConfiguration={"CORSRules": rules})
        except Exception as exc:  # noqa: BLE001
            raise CommandError(
                f"No se pudo aplicar CORS al bucket '{bucket}': {exc}\n"
                "Si Backblaze no acepta PutBucketCors por S3, avísame y lo hacemos "
                "por la API nativa de B2."
            )

        self.stdout.write(self.style.SUCCESS(
            f"CORS aplicado en '{bucket}' para: {', '.join(origins)}"
        ))
        try:
            current = client.get_bucket_cors(Bucket=bucket)
            self.stdout.write(f"Reglas actuales: {current.get('CORSRules')}")
        except Exception:  # noqa: BLE001
            pass
