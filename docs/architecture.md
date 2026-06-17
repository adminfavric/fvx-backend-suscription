# Arquitectura del proyecto sobre `code-master`

> **Audiencia**: dev backend que implementa sobre `code-master/fvx-backend`.
> **Estado**: aprobado
> **Última revisión**: 2026-05-28
> **Alcance**: piezas de infraestructura cross-módulo que aún NO están en
> `code-master`. Se asume conocimiento del stack base (Django 4.2 + DRF +
> Postgres + Redis + Angular 19 + Flutter).

---

## 1. Qué ya está y NO se toca

Antes de agregar nada, dejar claro qué de esto NO se reimplementa porque ya
existe en `code-master/`:

| Pieza | Doc de referencia |
|-------|-------------------|
| Notifications (email + SES + Mailpit + SNS webhook + adapters) | `fvx-backend/docs/email.md` |
| Storage de archivos pluggable (local / S3 / GCS) | `fvx-backend/docs/storage.md` |
| Blueprint multi-tenant con `Community` | `fvx-backend/docs/multi-tenant.md` |
| API + JWT + i18n + auth roles + auditoría + axes | `fvx-backend/docs/{API-Y-FRONTEND,I18N}.md` |
| Stack docker-compose (db + redis + mailpit + web) | `fvx-backend/docker-compose.yml` |
| CRUD base, BaseModelGeneric, TimeStampedModel | `fvx-backend/api/models/base.py` |
| Login social Google/Apple | `fvx-backend/docs/social-login-setup.md` |

**Reglas con la doc existente**:
- Si una decisión nueva contradice una de las docs anteriores, esa doc
  manda. Este archivo solo agrega lo que falta.
- Si hay duplicación: este archivo cita y NO repite.

---

## 2. Topología completa (consolidada)

```
┌────────────────────────────────────────────────────────────────────────┐
│  CLIENTES                                                              │
│  ┌────────────────┐  ┌────────────────┐  ┌──────────────────────────┐  │
│  │ Admin SPA      │  │ Portal         │  │ App móvil (lecturas)     │  │
│  │ Angular 19     │  │ Residente      │  │ Flutter                  │  │
│  │ (existe)       │  │ (Fase 3+)      │  │ (Fase 2.5)               │  │
│  └────────┬───────┘  └────────┬───────┘  └────────────┬─────────────┘  │
└───────────┼───────────────────┼───────────────────────┼────────────────┘
            │  HTTPS + JWT      │                       │
            ▼                   ▼                       ▼
┌────────────────────────────────────────────────────────────────────────┐
│  EDGE  ·  Nginx + Cloudflare                                           │
│  TLS · rate-limit · WAF · cache estáticos                              │
└────────────────────────────┬───────────────────────────────────────────┘
                             │
                             ▼
┌────────────────────────────────────────────────────────────────────────┐
│  BACKEND  ·  Django 4.2 + DRF  (Modular Monolith)                      │
│                                                                        │
│  apps/                                                                 │
│  ├── api/              ← stack base actual (auth, perms, menú)         │
│  ├── notifications/    ← infra cross-módulo (ya implementada)          │
│  ├── core/             ← nuevo: eventos, idempotency, health (Sec 3)   │
│  ├── tenancy/          ← nuevo: Community + middleware (Sec 4)         │
│  └── <comunidades, egresos, agendamientos, medidores>  ← negocio       │
│                                                                        │
│  Procesos:                                                             │
│  · Gunicorn (API HTTP)                                                 │
│  · Celery worker (jobs async)            ← NUEVO (Sec 6)               │
│  · Celery beat (cron)                    ← NUEVO (Sec 6)               │
└──┬──────────────┬─────────────────────┬──────────────┬────────────────┘
   │              │                     │              │
   ▼              ▼                     ▼              ▼
┌────────┐  ┌──────────┐  ┌─────────────────┐  ┌─────────────────────┐
│Postgres│  │ Redis    │  │ Object Storage  │  │ Servicios externos  │
│ multi  │  │ broker + │  │ (via storage.md │  │ via adapters (Sec 5)│
│ tenant │  │ cache    │  │  switch env)    │  │ - SES (email) ✅    │
│ por    │  │          │  │ - Backblaze     │  │ - OCR (futuro)      │
│ comm.  │  │          │  │ - S3 / GCS      │  │ - Webpay/Khipu      │
│ _id    │  │          │  │                 │  │ - Fintoc/Belvo      │
└────────┘  └──────────┘  └─────────────────┘  └─────────────────────┘

┌────────────────────────────────────────────────────────────────────────┐
│  OBSERVABILIDAD                                                        │
│  · Sentry (errores)                  ← NUEVO (Sec 7)                   │
│  · Healthcheck /health, /ready       ← NUEVO (Sec 8)                   │
│  · (Prometheus + Grafana Fase 2)                                       │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Convenciones de código nuevo

Todo módulo de negocio nuevo (`comunidades/`, `egresos/`, etc.) DEBE
respetar estas convenciones desde el primer commit.

### 3.1 Service layer obligatorio

```
apps/<dominio>/
├── models/             # Django ORM
├── serializers/        # DRF (solo transforma)
├── views/              # DRF viewsets (solo orquestan)
├── services/           # ← LÓGICA DE NEGOCIO VIVE ACÁ
│   ├── __init__.py
│   └── <subdominio>.py
├── adapters/           # adapters a servicios externos (si aplica)
├── signals.py
├── tasks.py            # Celery tasks del dominio
├── apps.py
├── urls.py
└── tests/
```

**Regla**: las views llaman a services, no manipulan ORM ni implementan
reglas de negocio. Cero `Model.objects.filter(...)` con lógica adentro
de un view. Las views son delgadas:

```python
# views/expenses.py
class ExpenseViewSet(viewsets.ModelViewSet):
    serializer_class = ExpenseSerializer

    def get_queryset(self):
        return expense_service.list_for_user(self.request)

    def perform_create(self, serializer):
        expense_service.create(
            community=self.request.community,
            user=self.request.user,
            **serializer.validated_data,
        )
