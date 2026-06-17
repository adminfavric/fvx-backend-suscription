# Storage de archivos — backend pluggable

Documento de referencia para humanos e IAs sobre el sistema de subida de archivos.

## Idea general

- **Un solo endpoint backend**: `POST /api/v1/uploads/` recibe `multipart/form-data` con el binario.
- **Un solo provider front**: `DjangoUploadProvider` mide el progreso con `HttpClient.reportProgress` y mapea la respuesta al contrato `FileUploadResult` del catálogo (`design-fvx.md` §4).
- **El destino real** (local FS, S3-compatible o GCS) lo decide Django vía `default_storage`, parametrizado por la env var `STORAGE_BACKEND`. El front nunca lo sabe.

## Switch principal

```bash
# .env
STORAGE_BACKEND=local       # 'local' | 's3' | 'gcs'
UPLOAD_MAX_BYTES=26214400   # 25 MB; sube si necesitas archivos más grandes
STORAGE_BUCKET_PREFIX=      # opcional; subdirectorio raíz dentro del bucket
```

Cambiar el backend = cambiar esta variable + las creds del proveedor. **Ningún archivo Python/TypeScript se toca.**

### `STORAGE_BUCKET_PREFIX` — namespacing dentro del bucket

Útil cuando varios proyectos comparten el mismo bucket S3/GCS, o quieres aislar los archivos del template bajo una carpeta lógica.

```bash
STORAGE_BUCKET_PREFIX=community
```

| Backend | Efecto |
|---|---|
| `s3` | `AWS_LOCATION=community` → cada key se guarda como `community/<path>` |
| `gcs` | `GS_LOCATION=community` → cada blob name se guarda como `community/<path>` |
| `local` | `MEDIA_ROOT` y `MEDIA_URL` cambian a `media/community/` y `/media/community/` |

El front no se entera: sigue recibiendo `path: "profiles/avatars/foo.png"` (la API trabaja relativo al prefix). Las URLs públicas sí lo incluyen, así que apuntan bien.

Si dejas la variable vacía (default), los archivos van a la raíz del bucket / `media/` como antes.

## Local (dev/testing)

Default. Sin dependencias extra. Los archivos van a `fvx-backend/media/` y se sirven en dev a `http://localhost:8080/media/...` (`core/urls.py` ya tiene el `static()` montado cuando `DEBUG=True`).

**Producción:** no es viable salvo que sirvas `MEDIA_ROOT` con nginx. Para deploy real elige `s3` o `gcs`.

## S3-compatible — AWS, Backblaze, DO Spaces, Wasabi, Cloudflare R2, MinIO

Instalar el SDK:

```bash
pip install django-storages[s3]
# o pip install boto3
```

Configurar `.env`:

```bash
STORAGE_BACKEND=s3
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_STORAGE_BUCKET_NAME=my-bucket
AWS_S3_REGION_NAME=us-east-1
# Solo si NO es AWS:
# AWS_S3_ENDPOINT_URL=<endpoint del proveedor>
```

### Endpoints para cada proveedor

| Proveedor | `AWS_S3_ENDPOINT_URL` | `AWS_S3_REGION_NAME` |
|---|---|---|
| AWS S3 | *(omitir)* | tu región (`us-east-1`, `eu-west-1`…) |
| **Backblaze B2** | `https://s3.us-west-002.backblazeb2.com` (ajustar al endpoint que da el bucket) | `us-west-002` |
| DigitalOcean Spaces | `https://nyc3.digitaloceanspaces.com` (ajustar región) | `nyc3` |
| Wasabi | `https://s3.wasabisys.com` (o regional) | `us-east-1` |
| Cloudflare R2 | `https://<account_id>.r2.cloudflarestorage.com` | `auto` |
| MinIO self-hosted | `https://minio.midominio.com` | tu región |

### CORS del bucket

**No hace falta** configurar CORS en el bucket porque el front habla con Django, no con el bucket directamente. Solo el `Content-Type: multipart/form-data` desde el dominio del front al de la API (`CORS_ALLOWED_ORIGINS` Django) — ya lo tienes.

### URLs públicas vs firmadas

Por defecto este template usa `AWS_QUERYSTRING_AUTH=False` → la URL devuelta es pública directa (el bucket debe ser público o las ACLs por objeto `public-read`). Si tu bucket es privado y quieres URLs firmadas de lectura (caducan):

```bash
AWS_QUERYSTRING_AUTH=True
```

Las URLs vendrán firmadas con TTL.

## Google Cloud Storage

Los SDKs de GCS **ya vienen instalados** en la imagen (`django-storages[s3,google]`
en `requirements.txt`), igual que los de S3. Cambiar a GCS es solo cuestión de
env vars + credenciales — **no requiere reinstalar ni reconstruir**.

`.env`:

```bash
STORAGE_BACKEND=gcs
GS_BUCKET_NAME=my-bucket
GS_PROJECT_ID=my-project
# Deja el JSON del service account en fvx-backend/ (se monta en /app vía el bind
# `.:/app`; está gitignoreado: *-service-account.json / *gcloud*.json).
GOOGLE_APPLICATION_CREDENTIALS=/app/gcs-service-account.json
```

El service account JSON debe tener al menos los roles `Storage Object Creator` y `Storage Object Viewer`. La librería oficial lee `GOOGLE_APPLICATION_CREDENTIALS` por convención.

> Si NO usarás GCS y quieres una imagen más liviana, baja el extra a
> `django-storages[s3]` en `requirements.txt` y reconstruye.

## Archivos grandes (> 25 MB)

