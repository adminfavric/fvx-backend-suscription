"""Django settings — BASE (común a todos los entornos).

Settings dividido por entorno: este `base.py` tiene lo común; `dev.py` /
`prod.py` / `test.py` heredan (`from .base import *`) y afinan. El módulo activo
lo elige `core/settings/__init__.py` según `DJANGO_ENV` (default `dev`).

Históricamente este archivo era `core/settings.py`; gran parte del
comportamiento por entorno ya vive aquí gobernado por `DEBUG`/`env(...)`, así que
los overlays son delgados (sobre todo afinan defaults y hardening explícito)."""

import os
from pathlib import Path
from datetime import timedelta
import environ

# Build paths. Tres niveles arriba: core/settings/base.py → core/settings →
# core → fvx-backend/ (raíz del backend, donde vive .env y manage.py).
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Environment variables
env = environ.Env(DEBUG=(bool, False))

# Read .env file. ``overwrite=True``: valores del archivo ganan a variables ya
# inyectadas (p. ej. Docker Compose + shell del host con ``SOCIAL_*`` antiguos).
environ.Env.read_env(os.path.join(BASE_DIR, ".env"), overwrite=True)

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = env("DJANGO_SECRET_KEY", default="django-insecure-change-this-in-production")

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env("DJANGO_DEBUG", default=True)

ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["*"])

# Orígenes confiados para CSRF en métodos inseguros (POST/PATCH/PUT/DELETE) con
# auth por cookie: Django 4 valida el header `Origin` contra esta lista. El SPA
# de desarrollo corre en otro puerto (p. ej. http://localhost:4200) → es
# cross-origin respecto al API (:8080), así que su origen DEBE figurar aquí o
# todo guardado (preferencias de usuario, CRUD, etc.) responde 403
# ("Origin checking failed"). Es el complemento de `_enforce_csrf` (ver
# api/authentication.py).
#
# Dev (DEBUG=True): default a los orígenes locales para que el template funcione
# sin configurar nada. Prod (DEBUG=False): default vacío → hay que declararlos
# explícitamente en el .env (DJANGO_CSRF_TRUSTED_ORIGINS=https://app.tudominio.com,...).
_DEV_TRUSTED_ORIGINS = [
    "http://localhost:4200",
    "http://127.0.0.1:4200",
    "http://localhost:4201",
    "http://127.0.0.1:4201",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
]
CSRF_TRUSTED_ORIGINS = env.list(
    "DJANGO_CSRF_TRUSTED_ORIGINS",
    default=(_DEV_TRUSTED_ORIGINS if DEBUG else []),
)

# Detrás de nginx con proxy_set_header X-Forwarded-Proto $scheme;
if env.bool("DJANGO_USE_PROXY_HEADERS", default=False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Application definition
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third party apps
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "django_filters",
    "drf_spectacular",
    "auditlog",
    "axes",
    "django_celery_beat",
    # Local apps
    "api",
    "notifications",
    "subscriptions",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "auditlog.middleware.AuditlogMiddleware",
    # AxesMiddleware DEBE ir al final (después de Authentication) para
    # interceptar fallos de login y devolver 403 cuando hay lockout.
    "axes.middleware.AxesMiddleware",
]

ROOT_URLCONF = "core.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "core.wsgi.application"

# Database
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", default="fvx_backend_db"),
        "USER": env("POSTGRES_USER", default="fvx_user"),
        "PASSWORD": env("POSTGRES_PASSWORD", default="fvx_password"),
        "HOST": env("POSTGRES_HOST", default="localhost"),
        "PORT": env("POSTGRES_PORT", default="5432"),
        "ATOMIC_REQUESTS": True,
    }
}

# Custom user model — declared from day zero so downstream projects can add
# fields with a routine makemigrations instead of a traumatic AUTH_USER_MODEL
# swap. Carries role, phone, photo_url, verified and ui_preferences (formerly
# the separate Profile model).
AUTH_USER_MODEL = "api.User"

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# ── Authentication backends ────────────────────────────────────────────
# AxesStandaloneBackend va PRIMERO: intercepta intentos fallidos antes de
# que ModelBackend valide credenciales. Si la cuenta está locked, devuelve
# 403 sin tocar la base. ModelBackend queda al final para credenciales
# normales user/password.
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