```

```python
# services/expense.py
def create(*, community, user, category, amount, **rest) -> Expense:
    # toda la lógica acá: validaciones, side effects, eventos
    ...
```

**Por qué**: cuando mañana se decida extraer un servicio a microservicio,
solo se reemplaza la importación del service por un cliente HTTP. Las
views, serializers y URLs no cambian.

### 3.2 Cross-app vía service interfaces

NUNCA importar modelos de otra app directamente para queries de negocio.
Si `egresos` necesita lecturas de medidores:

```python
# ❌ MAL — acopla al ORM de otro dominio
from apps.medidores.models import MeterReading
readings = MeterReading.objects.filter(...)
```

```python
# ✅ BIEN — usa la interfaz pública del otro dominio
from apps.medidores.services.readings import get_period_readings
readings = get_period_readings(community=c, period="2026-05", meter_type="HOT_WATER")
```

**Por qué**: el día que `apps/medidores/` se extraiga a un microservicio,
`get_period_readings(...)` cambia su body (de query SQL a llamada HTTP).
El caller no se entera.

### 3.3 Eventos de dominio (wrapper de signals)

En vez de usar `django.dispatch.Signal` directo, usar el wrapper de
`apps/core/events.py` (a crear, ver Sec 6):

```python
# apps/egresos/services/billing.py
from apps.core.events import dispatch

def close_period(community, period):
    bp = ...
    dispatch("billing_period.closed", billing_period=bp, community=community)
    return bp
```

Otros módulos se suscriben:

```python
# apps/notifications/listeners.py
from apps.core.events import on

@on("billing_period.closed")
def send_colilla_emails(*, billing_period, **_):
    for charge in billing_period.unit_charges.all():
        ...
