# FVX Template — Backend API

API Django REST Framework para la plantilla base (`code-master/fvx-backend/`): autenticación JWT, usuarios, grupos, organizaciones, menú dinámico y piezas transversales.

> **Rama plantilla (`code-master/fvx-backend/`):** la app `api` incluye menú dinámico (**`Menu` → `MenuSection` → `MenuItem`**) y **`GET /api/v1/menus/tree/`** (filtrado por roles permitidos por ítem; ver `api/roles.py`), uso de **`django-model-utils`** en timestamps y soft delete, y migraciones con semilla de menú por defecto. Estado y roadmap del template: [`../PLAN_TEMPLATE.md`](../PLAN_TEMPLATE.md).

**Documentación de desarrollo** (índice, acoplamiento con Angular, i18n del servidor): carpeta **[`docs/`](docs/README.md)**.  
KPIs del shell (`/dashboard` en Angular): **[`docs/dashboard-stats.md`](docs/dashboard-stats.md)** y endpoint **`GET /api/v1/stats/`** (JWT).

## 🚀 Características

- ✅ Django 4.2 + Django REST Framework
- ✅ PostgreSQL (motor estándar; sin PostGIS en el template base)
- ✅ Autenticación JWT (access + refresh tokens)
- ✅ Internacionalización (Español/Inglés)
- ✅ CORS configurado
- ✅ Docker + Docker Compose
- ✅ API Documentation (Swagger/ReDoc)
- ✅ Soft Delete en modelos críticos
- ✅ Audit logging
- ✅ Redis para caching

## 📋 Requisitos Previos

- Docker y Docker Compose
- Git

## 🛠️ Instalación y Configuración

### 1. Clonar el repositorio

```bash
cd backend
```

### 2. Configurar variables de entorno

```bash
cp .env.example .env
# Editar .env con tus configuraciones
```

### 3. Iniciar el proyecto (LOCAL)

```bash
chmod +x start.sh update.sh restart.sh
./start.sh local
```

Esto hará:
- Crear contenedores Docker (PostgreSQL, Redis, Django)
- Ejecutar migraciones
- Crear superusuario (admin/admin123)
- Recopilar archivos estáticos
- Compilar mensajes de traducción

### 4. Acceder a los servicios

- **API**: http://localhost:8080
- **Admin**: http://localhost:8080/admin
- **API Docs (Swagger)**: http://localhost:8080/api/docs/
- **API Docs (ReDoc)**: http://localhost:8080/api/redoc/
- **PostgreSQL**: localhost:5432
- **Redis**: localhost:6379

**Credenciales por defecto:**
- Username: `admin`
- Password: `admin123`

## 📚 Estructura del Proyecto

```
fvx-backend/
├── core/                  # Configuración principal Django
│   ├── settings.py       # Configuración unificada
│   ├── urls.py           # URLs principales
│   ├── wsgi.py
│   └── asgi.py
├── api/                   # App única con toda la lógica
│   ├── models/           # Modelos (ver sección “Extensión” más abajo)
│   │   ├── base.py       # Modelos de la plantilla
│   │   └── __init__.py  # importa `base` y, si aplica, módulos propios
│   ├── serializers/    # Serializers DRF (un módulo por dominio o feature)
│   │   └── __init__.py  # reexporta clases para `from api.serializers import …`
│   ├── views/            # ViewSets y APIViews
│   │   └── __init__.py  # reexporta clases para `from api.views import …`
│   ├── urls.py           # Routing API
│   ├── admin.py          # Django Admin
│   ├── admin_forms/     # Formularios/widgets del admin (iconos, menú)
│   ├── jwt/              # Login JWT (SimpleJWT: serializer + vista)
│   ├── openapi/         # Extensiones drf-spectacular (p. ej. esquema Api-Key)
│   ├── permissions/   # Clases de permisos DRF
│   ├── shell/            # Métricas dashboard, preferencias UI del shell
│   ├── signals.py        # Django signals
│   ├── authentication.py # Autenticación (Api-Key en producción; string en settings)
│   ├── choices.py, roles.py  # Catálogos y reglas de rol
│   ├── utils.py          # Funciones auxiliares
│   ├── migrations/       # Migraciones de BD
│   └── management/       # Comandos personalizados
│       └── commands/
├── locale/               # Archivos de traducción (es/en)
├── static/
├── media/
├── logs/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── manage.py
```

### Extensión: dónde guardar código personalizado

La plantilla organiza el código en **paquetes** (carpetas con `__init__.py`). Al añadir entidades propias, conviene **seguir el mismo criterio** para que el repositorio siga siendo fácil de navegar y de fusionar con actualizaciones del template.

