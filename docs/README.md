# Documentación — `fvx-backend`

Material de referencia para quien mantiene la API Django y para quien necesita **encajar backend y frontend** en el monorepo `code-master/`.

**Reglas globales del repo:** [`../../AGENT.md`](../../AGENT.md).

**Guía operativa larga** (Docker, scripts, credenciales, estructura de carpetas): [`../README.md`](../README.md) en la raíz de `fvx-backend/`.

## Documentación en este directorio

| Documento | Contenido |
|-----------|-----------|
| [**api-and-frontend.md**](api-and-frontend.md) | Cómo se conectan Angular y Django: URLs base, JWT, menú, convenciones compartidas. |
| [**dashboard-stats.md**](dashboard-stats.md) | `GET /api/v1/stats/`, KPIs para el dashboard Angular (`app-stat-card`) y cómo añadir métricas. |
| [**i18n.md**](i18n.md) | Internacionalización en el servidor: `gettext`, choices, `role_label`, `Accept-Language`. |
| [**social-login-setup.md**](social-login-setup.md) | Login con Google / Apple: consolas, variables `.env`, checklist y fallos frecuentes. |

## Frontend (Angular)

La SPA vive en **`fvx-frontend/`**. Índice de su documentación:

- [`../../fvx-frontend/docs/README.md`](../../fvx-frontend/docs/README.md)

Temas que cruzan ambas capas (idiomas, headers HTTP, contratos de payload):

- [`../../fvx-frontend/docs/i18n.md`](../../fvx-frontend/docs/i18n.md)
- [`../../fvx-frontend/docs/backend.md`](../../fvx-frontend/docs/backend.md) — resumen del backend pensado para quien solo toca el front.

## Resumen del backend (plantilla)

- **Framework:** Django + Django REST Framework; autenticación JWT (`/api/auth/token/`, refresh).
- **App principal:** `api/` (modelos, serializers, vistas, `choices.py`, `roles.py`).
- **Configuración:** `core/settings.py` (CORS, `LANGUAGES`, `LOCALE_PATHS`, `LocaleMiddleware`).
- **Contratos con el cliente:** versionado bajo prefijo típico `/api/v1/`; el frontend alinea `environment.apiUrl` y `environment.authUrl` con ese despliegue.

Para añadir un recurso CRUD de extremo a extremo, la receta que une Django y Angular está en el front: [`../../fvx-frontend/docs/add-crud-model.md`](../../fvx-frontend/docs/add-crud-model.md).

---

## Resumen: qué ejecutar con Docker

En **`fvx-backend/`** (donde está `docker-compose.yml`), siguiendo el [`README.md`](../README.md) del backend (red `fvx_shared`, `./start.sh`, etc.):

```bash
docker compose up -d --build
```

**Traducciones** (`makemessages` / `compilemessages`): ver la sección final de [i18n.md](i18n.md).

**Frontend** (otro terminal / otro directorio): en **`fvx-frontend/`**, típicamente `docker compose up --build` según el [`README.md`](../../fvx-frontend/README.md) del front.