```

**Por qué**: hoy `dispatch()` es un wrapper de `Signal.send()`. Mañana es
un publish a RabbitMQ o Kafka — la firma no cambia.

### 3.4 Multi-tenant: `Community` siempre primero

Toda app de negocio hereda de `TenantScopedModel` (ya documentado en
`multi-tenant.md`). Ver Sec 4 para qué falta implementar.

### 3.5 Idempotencia en mutaciones críticas

Endpoints que reciben webhooks (SES SNS, Webpay, Fintoc) o que mutan
estado financiero deben ser idempotentes vía clave única. Ver Sec 9.

---

## 4. Multi-tenant — terminar la implementación

Ya hay blueprint completo en `fvx-backend/docs/multi-tenant.md`. Lo que
falta hacer para que el primer módulo de negocio (`comunidades/`) lo use:

### 4.1 Decisión confirmada

| Cosa | Valor |
|---|---|
| Nombre del tenant | **`Community`** |
| Relación user ↔ tenant | M2M vía `CommunityMembership` |
| Cómo viaja | Header `X-Community-ID` |
| Persistencia activa | `Profile.last_active_community_id` |
| Modelo base | `TenantScopedModel` |
| ViewSet mixin | `TenantScopedViewSetMixin` |

### 4.2 Pasos de implementación (extraídos de `multi-tenant.md`)

1. **Crear app `tenancy/`** (NO mezclar con `api/`):
   ```
   apps/tenancy/
   ├── models/
   │   ├── community.py            # Community
   │   └── membership.py           # CommunityMembership
   ├── middleware.py               # CommunityScopeMiddleware
   ├── mixins.py                   # TenantScopedModel, TenantScopedViewSetMixin
   └── tests/
       └── test_isolation.py       # Test CI: ningún modelo escape sin scope
   ```
2. **Agregar middleware** a `MIDDLEWARE` en `core/settings.py`:
   ```python
   "apps.tenancy.middleware.CommunityScopeMiddleware",
   ```
3. **Test CI obligatorio** (`apps/tenancy/tests/test_isolation.py`): que
   recorre todos los modelos y exige `TenantScopedModel` o whitelist
   explícita (la whitelist está en el doc).
4. **Documentar la whitelist** en el mismo test:
   ```python
   TENANT_UNSCOPED_WHITELIST = {
       "User", "Profile", "Notification", "EmailMessage", "EmailSuppression",
       "MenuItem", "MenuSection", "ApiKey", "SocialAccount",
       "Community", "CommunityMembership",  # el tenant mismo
       "LogEntry",
   }
   ```

### 4.3 Particionamiento futuro

Hoy 1 DB compartida con `community_id` en cada tabla. Cuando una comunidad
supere los ~10k Units o las tablas hot (lecturas, transacciones) crezcan
mucho, particionar Postgres por `community_id`:

```sql
-- Plan futuro, no hacer aún
CREATE TABLE meter_readings (...) PARTITION BY HASH (community_id);
```

No es una decisión a tomar ahora, pero el modelado con `community_id` en
cada tabla deja la puerta abierta.

---

## 5. Adapter pattern — formalizar la convención

`code-master` ya usa el patrón en dos lugares:
- `notifications/adapters/{base,ses,smtp,console}.py` — para email
- `STORAGE_BACKEND` env var (local/s3/gcs) — para object storage

Falta **formalizar la convención** para que el otro AI (y los que vengan)
lo apliquen consistente cuando agreguen integraciones a OCR, pagos, banco,
push.

### 5.1 Estructura estándar

```
apps/<dominio>/adapters/
├── __init__.py          # factory get_<dominio>_adapter()
├── base.py              # Protocol + Payload dataclass + Error
├── <proveedor1>.py      # implementación A
├── <proveedor2>.py      # implementación B
└── console.py           # para tests / debug local
```

### 5.2 Plantilla

```python
# apps/<dominio>/adapters/base.py
from dataclasses import dataclass
from typing import Protocol

@dataclass
class XPayload:
    ...

class XAdapter(Protocol):
    def do_something(self, payload: XPayload) -> str: ...

class XError(Exception):
    def __init__(self, msg: str, *, is_transient: bool = False):
        super().__init__(msg)
        self.is_transient = is_transient
```

```python
# apps/<dominio>/adapters/__init__.py
from django.conf import settings
from .console import ConsoleXAdapter
from .provider1 import Provider1XAdapter
from .provider2 import Provider2XAdapter

_ADAPTERS = {
    "console": ConsoleXAdapter,
    "provider1": Provider1XAdapter,
    "provider2": Provider2XAdapter,
}

_instance = None