# ── Lockout (django-axes) — política contra brute-force ─────────────────
# Complementa al rate-limit:
# • Throttle (LoginIPRateThrottle/LoginUsernameRateThrottle): frena el RITMO.
# • Axes: bloquea la CUENTA por tiempo prolongado tras N fallos.
AXES_FAILURE_LIMIT = 5  # 5 fallos consecutivos → lockout
AXES_COOLOFF_TIME = 1  # bloqueo de 1 hora (horas, no segundos)
AXES_LOCKOUT_PARAMETERS = [["username"]]  # lockout por username (cubre IP rotation)
AXES_RESET_ON_SUCCESS = True  # login exitoso resetea el contador (mejor UX)
AXES_ENABLE_ACCESS_FAILURE_LOG = True  # AccessAttempt persistente en DB
# Respuesta cuando la cuenta está bloqueada: JSON 403 con mensaje claro
AXES_LOCKOUT_CALLABLE = "api.jwt.lockout.lockout_response"
# Para que el AxesMiddleware acepte el username del body JSON del login JWT
# (default lee de form-encoded), usamos un parser custom.
AXES_USERNAME_FORM_FIELD = "username"

# Internationalization
LANGUAGE_CODE = env("LANGUAGE_CODE", default="es")
TIME_ZONE = env("TIME_ZONE", default="America/Santiago")
USE_I18N = True
USE_L10N = True
USE_TZ = True

LANGUAGES = [
    ("es", "Español"),
    ("en", "English"),
]

LOCALE_PATHS = [
    BASE_DIR / "locale",
]

# Static files (CSS, JavaScript, Images)
# El backend de staticfiles se declara en el bloque `STORAGES` más abajo
# (Django 4.2+ unifica file storage y staticfiles en un solo dict).
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = []

# Media files (local FS — fallback cuando STORAGE_BACKEND='local').
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# ──────────────────────────────────────────────────────────────────────────────
# Storage (pluggable: local | s3 | gcs)
# Switch único vía env var ``STORAGE_BACKEND``. El front sube siempre al mismo
# endpoint Django (``POST /api/v1/uploads/``); el destino real lo decide aquí.
# Ver ``fvx-backend/docs/storage.md`` para configurar cada provider + CORS.
# ──────────────────────────────────────────────────────────────────────────────
STORAGE_BACKEND = env("STORAGE_BACKEND", default="local").lower()

# Tamaño máximo aceptado en el endpoint de upload (bytes). 25 MB por defecto.
# Para archivos > 100 MB conviene además subir el límite de nginx / gunicorn.
UPLOAD_MAX_BYTES = env.int("UPLOAD_MAX_BYTES", default=25 * 1024 * 1024)

# Allow-list de subida. Con STORAGE_BACKEND=s3/gcs las URLs devueltas son
# públicas en el mismo origen lógico de la marca: aceptar .html/.svg/.js
# permitiría XSS almacenado / phishing. Por eso el default NO incluye svg ni
# tipos ejecutables; un proyecto que necesite más los añade vía .env.
# La extensión es el control duro; el content-type declarado se valida si
# viene (es spoofeable — sniffing por magic-bytes queda como hardening futuro).
UPLOAD_ALLOWED_EXTENSIONS = [
    e.lower().lstrip(".")
    for e in env.list(
        "UPLOAD_ALLOWED_EXTENSIONS",
        default=["jpg", "jpeg", "png", "gif", "webp", "pdf"],
    )
]
UPLOAD_ALLOWED_CONTENT_TYPES = env.list(
    "UPLOAD_ALLOWED_CONTENT_TYPES",
    default=[
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
        "application/pdf",
    ],
)

# Subdirectorio raíz dentro del bucket / MEDIA_ROOT. Útil cuando varios
# proyectos comparten el mismo bucket (S3) o el mismo `media/` (dev), p. ej.
# ``STORAGE_BUCKET_PREFIX=community`` → todos los uploads viven bajo
# ``community/...`` en lugar de la raíz. Vacío (default) = sin prefijo.
STORAGE_BUCKET_PREFIX = env("STORAGE_BUCKET_PREFIX", default="").strip().strip("/")

