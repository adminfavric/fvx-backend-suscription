"""
Configura el CORS del bucket PRIVADO de media para permitir la **subida directa**
desde el navegador (presigned PUT).

Usa la **API NATIVA de B2** (no la S3): Backblaze rechaza ``PutBucketCors`` por S3
si el bucket ya tiene reglas CORS nativas (las que crea el panel web). La API
nativa sí las actualiza. Se corre dentro del contenedor con ``requests`` (ya
instalado), sin CLIs extra:

    docker compose -f docker-compose.yml -f docker-compose.prod.yml \\
        exec web python manage.py set_media_cors \\
        --access-key <MASTER_KEY_ID> --secret-key <MASTER_APP_KEY>

Necesita una llave con capacidad ``writeBuckets`` (la Master Application Key la
tiene). Si no se pasan ``--access-key/--secret-key``, usa las del ``.env`` (que
pueden no tener permiso → "not entitled").
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

B2_AUTH_URL = "https://api.backblazeb2.com/b2api/v2/b2_authorize_account"


class Command(BaseCommand):
    help = "Configura el CORS (subida directa PUT) del bucket privado vía API nativa de B2."

    def add_arguments(self, parser):
        parser.add_argument("--bucket", default=None, help="Bucket (default: MEDIA_PRIVATE_BUCKET o el por defecto).")
        parser.add_argument("--origins", nargs="+", default=None, help="Orígenes HTTPS permitidos.")
        parser.add_argument("--access-key", default=None, help="keyID con capacidad writeBuckets (ej. Master Key).")
        parser.add_argument("--secret-key", default=None, help="applicationKey correspondiente.")

    def handle(self, *args, **opts):
        import requests

        bucket = (
            opts["bucket"]
            or getattr(settings, "MEDIA_PRIVATE_BUCKET", "")
            or getattr(settings, "AWS_STORAGE_BUCKET_NAME", "")
        )
        if not bucket:
            raise CommandError("No hay bucket definido (MEDIA_PRIVATE_BUCKET / AWS_STORAGE_BUCKET_NAME).")

        key_id = opts["access_key"] or getattr(settings, "AWS_ACCESS_KEY_ID", "")
        app_key = opts["secret_key"] or getattr(settings, "AWS_SECRET_ACCESS_KEY", "")
        if not (key_id and app_key):
            raise CommandError("Faltan credenciales (--access-key/--secret-key o las del .env).")

        origins = opts["origins"] or [
            o for o in [
                (getattr(settings, "FRONTEND_BASE_URL", "") or "").rstrip("/"),
                "https://experienciaslitadonoso.com",
                "https://exp-lita.web.app",
            ] if o
        ]
        origins = list(dict.fromkeys(origins))

        # 1) Autorizar cuenta.
        try:
            auth = requests.get(B2_AUTH_URL, auth=(key_id, app_key), timeout=30)
            auth.raise_for_status()
            auth = auth.json()
        except Exception as exc:  # noqa: BLE001
            raise CommandError(f"No se pudo autorizar en B2 (¿credenciales?): {exc}")

        api_url = auth["apiUrl"]
        token = auth["authorizationToken"]
        account_id = auth["accountId"]
        headers = {"Authorization": token}

        # 2) Buscar el bucketId por nombre.
        try:
            lb = requests.post(
                f"{api_url}/b2api/v2/b2_list_buckets",
                headers=headers,
                json={"accountId": account_id, "bucketName": bucket},
                timeout=30,
            )
            lb.raise_for_status()
            buckets = lb.json().get("buckets", [])
        except Exception as exc:  # noqa: BLE001
            raise CommandError(f"No se pudo listar buckets: {exc}")
        if not buckets:
            raise CommandError(f"No se encontró el bucket '{bucket}' con esta llave.")
        bucket_id = buckets[0]["bucketId"]

        # 3) Actualizar las reglas CORS (subida S3 PUT + lectura GET/HEAD firmada).
        cors_rules = [{
            "corsRuleName": "browser-uploads",
            "allowedOrigins": origins,
            "allowedOperations": ["s3_put", "s3_get", "s3_head"],
            "allowedHeaders": ["*"],
            "exposeHeaders": ["etag"],
            "maxAgeSeconds": 3600,
        }]
        try:
            ub = requests.post(
                f"{api_url}/b2api/v2/b2_update_bucket",
                headers=headers,
                json={"accountId": account_id, "bucketId": bucket_id, "corsRules": cors_rules},
                timeout=30,
            )
            ub.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            body = getattr(getattr(exc, "response", None), "text", "")
            raise CommandError(f"No se pudo actualizar CORS: {exc}\n{body}")

        self.stdout.write(self.style.SUCCESS(
            f"CORS aplicado en '{bucket}' (API nativa B2) para: {', '.join(origins)}"
        ))
        self.stdout.write(f"Reglas: {ub.json().get('corsRules')}")