def get_x_adapter():
    global _instance
    if _instance is None:
        name = getattr(settings, "X_ADAPTER", "console")
        _instance = _ADAPTERS[name]()
    return _instance

def reset_x_adapter():  # para tests
    global _instance
    _instance = None
```

### 5.3 Convenciones de env vars

```
<DOMINIO>_ADAPTER=<nombre>           # ej. OCR_ADAPTER=gemini, PAYMENTS_ADAPTER=webpay
<DOMINIO>_<PROVIDER>_API_KEY=...
<DOMINIO>_<PROVIDER>_<OTRA_CONF>=...
```

### 5.4 Casos a implementar (cuando llegue cada módulo)

| Dominio | Proveedores planeados |
|---|---|
| Email | `ses`, `smtp`, `console` ✅ (ya implementado) |
| Storage | `local`, `s3`, `gcs` ✅ (ya implementado) |
| OCR | `gemini`, `google_vision`, `tesseract`, `console` — Fase 2.5 |
| Payments | `webpay`, `khipu`, `console` — Fase 2 |
| Bank | `fintoc`, `belvo`, `manual`, `console` — Fase 2 |
| Push | `fcm`, `apns`, `webpush`, `console` — Fase 3+ |

Cada uno se agrega cuando el módulo correspondiente lo necesite, no antes.

---

## 6. Celery + Beat — agregar al stack

Redis ya está en `docker-compose.yml`. La task `send_email_task` está
escrita pero con stub para cuando Celery no esté instalado. Toca agregarlo.

### 6.1 Cambios en `requirements.txt`

```python
celery==5.3.6
django-celery-beat==2.5.0   # tasks programadas en la BD (cron del cierre)
django-celery-results==2.5.1  # opcional: persistir resultados
```

### 6.2 `core/celery.py` (nuevo)

```python
import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

app = Celery("fvx_backend")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

@app.task(bind=True)
def debug_task(self):
    print(f"Request: {self.request!r}")
```

### 6.3 `core/__init__.py`

```python
from .celery import app as celery_app

__all__ = ("celery_app",)
```

### 6.4 `core/settings.py` — agregar bloque

```python
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://redis:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://redis:6379/1")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE   # ya definido
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
CELERY_TASK_ROUTES = {
    "notifications.tasks.send_email_task": {"queue": "emails"},
    # futuras: meter OCR a "ocr", PDFs a "documents", etc.
}
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TASK_ACKS_LATE = True              # importante para idempotencia
CELERY_WORKER_PREFETCH_MULTIPLIER = 1     # evita perder tasks si un worker muere
```

### 6.5 `docker-compose.yml` — agregar servicios

```yaml
  celery_worker:
    build: .
    container_name: fvx_suscription_backend_celery_worker
    command: celery -A core worker -l info -Q default,emails
    volumes:
      - .:/app
    env_file:
      - .env
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    networks:
      - internal

  celery_beat:
    build: .
    container_name: fvx_suscription_backend_celery_beat
    command: celery -A core beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
    volumes:
      - .:/app
    env_file:
      - .env
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    networks:
      - internal
```

### 6.6 Convención de queues

| Queue | Uso |
|---|---|
| `default` | Catch-all |
| `emails` | Envío de emails (ya configurado) |
| `documents` | Generación de PDFs (futuro: colillas, reportes) |
| `ocr` | Procesamiento OCR de lecturas (futuro) |
| `bank` | Sincronización con Fintoc/Belvo (futuro) |
| `reports` | Reportes pesados / exports masivos |

Cada queue se escala independiente cuando crece el volumen.

### 6.7 Producción

- Ejecutar 1 worker por queue crítica (`emails`, `ocr`, `documents`).
- Beat solo en UNA instancia (lock vía Postgres con `django-celery-beat`).
- Monitoreo: Flower (opcional Fase 2) o métricas Prometheus de Celery.

---

## 7. Sentry — observabilidad mínima

### 7.1 Cambios en `requirements.txt`

```
sentry-sdk[django]==2.8.0
```

### 7.2 `core/settings.py`

```python
import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.celery import CeleryIntegration

SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=os.environ.get("SENTRY_ENVIRONMENT", "local"),
        release=os.environ.get("APP_VERSION", "unknown"),
        integrations=[DjangoIntegration(), CeleryIntegration()],
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
        send_default_pii=False,        # privacy: no PII por default
    )