if STORAGE_BACKEND == "s3":
    # S3-compatible: AWS, Backblaze B2, DigitalOcean Spaces, Wasabi, Cloudflare R2, MinIO…
    # Para non-AWS, set AWS_S3_ENDPOINT_URL al endpoint del proveedor.
    AWS_ACCESS_KEY_ID = env("AWS_ACCESS_KEY_ID", default="")
    AWS_SECRET_ACCESS_KEY = env("AWS_SECRET_ACCESS_KEY", default="")
    AWS_STORAGE_BUCKET_NAME = env("AWS_STORAGE_BUCKET_NAME", default="")
    AWS_S3_REGION_NAME = env("AWS_S3_REGION_NAME", default="us-east-1")
    AWS_S3_ENDPOINT_URL = env("AWS_S3_ENDPOINT_URL", default=None)
    AWS_DEFAULT_ACL = env("AWS_DEFAULT_ACL", default=None)  # None → bucket ACL
    AWS_QUERYSTRING_AUTH = env.bool("AWS_QUERYSTRING_AUTH", default=False)  # False → URLs públicas
    AWS_S3_FILE_OVERWRITE = False  # Genera sufijo si colisiona el filename.
    # django-storages: prepende `AWS_LOCATION/` a cada key.
    AWS_LOCATION = STORAGE_BUCKET_PREFIX

    STORAGES = {
        "default": {"BACKEND": "storages.backends.s3.S3Storage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }
elif STORAGE_BACKEND == "gcs":
    # Google Cloud Storage nativo (service account JSON).
    GS_BUCKET_NAME = env("GS_BUCKET_NAME", default="")
    GS_PROJECT_ID = env("GS_PROJECT_ID", default=None)
    GS_DEFAULT_ACL = env("GS_DEFAULT_ACL", default=None)
    GS_QUERYSTRING_AUTH = env.bool("GS_QUERYSTRING_AUTH", default=False)
    GS_FILE_OVERWRITE = False
    # django-storages: prepende `GS_LOCATION/` a cada blob name.
    GS_LOCATION = STORAGE_BUCKET_PREFIX
    # Lee creds desde GOOGLE_APPLICATION_CREDENTIALS (path al JSON) por convención SDK.

    STORAGES = {
        "default": {"BACKEND": "storages.backends.gcloud.GoogleCloudStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }
else:
    # 'local' (default): FileSystemStorage en MEDIA_ROOT. Ideal para dev.
    # Aplicamos el prefix como subdirectorio de MEDIA_ROOT + MEDIA_URL para que
    # rutas y URLs coincidan con el comportamiento de S3/GCS.
    if STORAGE_BUCKET_PREFIX:
        MEDIA_URL = f"/media/{STORAGE_BUCKET_PREFIX}/"
        MEDIA_ROOT = MEDIA_ROOT / STORAGE_BUCKET_PREFIX
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }

# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ─── API keys ──────────────────────────────────────────────────────────────
# Marca/prefijo de las API keys: ``<brand>.<prefix>.<secret>`` (p. ej.
# ``fvx.ab12….xyz…``). Configurable por env para que cada proyecto descendiente
# de la plantilla use su propia marca sin tocar código. Default ``fvx`` (compat).
# Solo letras/dígitos minúsculas; se normaliza para evitar puntos accidentales.
API_KEY_BRAND_PREFIX = env("API_KEY_BRAND_PREFIX", default="fvx").strip().lower()

# ─── Flow.cl (subscriptions / payments) ──────────────────────────────────────
# Credentials from the Flow merchant panel. FLOW_SANDBOX=True targets
# sandbox.flow.cl (test); set False for production (www.flow.cl). FLOW_API_BASE
# overrides the base URL if ever needed. See subscriptions/services/flow.py.
FLOW_API_KEY = env("FLOW_API_KEY", default="")
FLOW_SECRET_KEY = env("FLOW_SECRET_KEY", default="")
FLOW_SANDBOX = env.bool("FLOW_SANDBOX", default=True)
FLOW_API_BASE = env("FLOW_API_BASE", default="")

# ─── PayPal (suscripciones internacionales en USD) ───────────────────────────
# Flow es la pasarela principal (tarjetas chilenas, CLP). PayPal se ofrece como
# ALTERNATIVA INTERNACIONAL (clientes de Argentina, etc.) y cobra en USD, ya que
# PayPal no soporta CLP. El precio USD se deriva del precio CLP del plan dividido
# por PAYPAL_CLP_PER_USD (tipo de cambio configurable), salvo que el plan defina
# un precio USD propio. Credenciales desde developer.paypal.com → Apps & Creds.
# PAYPAL_SANDBOX=True usa api-m.sandbox.paypal.com; False = api-m.paypal.com.
PAYPAL_CLIENT_ID = env("PAYPAL_CLIENT_ID", default="")
PAYPAL_SECRET = env("PAYPAL_SECRET", default="")
PAYPAL_SANDBOX = env.bool("PAYPAL_SANDBOX", default=True)
PAYPAL_API_BASE = env("PAYPAL_API_BASE", default="")
# Webhook id (panel de PayPal) para verificar la firma de las notificaciones.
PAYPAL_WEBHOOK_ID = env("PAYPAL_WEBHOOK_ID", default="")
# Pesos chilenos por 1 USD usado para convertir el precio del plan a USD.
PAYPAL_CLP_PER_USD = env.int("PAYPAL_CLP_PER_USD", default=950)
# Nombre de marca mostrado en la pantalla de aprobación de PayPal.
PAYPAL_BRAND_NAME = env("PAYPAL_BRAND_NAME", default="Lita Donoso")

# Public base URLs used to build Flow redirect/return URLs.
# PUBLIC_API_BASE_URL: where Flow sends the customer back (this backend, browser-
# reachable). FRONTEND_BASE_URL: where we then redirect to show the result.
PUBLIC_API_BASE_URL = env("PUBLIC_API_BASE_URL", default="http://localhost:8080")
FRONTEND_BASE_URL = env("FRONTEND_BASE_URL", default="http://localhost:4201")

# ─── Zoom (sesiones en vivo embebidas con el Meeting SDK) ─────────────────────
# El miembro NO recibe un link de Zoom: el backend emite una firma de vida corta
# (subscriptions/services/zoom.py) solo si tiene el plan activo y estamos dentro
# de la franja horaria de la sesión. Credenciales desde marketplace.zoom.us → app
# tipo "Meeting SDK" (SDK Key / SDK Secret). Funciona con cuenta Zoom GRATIS para
# pruebas (límite de 40 min por reunión).
ZOOM_SDK_KEY = env("ZOOM_SDK_KEY", default="")
ZOOM_SDK_SECRET = env("ZOOM_SDK_SECRET", default="")
# Minutos ANTES de live_start en que se abre el acceso a la sala.
ZOOM_LIVE_OPEN_BEFORE_MIN = env.int("ZOOM_LIVE_OPEN_BEFORE_MIN", default=15)
# Duración por defecto (min) si la sesión no define live_end.
ZOOM_DEFAULT_DURATION_MIN = env.int("ZOOM_DEFAULT_DURATION_MIN", default=240)
# Candado de "entrada única en vivo": segundos que dura la marca de presencia de
# un miembro en una sesión Zoom. El frontend la renueva con un latido (~30s); si
# expira sin latido (cerró la pestaña), otro dispositivo puede entrar.
ZOOM_LIVE_LOCK_TTL = env.int("ZOOM_LIVE_LOCK_TTL", default=75)

# REST Framework
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "api.authentication.ApiKeyAuthentication",
        # JWTCookieAuthentication: lee primero de la cookie `fvx_access`, y
        # si no la encuentra cae al header `Authorization: Bearer ...` (útil
        # para Swagger, postman y API clients server-to-server).
        "api.authentication.JWTCookieAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    # Baseline anti-abuso para TODA la superficie API (antes solo login/social
    # tenían throttle; uploads y CRUD quedaban sin tope para un token válido o
    # una API key filtrada). UserRateThrottle/AnonRateThrottle aplican a todo;
    # ScopedRateThrottle solo a vistas que declaran ``throttle_scope`` (uploads).
    # Las vistas con ``throttle_classes`` propio (login, social) no se ven
    # afectadas. Rates pensados como piso razonable; cada proyecto los ajusta.
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.UserRateThrottle",
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.ScopedRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "user": env("THROTTLE_USER", default="2000/hour"),
        "anon": env("THROTTLE_ANON", default="120/hour"),
        "upload": env("THROTTLE_UPLOAD", default="60/hour"),
        "social": "30/hour",
        # Login (/api/auth/token/): protección contra credential stuffing y
        # brute force. Doble vector — la combinación AND devuelve 429 si
        # cualquiera de los dos se excede.
        "login_ip": "10/min",  # por IP: ~suficiente para usuarios reales (1-2 intentos)
        "login_user": "5/min",  # por username: frena ataque dirigido aunque roten IPs
        # Refresh (/api/auth/token/refresh/): más permisivo porque el cliente
        # lo dispara automáticamente, pero limita el abuso.
        "token_refresh": "60/hour",
    },
}

# Social login (Google / Apple / Microsoft id_token → JWT)
SOCIAL_AUTH_GOOGLE_ENABLED = env.bool("SOCIAL_AUTH_GOOGLE_ENABLED", default=False)
SOCIAL_AUTH_APPLE_ENABLED = env.bool("SOCIAL_AUTH_APPLE_ENABLED", default=False)
SOCIAL_AUTH_MICROSOFT_ENABLED = env.bool("SOCIAL_AUTH_MICROSOFT_ENABLED", default=False)
GOOGLE_OAUTH_CLIENT_ID = env("GOOGLE_OAUTH_CLIENT_ID", default="")
APPLE_CLIENT_ID = env("APPLE_CLIENT_ID", default="")
# Microsoft Entra ID: Application (client) ID del registro de app.
MICROSOFT_OAUTH_CLIENT_ID = env("MICROSOFT_OAUTH_CLIENT_ID", default="")
# Tenant: 'common' (multi-tenant + personales), 'organizations', 'consumers', o un
# GUID/dominio concreto. Define el issuer y el JWKS aceptados.
MICROSOFT_OAUTH_TENANT_ID = env("MICROSOFT_OAUTH_TENANT_ID", default="common")

# JWT Settings
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env.int("JWT_ACCESS_TOKEN_LIFETIME", default=60)),
    "REFRESH_TOKEN_LIFETIME": timedelta(
        minutes=env.int("JWT_REFRESH_TOKEN_LIFETIME", default=1440)
    ),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "AUTH_HEADER_NAME": "HTTP_AUTHORIZATION",
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "AUTH_TOKEN_CLASSES": ("rest_framework_simplejwt.tokens.AccessToken",),
    "TOKEN_TYPE_CLAIM": "token_type",
}