Subir el límite Django:
```bash
UPLOAD_MAX_BYTES=104857600   # 100 MB
```

Y en infraestructura:

| Capa | Setting | Valor recomendado |
|---|---|---|
| **nginx (server block)** | `client_max_body_size` | `120m` (un poco por encima del límite Django) |
| **gunicorn** | `--timeout` | `300` (5 min para uploads lentos) |
| **gunicorn** | `--worker-class` | `gthread` o `uvicorn.workers.UvicornWorker` (mejor para I/O largo) |

Para archivos **>= 500 MB** considera migrar a signed URLs directos al bucket: el front ya tiene `SignedUrlUploadProvider` que puede consumir un endpoint distinto sin tocar el resto del flujo. Esa pieza no está incluida en este template pero es la evolución natural cuando aparece el caso.

## Contrato HTTP

### Request — `POST /api/v1/uploads/`

`Content-Type: multipart/form-data` con:

| Campo | Tipo | Requerido | Descripción |
|---|---|---|---|
| `file` | File | sí | El binario |
| `path_prefix` | string | no | Carpeta lógica destino (sin `/` inicial; no admite `..`). Ej.: `profiles/avatars` |
| `metadata` | string JSON | no | Objeto JSON serializado; el backend lo deserializa y devuelve en `meta` |

### Response — `201 Created`

```json
{
  "url": "https://bucket.s3.amazonaws.com/path/file.png",
  "path": "profiles/avatars/file.png",
  "size": 12345,
  "name": "file.png",
  "mime_type": "image/png",
  "meta": { "campos_que_pasaste": "..." }
}
```

### Errores típicos

| Status | Causa | Cuerpo |
|---|---|---|
| 400 | Falta `file` | `{ "file": ["This field is required."] }` |
| 400 | Excede `UPLOAD_MAX_BYTES` | `{ "file": ["File exceeds the maximum size of N MB."] }` |
| 400 | `path_prefix` con `..` | `{ "path_prefix": ["path_prefix may not contain \".\"."] }` |
| 401 | Sin JWT | (interceptor del front intenta refresh) |

### Delete — `DELETE /api/v1/uploads/object/?path=<storage_path>`

Borra el objeto del backend activo. Devuelve `204 No Content`.

## Convención de `path_prefix` por tipo de modelo

El front controla cómo se organizan los uploads vía `FileUploadContext.pathPrefix`. No hay (ni debe haber) política global de "todo va con año/mes"; cada modelo decide según su naturaleza.

| Caso | `path_prefix` sugerido | Por qué |
|---|---|---|
| Avatar de usuario | `profiles/avatars` | 1 archivo por usuario; se reemplaza al actualizar. Sin fecha. |
| Logo de organización / marca | `organizations/logos` | Pocos archivos, lifecycle ≈ nunca. Sin fecha. |
| Documentos / facturas / contratos | `documents/<YYYY>/<MM>` | Crecimiento lineal; lifecycle policies por año son útiles (retención fiscal, archivado). |
| Adjuntos de ticket / mensaje | `tickets/<ticket_id>` | Agrupar por entidad padre facilita listar / borrar todo cuando el ticket se cierra. |
| Imports temporales (CSV, batch) | `imports/<user_id>/<YYYY-MM-DD>` | Temporales — la fecha facilita un cleanup `S3 lifecycle delete > 7 días`. |
| Exports de tablas | `exports/<user_id>` | Por usuario; suelen ser pocos. Sin fecha salvo que el usuario genere muchos. |

### Cuándo añadir año/mes

- **`✅` Vale la pena** cuando el modelo acumula archivos linealmente (1+ por día) y/o necesitas lifecycle policies por antigüedad.
- **`❌` No vale la pena** cuando hay 1 archivo por entidad (avatar, logo) o el conjunto cabe naturalmente en una carpeta por padre (ticket, organización).

### Cómo construirlo en el front

```ts
// Sin fecha — caso típico
this.uploader.upload(avatar, { pathPrefix: 'profiles/avatars' });

// Con año/mes — modelos de "crecen linealmente"
const ym = new Date().toISOString().slice(0, 7); // '2026-05'
this.uploader.upload(doc, { pathPrefix: `documents/${ym}` });

// Por entidad padre
this.uploader.upload(file, { pathPrefix: `tickets/${ticket.id}` });
```

Sin helper centralizado por ahora — cuando 3+ features compartan el patrón de fecha, extraemos a `shared/utils/`.

### Nota sobre cloud vs local

S3 / GCS / Backblaze son object stores planos: el "anidamiento" es estético, no afecta performance de lectura/escritura. La razón de partir por fecha es **operacional** (lifecycle policies, auditoría, backups), no técnica.

En local FS sí pesa para `ls`, `rsync`, file managers — pero solo si llegas a decenas de miles de archivos en la misma carpeta.

## Migrar entre backends

Cambias `.env` y reinicias. Los archivos viejos quedan en el backend anterior (el front los sigue mostrando con sus URLs ya guardadas en BD). Si quieres mover archivos físicamente, usa los CLIs del proveedor:

```bash
# Local → S3
aws s3 sync ./media s3://my-bucket/

# S3 → GCS
gsutil rsync -r s3://my-bucket gs://my-bucket
```

## Referencias

- Catálogo front: `fvx-frontend/docs/design-fvx.md` §4 (`app-file-uploader`).
- Provider: `fvx-frontend/src/app/shared/components/file-uploader/providers/django-upload.provider.ts`.
- Configuración Django: `fvx-backend/core/settings.py` (bloque "Storage").