```

### 7.3 `.env` por ambiente

```bash
# .env.local        → vacío (no enviar)
# .env.staging      → SENTRY_DSN=https://...sentry.io/...    SENTRY_ENVIRONMENT=staging
# .env.production   → SENTRY_DSN=https://...sentry.io/...    SENTRY_ENVIRONMENT=production
```

### 7.4 Qué reporta automáticamente

- Excepciones no capturadas en views, services, tasks Celery.
- Performance traces (10% de requests por default).
- Errores SQL lentos.

### 7.5 Qué NO mandar a Sentry

`send_default_pii=False` ya filtra request body y cookies. Además:

```python
def before_send(event, hint):
    # Sanitizar campos sensibles
    if "request" in event and "data" in event["request"]:
        data = event["request"]["data"]
        for key in ("password", "tax_id", "bank_account"):
            if key in data:
                data[key] = "[REDACTED]"
    return event

sentry_sdk.init(..., before_send=before_send)
```

---

## 8. Healthcheck endpoints

Necesarios para load balancer / k8s. Endpoints separados:

### 8.1 Crear `apps/core/` (si no existe)

```
apps/core/
├── __init__.py
├── apps.py
├── views.py          # health, ready
└── urls.py
```

### 8.2 Vistas

```python
# apps/core/views.py
from django.conf import settings
from django.db import connection
from django.http import JsonResponse
import redis


def health(request):
    """Liveness — el proceso responde. NO toca BD ni Redis."""
    return JsonResponse({"status": "ok"})


def ready(request):
    """Readiness — verifica dependencias críticas."""
    checks = {}
    overall = True

    # Postgres
    try:
        with connection.cursor() as c:
            c.execute("SELECT 1")
        checks["postgres"] = "ok"
    except Exception as e:
        checks["postgres"] = f"error: {e}"
        overall = False

    # Redis
    try:
        r = redis.Redis.from_url(settings.CELERY_BROKER_URL, socket_timeout=2)
        r.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"
        overall = False

    status = 200 if overall else 503
    return JsonResponse({"status": "ok" if overall else "degraded", "checks": checks},
                         status=status)
```

### 8.3 URLs

```python
# apps/core/urls.py
from django.urls import path
from .views import health, ready

urlpatterns = [
    path("health/", health),     # GET /api/health/
    path("ready/", ready),       # GET /api/ready/
]
```

Sin auth (load balancer no manda JWT). Listar en `core/urls.py`:

```python
path("api/", include("apps.core.urls")),
```

---

## 9. Idempotencia para webhooks y mutaciones críticas

Webhooks externos (SES SNS, Webpay, Fintoc/Belvo) duplican requests con
frecuencia. Necesitamos rechazar duplicados.

### 9.1 Modelo

```python
# apps/core/models/idempotency.py
from django.db import models


class IdempotencyKey(models.Model):
    """Cada operación idempotente registra su clave única acá."""
    key = models.CharField(max_length=120, unique=True, db_index=True)
    scope = models.CharField(max_length=40, db_index=True)
    response_status = models.IntegerField()
    response_body = models.JSONField(default=dict, blank=True)
    created = models.DateTimeField(auto_now_add=True)
```

### 9.2 Decorator

```python
# apps/core/idempotency.py
from functools import wraps
from django.http import JsonResponse
from .models import IdempotencyKey


def idempotent(*, scope: str, key_from):
    """
    Decorator para vistas con efectos. `key_from(request)` extrae la clave.

    Uso:
        @idempotent(scope="ses-webhook", key_from=lambda req: json.loads(req.body)["MessageId"])
        def ses_webhook(request): ...

        @idempotent(scope="webpay-confirm",
                    key_from=lambda req: req.POST["token_ws"])
        def webpay_confirm(request): ...
    """
    def wrapper(view):
        @wraps(view)
        def inner(request, *args, **kwargs):
            try:
                key = key_from(request)
            except Exception:
                return JsonResponse({"detail": "missing idempotency key"}, status=400)

            existing = IdempotencyKey.objects.filter(scope=scope, key=key).first()
            if existing:
                return JsonResponse(
                    existing.response_body, status=existing.response_status)

            response = view(request, *args, **kwargs)
            try:
                body = response.content.decode()
            except Exception:
                body = {}
            IdempotencyKey.objects.create(
                scope=scope, key=key,
                response_status=response.status_code,
                response_body=body if isinstance(body, dict) else {"raw": body[:1000]},
            )
            return response
        return inner
    return wrapper