# ─── JWT cookies (P0 #3 del audit de seguridad) ───────────────────────────────
# El access + refresh viajan en cookies HttpOnly en vez de localStorage. Eso
# cierra el vector XSS principal — JavaScript no puede leer cookies HttpOnly,
# así que un script malicioso inyectado no puede exfiltrar el token.
#
# Política de prod (frontend + backend en la misma raíz de dominio, ej.
# `app.fvx-med.cl` + `api.fvx-med.cl`): SameSite=Strict + Secure=True. Para
# escenarios cross-site (cliente con su propio dominio apuntando a la API),
# subir `AUTH_COOKIE_SAMESITE=None` y `AUTH_COOKIE_SECURE=True` en el .env.
AUTH_COOKIE_ACCESS = "fvx_access"
AUTH_COOKIE_REFRESH = "fvx_refresh"
AUTH_COOKIE_SECURE = env.bool("AUTH_COOKIE_SECURE", default=not DEBUG)
AUTH_COOKIE_SAMESITE = env(
    "AUTH_COOKIE_SAMESITE", default="Lax"
)  # Lax dev | Strict prod | None cross-site
AUTH_COOKIE_DOMAIN = (
    env("AUTH_COOKIE_DOMAIN", default=None) or None
)  # None = origen actual; '.fvx-med.cl' para subdominios
AUTH_COOKIE_PATH_ACCESS = "/"  # se envía con cada request a la API
AUTH_COOKIE_PATH_REFRESH = "/api/auth/"  # restringido a endpoints de auth (refresh + logout)