| Qué añades | Dónde colocarlo | Cómo integrarlo |
|------------|-----------------|-----------------|
| **Modelos** nuevos | `api/models/<nombre>.py` (o varios archivos por dominio) | Importar las clases en `api/models/__init__.py` (p. ej. `from .mi_dominio import *`) para que Django las descubra al cargar la app. Luego `makemigrations` / `migrate`. |
| **Serializers** | `api/serializers/<nombre>.py` | Exportar las clases en `api/serializers/__init__.py` con `__all__` o imports explícitos, para que sigan funcionando `from api.serializers import MiSerializer`. |
| **Vistas** (ViewSets, APIView) | `api/views/<nombre>.py` | Reexportar en `api/views/__init__.py` y registrar rutas en `api/urls.py` (router o `path(...)`). |
| **Auth JWT** (token / mensajes) | `api/jwt/serializers.py`, `api/jwt/views.py` (exportar en `api/jwt/__init__.py`) | `core/urls.py` importa p. ej. `from api.jwt import FvxTokenObtainPairView`. |
| **Permisos DRF** | `api/permissions/drf.py` (nuevas clases) + `api/permissions/__init__.py` | Sigue aplicando `from api.permissions import IsAdminOrReadOnly`. |
| **OpenAPI / Spectacular** | `api/openapi/extensions.py` | `api.apps` ya hace `import api.openapi` para registrar extensiones. |
| **Dashboard (KPIs)** o **preferencias de UI** | `api/shell/dashboard_stats.py`, `api/shell/ui_preferences.py` | Las vistas usan `api.shell…`; al extender KPIs ver `docs/dashboard-stats.md`. |
| **Formularios del admin** (menú, iconos) | `api/admin_forms/` | `api/admin.py` importa `MenuItemAdminForm` desde `api.admin_forms`. |
| **Lógica auxiliar** reutilizable | `api/utils.py` o módulos bajo `api/shell/`, `api/…` | Importar desde vistas o serializers. |
| **Comandos** | `api/management/commands/<nombre>.py` | `python manage.py <nombre>`. |
| **Admin (ModelAdmin)** | `api/admin.py` | Registrar `ModelAdmin` y, si aplica, formularios en `api/admin_forms/`. |

**Resumen:** un archivo (o pocos) por dominio dentro de `models/`, `serializers/` y `views/`; el **`__init__.py`** de cada paquete actúa como fachada estable para el resto del código (`urls`, tests, `openapi`).

**Qué suele quedarse en la raíz de `api/`:** `apps.py`, `urls.py`, `admin.py`, `signals.py`, `authentication.py` (la ruta en cadena `api.authentication.ApiKeyAuthentication` también la usa OpenAPI y settings), `choices.py`, `roles.py`, `utils.py` — son pocos archivos compartidos o referenciados por string; si un módulo crece mucho, se puede extraer a un paquete siguiendo el mismo patrón.

## 🔐 Autenticación

### Obtener tokens

```bash
POST /api/auth/token/
{
  "username": "admin",
  "password": "admin123"
}

Response:
{
  "access": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc..."
}
```

### Refrescar token

```bash
POST /api/auth/token/refresh/
{
  "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc..."
}
```

### Usar token en requests

```bash
Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc...
```

## 📡 Endpoints principales (plantilla)

Expuestos bajo el prefijo típico **`/api/v1/`** (ver `api/urls.py` y esquema OpenAPI en `/api/docs/`):

- **Auth (JWT):** `POST /api/auth/token/`, `POST /api/auth/token/refresh/`
- **Usuarios y perfiles:** `GET/POST/PATCH …/users/`, `GET/PATCH …/users/me/`, `…/profiles/`
- **Grupos (Django auth):** `…/groups/`
- **Organizaciones y membresías:** `…/organizations/`
- **Menú:** `…/menus/` y **`GET …/menus/tree/`** (árbol filtrado por rol)
- **División geográfica (referencia):** `…/geographic-divisions/`
- **API keys:** `…/api-keys/`
- **Ajustes UI (cuando exista el endpoint):** `GET/PATCH …/settings/ui/`

**Nota:** operaciones CRUD estándar de DRF:
- `GET` - Listar (con paginación)
- `POST` - Crear
- `GET /{id}/` - Detalle
- `PUT /{id}/` - Actualizar completo
- `PATCH /{id}/` - Actualizar parcial
- `DELETE /{id}/` - Eliminar (soft delete donde aplique)

## 🌍 Internacionalización

### Cambiar idioma

Enviar header `Accept-Language`:
```bash
Accept-Language: es  # Español
Accept-Language: en  # English
```

### Crear/Actualizar traducciones

```bash
# Generar archivos de traducción
docker-compose exec web python manage.py makemessages -l es
docker-compose exec web python manage.py makemessages -l en

# Compilar traducciones
docker-compose exec web python manage.py compilemessages
```

## 🔧 Comandos Útiles

### Scripts de gestión

```bash
./start.sh local      # Iniciar en modo desarrollo
./start.sh remote     # Iniciar en modo producción
./update.sh           # Actualizar sistema
./restart.sh          # Reiniciar contenedores
```

### Docker Compose