```

### 9.3 Limpieza

Las claves de webhooks pueden purgarse después de 30 días. Beat task:

```python
# apps/core/tasks.py
from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from .models import IdempotencyKey

@shared_task
def cleanup_old_idempotency_keys():
    cutoff = timezone.now() - timedelta(days=30)
    IdempotencyKey.objects.filter(created__lt=cutoff).delete()
```

---

## 10. Domain event bus (wrapper de signals)

Hoy es trivial — wrapper sobre Django signals. Mañana se cambia el body
por un publisher a RabbitMQ sin que los callers se enteren.

### 10.1 `apps/core/events.py`

```python
import logging
from django.dispatch import Signal

logger = logging.getLogger(__name__)

_EVENTS: dict[str, Signal] = {}


def _get(name: str) -> Signal:
    if name not in _EVENTS:
        _EVENTS[name] = Signal()
    return _EVENTS[name]


def dispatch(event: str, **payload) -> None:
    """Publica un evento de dominio. Llamado por services."""
    logger.info("event=%s payload=%s", event, list(payload.keys()))
    _get(event).send(sender=event, **payload)


def on(event: str):
    """
    Decorator para suscribirse a un evento.

    Uso:
        from apps.core.events import on

        @on("billing_period.closed")
        def send_colilla_emails(*, billing_period, **_):
            ...
    """
    def wrapper(fn):
        _get(event).connect(lambda sender, **kw: fn(**kw),
                             weak=False,
                             dispatch_uid=f"{event}:{fn.__module__}.{fn.__name__}")
        return fn
    return wrapper
```

### 10.2 Convención de nombres

`<dominio>.<acción_pasada>` minúsculas con underscore:

| Evento | Disparado por |
|---|---|
| `billing_period.closed` | `egresos.services.billing.close_period()` |
| `meter_reading.confirmed` | `medidores.services.readings.confirm()` |
| `reservation.created` | `agendamientos.services.reservations.create()` |
| `unit_payment.received` | `egresos.services.payments.record()` |

### 10.3 Listeners

Cada app que reaccione a eventos tiene un `listeners.py` cargado en `ready()`:

```python
# apps/notifications/apps.py
class NotificationsConfig(AppConfig):
    name = "apps.notifications"
    def ready(self):
        from . import listeners   # noqa
```

```python
# apps/notifications/listeners.py
from apps.core.events import on

@on("billing_period.closed")
def send_colilla_emails(*, billing_period, **_):
    ...

@on("reservation.created")
def send_reservation_confirmation(*, reservation, **_):
    ...
```

---

## 11. Estructura final esperada del backend

Tras aplicar todo lo anterior:

```
fvx-backend/
├── api/                    # ya existe (auth, perms, menú, base models)
├── notifications/          # ya implementada (email.md)
├── apps/
│   ├── core/               # NUEVO — events, idempotency, health
│   │   ├── events.py
│   │   ├── idempotency.py
│   │   ├── models/
│   │   │   └── idempotency.py
│   │   ├── tasks.py        # cleanup_old_idempotency_keys
│   │   ├── views.py        # health, ready
│   │   └── urls.py
│   ├── tenancy/            # NUEVO — Community + middleware (per multi-tenant.md)
│   │   ├── models/
│   │   ├── middleware.py
│   │   ├── mixins.py
│   │   └── tests/
│   ├── comunidades/        # FUTURO (módulo de negocio)
│   ├── egresos/            # FUTURO
│   ├── agendamientos/      # FUTURO
│   └── medidores/          # FUTURO
├── core/
│   ├── settings.py
│   ├── celery.py           # NUEVO
│   ├── urls.py
│   └── wsgi.py
├── docker-compose.yml      # actualizar: celery_worker, celery_beat
├── requirements.txt        # actualizar: celery, sentry-sdk, django-celery-beat
└── docs/
    ├── email.md            # ya está
    ├── storage.md          # ya está
    ├── multi-tenant.md     # ya está (terminar implementación)
    ├── i18n.md             # ya está
    └── architecture.md     # este archivo, copia desde community-project