# Guardrail: SameSite=None solo es válido con Secure=True (regla browser).
if AUTH_COOKIE_SAMESITE.lower() == "none" and not AUTH_COOKIE_SECURE:
    raise RuntimeError(
        "Seguridad: AUTH_COOKIE_SAMESITE=None requiere AUTH_COOKIE_SECURE=True "
        "(regla obligatoria de los browsers). Ajusta el .env."
    )

# ── CSRF (double-submit token para la auth por cookie) ──────────────────────
# La cookie de sesión (fvx_access) es ambiente: el browser la adjunta sola, así
# que JWTCookieAuthentication exige en requests mutantes un header X-CSRFToken
# que coincida con la cookie `csrftoken`. Esa cookie DEBE ser legible por JS
# (no HttpOnly) para que el front la copie al header. Sus atributos espejan los
# de la cookie de auth para comportarse igual en cross-site (SameSite=None →
# Secure). El front envía X-CSRFToken (ver csrf.interceptor.ts); el header por
# defecto de Django (HTTP_X_CSRFTOKEN) ya lo mapea.
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = AUTH_COOKIE_SAMESITE
CSRF_COOKIE_SECURE = AUTH_COOKIE_SECURE
CSRF_COOKIE_DOMAIN = AUTH_COOKIE_DOMAIN
# CSRF_TRUSTED_ORIGINS (definido arriba desde el .env) debe listar el origen del
# SPA cuando front y API viven en dominios distintos.