**Nombre del proyecto en Docker Desktop / `docker compose ls`:** en `docker-compose.yml` hay un bloque `name:` que lee **`COMPOSE_PROJECT_NAME`** del **`.env`** (`.env.example`: `COMPOSE_PROJECT_NAME=fvx_backend`). Tras **`install.sh`**, suele ser `<prefijo>_<clave>_backend` (p. ej. `fvx_community_backend`). Los **volúmenes y la red interna** usan **claves cortas** (`postgres_data`, `static_volume`, `media_volume`, red `internal`); Docker los materializa como **`<COMPOSE_PROJECT_NAME>_<clave>`** (p. ej. `fvx_community_backend_postgres_data`), sin duplicar el nombre de la carpeta `fvx-backend/`.

**Agrupación en Docker Desktop:** si ves varios stacks bajo una carpeta padre (p. ej. el nombre del repo en tu disco), suele ser la **ruta del proyecto en el host**; cambiar eso implica renombrar/mover el directorio o abrir Docker desde otra raíz — no lo controla el YAML.

Red compartida con otros stacks (p. ej. `fvx-frontend`): el servicio `web` también está en la red externa **`fvx_suscription_shared`**. Créala una vez en el host:

```bash
docker network create fvx_suscription_shared
```

Desde otro contenedor en esa red, la API Django responde en **`http://fvx_suscription_backend_web:8080`**.

```bash
# Ver logs
docker compose logs -f

# Ver logs de un servicio específico
docker compose logs -f web

# Ejecutar comandos Django
docker compose exec web python manage.py <comando>

# Crear migraciones
docker compose exec web python manage.py makemigrations

# Ejecutar migraciones
docker compose exec web python manage.py migrate

# Crear superusuario
docker compose exec web python manage.py createsuperuser

# Shell de Django
docker compose exec web python manage.py shell

# Acceder a PostgreSQL
docker compose exec db psql -U fvx_user -d fvx_backend_db
```

### Detener servicios

```bash
docker compose down              # Detener contenedores
docker compose down -v           # Detener y eliminar volúmenes
```

## 🔒 CORS Configuration

### Desarrollo (permitir todo)
Ya está configurado en `.env`:
```
CORS_ALLOW_ALL_ORIGINS=True
```

### Producción (restringir orígenes)
Editar `.env`:
```
CORS_ALLOW_ALL_ORIGINS=False
CORS_ALLOWED_ORIGINS=https://app.example.com,https://admin.example.com
```

## 🧪 Testing

```bash
# Ejecutar tests
docker-compose exec web pytest

# Con cobertura
docker-compose exec web pytest --cov=apps

# Tests específicos
docker-compose exec web pytest apps/core/tests/
```

## 📝 Próximos Pasos

### 1. Modelos y migraciones

La lógica vive en la app única **`api/`** (`api/models/`, etc.). Para cambios de esquema:

- Ajustar modelos y ejecutar `docker compose exec web python manage.py makemigrations`
- Aplicar: `docker compose exec web python manage.py migrate`

### 2. Serializers y vistas

Mantener alineados los módulos en `api/serializers/` y `api/views/` (vía sus `__init__.py` y `api/urls.py`) con el contrato que consume el frontend, siguiendo la guía de la subsección **Extensión: dónde guardar código personalizado** (arriba, bajo *Estructura del Proyecto*).

### 3. Admin y permisos

Registrar modelos en `api/admin.py` y revisar permisos DRF / roles (`api/roles.py`, `ROLE_CHOICES`).

## 🐛 Troubleshooting

### Error: Puerto 5432 ya en uso
```bash
# Detener PostgreSQL local
sudo service postgresql stop
# O cambiar puerto en docker-compose.yml
```

### Error: Puerto 8080 ya en uso
```bash
# Cambiar puerto en docker-compose.yml
ports:
  - "8081:8080"
```

### Resetear base de datos
```bash
docker-compose down -v
docker-compose up -d
```

### Error al construir la imagen: `E: You don't have enough free space in /var/cache/apt/archives/`

Eso ocurre **dentro del builder de Docker**: el disco reservado a Docker (o el disco del Mac) está casi lleno. El `Dockerfile` ya pide menos paquetes que antes (sin `gdal-bin` / `-dev`) y usa caché de BuildKit para apt, pero si no hay espacio libre hay que liberarlo.

1. Ver uso de Docker: `docker system df`
2. Liberar imágenes/contenedores viejos (ojo, borra lo no usado): `docker system prune -a`
3. Liberar caché de **builds** (a veces llena el disco aunque no haya contenedores): `docker builder prune`
4. **Docker Desktop** → *Settings* → *Resources* → *Disk image size* → subir el límite si está al máximo
5. En macOS, revisar espacio en disco: *Apple menu* → *About This Mac* → *Storage*

## 📄 Licencia

Propietario — FVX Template (código base interno)

## 👥 Contacto

Para soporte o consultas, contactar al equipo de desarrollo.