```

---

## 12. Checklist de implementación

### Sprint 0 — Infra base (1 semana)
- [ ] Agregar `celery`, `django-celery-beat`, `sentry-sdk[django]` a `requirements.txt`
- [ ] Crear `core/celery.py` + settings CELERY_*
- [ ] Agregar servicios `celery_worker` y `celery_beat` a `docker-compose.yml`
- [ ] Verificar que `notifications.tasks.send_email_task` funcione async
- [ ] Crear `apps/core/` con `events.py`, `idempotency.py`, `models/`, `views.py`, `tasks.py`
- [ ] Aplicar decorator `@idempotent` al webhook SNS de notifications
- [ ] Crear health/ready endpoints
- [ ] Setup Sentry con DSN por ambiente (puede quedarse vacío en local)

### Sprint 1 — Multi-tenant (3-5 días)
- [ ] Crear app `apps/tenancy/` per `docs/multi-tenant.md`:
  - [ ] Modelos `Community` y `CommunityMembership`
  - [ ] `CommunityScopeMiddleware`
  - [ ] `TenantScopedModel` y `TenantScopedViewSetMixin`
- [ ] Agregar middleware a settings
- [ ] Test CI `test_isolation.py` que enforza el patrón
- [ ] Migración: poblar `Community` por defecto para usuarios existentes

### Sprint 2 — Convenciones documentadas
- [ ] Documentar service layer en `docs/CONVENCIONES.md` con ejemplo end-to-end
- [ ] Refactorear `notifications/listeners.py` para usar `apps.core.events.on(...)`
- [ ] Hacer linting que rechace `from apps.<x>.models import` desde fuera de la app `x`
  (ruff custom rule o test simple)

### Sprint 3 — Primer módulo de negocio
- [ ] `apps/comunidades/` siguiendo todas las convenciones
- [ ] Validar end-to-end: crear Community, asignar membership, llamar API con header

---

## 13. Lo que NO hacer

- ❌ **No implementar microservicios todavía**. Modular monolith hasta que el cierre de periodo lo justifique extraer algo.
- ❌ **No crear apps fuera de `apps/`** (excepto `api/` y `notifications/` que ya existen en raíz por compatibilidad histórica). Toda app nueva va bajo `apps/`.
- ❌ **No saltarse el service layer**. Lógica de negocio NUNCA en views ni serializers.
- ❌ **No importar modelos de otra app de negocio**. Siempre via `services.*`.
- ❌ **No agregar tasks Celery sin queue específica**. Si todo va a `default`, no hay forma de escalar.
- ❌ **No mandar PII a Sentry**. `send_default_pii=False` + `before_send` que redacta.
- ❌ **No exponer `/health` con auth**. El load balancer no manda JWT.
- ❌ **No olvidar `@idempotent` en webhooks**. Sin esto SES y Webpay duplican operaciones.

---

## 14. Referencias

- [`fvx-backend/docs/email.md`](../../fvx-med/code-master/fvx-backend/docs/email.md) — Email transaccional
- [`fvx-backend/docs/storage.md`](../../fvx-med/code-master/fvx-backend/docs/storage.md) — Object storage
- [`fvx-backend/docs/multi-tenant.md`](../../fvx-med/code-master/fvx-backend/docs/multi-tenant.md) — Blueprint multi-tenant
- [`fvx-backend/docs/api-and-frontend.md`](../../fvx-med/code-master/fvx-backend/docs/api-and-frontend.md) — Contrato con Angular
- [`fvx-backend/docs/i18n.md`](../../fvx-med/code-master/fvx-backend/docs/i18n.md) — i18n full stack
- [Celery best practices](https://docs.celeryq.dev/en/stable/userguide/index.html)
- [Sentry Django integration](https://docs.sentry.io/platforms/python/integrations/django/)
- Patrón "Modular Monolith": Shopify, Basecamp, GitHub.