# CORS Settings
# Default-deny: el template arranca con allow-list (los orígenes dev de abajo),
# no con "abre a todos". Antes el default era True, que con
# CORS_ALLOW_CREDENTIALS=True deja la API abierta a cualquier dominio si alguien
# despliega sin tocar el .env. Para abrir todo en dev local, setear
# CORS_ALLOW_ALL_ORIGINS=True explícitamente en el .env.
CORS_ALLOW_ALL_ORIGINS = env.bool("CORS_ALLOW_ALL_ORIGINS", default=False)
CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS",
    default=[
        "http://localhost:4200",
        "http://localhost:4201",
        "http://localhost:3000",
    ],
)
CORS_ALLOW_CREDENTIALS = True

# Guardrail: CORS_ALLOW_ALL_ORIGINS=True + CORS_ALLOW_CREDENTIALS=True es una
# combinación peligrosa (deja la API abierta a cualquier dominio que mande
# cookies/Authorization). Solo es tolerable en dev (DEBUG=True). Si alguien
# despliega copiando el .env y olvida apagarlo en prod, la app NO arranca.
if not DEBUG and CORS_ALLOW_ALL_ORIGINS and CORS_ALLOW_CREDENTIALS:
    raise RuntimeError(
        "Seguridad: CORS_ALLOW_ALL_ORIGINS=True con CORS_ALLOW_CREDENTIALS=True "
        "no se permite cuando DEBUG=False. Setea CORS_ALLOW_ALL_ORIGINS=False y "
        "lista los origenes válidos en CORS_ALLOWED_ORIGINS."
    )
CORS_ALLOW_METHODS = [
    "DELETE",
    "GET",
    "OPTIONS",
    "PATCH",
    "POST",
    "PUT",
]
CORS_ALLOW_HEADERS = [
    "accept",
    "accept-encoding",
    "authorization",
    "content-type",
    "dnt",
    "origin",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
    "x-api-key",
    "x-request-id",
]

# DRF Spectacular (API Documentation)
SPECTACULAR_SETTINGS = {
    "TITLE": "FVX Template API",
    "DESCRIPTION": "Generic Django REST API (auth users, groups, roles, dynamic menu)",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    # Incluye `/api/v1/*` y `/api/auth/*` (JWT + social) en el esquema OpenAPI.
    "SCHEMA_PATH_PREFIX": "/api",
}

# Caching
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": env("REDIS_URL", default="redis://127.0.0.1:6379/0"),
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        },
    }
}

# Session
SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "default"

# Logging
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
        "file": {
            "class": "logging.FileHandler",
            "filename": BASE_DIR / "logs" / "django.log",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console", "file"],
            "level": "INFO",
            "propagate": False,
        },
    },
}

# ─── Email transaccional (notifications/) ─────────────────────────────────────
# Adapter pattern — ver fvx-backend/docs/email.md.
# Valores válidos: ``smtp`` (Mailpit local / cualquier SMTP), ``ses`` (Amazon
# SES en staging/prod), ``console`` (tests).
NOTIFICATIONS_EMAIL_ADAPTER = env("NOTIFICATIONS_EMAIL_ADAPTER", default="smtp")

# Sender
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="no-reply@local.test")
SERVER_EMAIL = env("SERVER_EMAIL", default=DEFAULT_FROM_EMAIL)

# SMTP (Mailpit local o cualquier proveedor SMTP genérico).
# Mailpit corre dentro de la red docker-compose en `mailpit:1025`. Para
# consumir desde host (manage.py shell del host) bastaría `localhost:1025`.
EMAIL_HOST = env("EMAIL_HOST", default="mailpit")
EMAIL_PORT = env.int("EMAIL_PORT", default=1025)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=False)
EMAIL_USE_SSL = env.bool("EMAIL_USE_SSL", default=False)

# Amazon SES — solo si NOTIFICATIONS_EMAIL_ADAPTER='ses'.
AWS_SES_ACCESS_KEY_ID = env("AWS_SES_ACCESS_KEY_ID", default="")
AWS_SES_SECRET_ACCESS_KEY = env("AWS_SES_SECRET_ACCESS_KEY", default="")
AWS_SES_REGION_NAME = env("AWS_SES_REGION_NAME", default="us-east-1")
AWS_SES_CONFIGURATION_SET = env("AWS_SES_CONFIGURATION_SET", default="")

# Auditoría: si se setea a True, ``EmailMessage.context_snapshot`` guarda
# también el HTML renderizado. Default off por peso y privacidad.
NOTIFICATIONS_PERSIST_BODY = env.bool("NOTIFICATIONS_PERSIST_BODY", default=False)

# Mailpit Web UI — solo dev. Lo expone ``MailTestView`` para que el botón
# "Abrir Mailpit" del showcase /components apunte al puerto correcto si el
# deployer mapeó Mailpit a uno distinto del 8025 estándar.
MAILPIT_URL = env("MAILPIT_URL", default="http://localhost:8025/")

# ─── Celery + Beat ────────────────────────────────────────────────────────────
# Redis ya está en el stack como broker + cache. Una vez configurado acá,
# notifications.tasks.send_email_task corre async por default — el helper
# `services.email._resolve_sync` detecta la disponibilidad y decide.
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://redis:6379/0")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default="redis://redis:6379/1")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
# Routing por dominio (ver architecture.md §6.6) — cada queue se escala
# independiente cuando crece volumen. Hoy: emails. Futuras: documents, ocr, bank.
CELERY_TASK_ROUTES = {
    "notifications.tasks.send_email_task": {"queue": "emails"},
}
CELERY_TASK_DEFAULT_QUEUE = "default"
# `acks_late` + prefetch 1 = workers no pierden tasks ante crash (importante para
# idempotency end-to-end con el decorator @idempotent — viene en Pass 2).
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1

# ─── Sentry (error tracking + traces) ─────────────────────────────────────────
# Solo se activa si SENTRY_DSN está seteado. Dev queda en blanco → no envía.
SENTRY_DSN = env("SENTRY_DSN", default="")
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.django import DjangoIntegration

    def _sentry_before_send(event, hint):
        """Sanitiza PII conocida del payload antes de mandar a Sentry."""
        req = event.get("request") or {}
        data = req.get("data")
        if isinstance(data, dict):
            for key in (
                "password",
                "new_password",
                "old_password",
                "tax_id",
                "rut",
                "bank_account",
            ):
                if key in data:
                    data[key] = "[REDACTED]"
        # También limpiar cookies (los tokens HttpOnly viajan acá).
        if isinstance(req.get("cookies"), dict):
            for k in ("fvx_access", "fvx_refresh"):
                if k in req["cookies"]:
                    req["cookies"][k] = "[REDACTED]"
        return event

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=env("SENTRY_ENVIRONMENT", default="local"),
        release=env("APP_VERSION", default="unknown"),
        integrations=[DjangoIntegration(), CeleryIntegration()],
        traces_sample_rate=env.float("SENTRY_TRACES_SAMPLE_RATE", default=0.1),
        send_default_pii=False,  # nunca mandar PII por default
        before_send=_sentry_before_send,
    )

# Create logs directory
os.makedirs(BASE_DIR / "logs", exist_ok=True)

# Security settings for production
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    CORS_ALLOW_ALL_ORIGINS = False
