# API y frontend — acoplamiento

Este documento describe **cómo encaja** `fvx-backend` con `fvx-frontend` en el mismo repositorio. No sustituye el [`README.md`](../README.md) del backend ni el [`README.md`](../../fvx-frontend/docs/README.md) del frontend.

## URLs y entornos

El Angular define en `fvx-frontend/src/environments/`:

- **`apiUrl`**: base de la API versionada (ej. `http://localhost:8080/api/v1`).
- **`authUrl`**: base de autenticación JWT (ej. `http://localhost:8080/api/auth`).

Esas URLs deben coincidir con el despliegue real de Django (puerto, host, prefijos). En Docker, el `README.md` del backend y el del frontend suelen documentar la red compartida y los puertos.

## Autenticación

1. El front obtiene **access** y **refresh** contra el endpoint de token configurado en `authUrl`.
2. Las peticiones a `apiUrl` llevan el header **`Authorization`** con esquema **Bearer** y el access token (interceptor en el front).
3. El backend valida el JWT y aplica permisos por vista / rol efectivo (ver `api/roles.py` y permisos DRF).

Cualquier cambio en rutas de auth o en el formato de respuesta exige actualizar **servicios e interceptores** del frontend y documentar el contrato aquí o en OpenAPI/Spectacular.

## Menú lateral

El menú dinámico se obtiene desde la API (p. ej. árbol de menús filtrado por rol). El layout Angular hace fallback a entradas estáticas si la carga falla o viene vacía. Los textos del menú **desde base de datos** siguen el idioma almacenado en servidor; el selector **EN/ES** del front afecta sobre todo a **cadenas de Angular** y a **`Accept-Language`** para respuestas traducibles del API (ver [i18n.md](i18n.md)).

## Internacionalización (resumen)

- El front envía **`Accept-Language`** en llamadas a `apiUrl` y `authUrl` (interceptor `locale.interceptor.ts`).
- El back usa **`LocaleMiddleware`** y catálogos en **`locale/`** para `gettext` / `gettext_lazy` en código Python (p. ej. etiquetas de choices y `role_label` en serializers).

Detalle y comandos: [i18n.md](i18n.md) y en el front [i18n.md](../../fvx-frontend/docs/i18n.md).

## Documentación cruzada

| Tema | Backend | Frontend |
|------|---------|----------|
| Índice docs | [docs/README.md](README.md) | [docs/README.md](../../fvx-frontend/docs/README.md) |
| Resumen del otro lado | (esta guía) | [backend.md](../../fvx-frontend/docs/backend.md) |
| i18n full stack | [i18n.md](i18n.md) | [i18n.md](../../fvx-frontend/docs/i18n.md) |
| CRUD nuevo modelo | Modelos, serializers, URLs en `api/` | [add-crud-model.md](../../fvx-frontend/docs/add-crud-model.md) |

## Gobernanza

Cambios que tocan **contratos de API**, **auth**, **CORS**, **serializers expuestos al front** o **settings** compartidos deben alinearse con [`AGENT.md`](../../AGENT.md).

---

## Resumen: qué ejecutar con Docker

Levantar **API + BD + Redis** (desde **`fvx-backend/`**):

```bash
docker compose up -d --build
```

Levantar **Angular** (desde **`fvx-frontend/`**, con la red `fvx_suscription_shared` creada y el backend accesible según `environment.ts`):

```bash
docker compose up --build
```

No necesitas invocar `python manage.py` en el host para el flujo diario: usa `docker compose exec web …` como en [i18n.md](i18n.md) para tareas de mantenimiento (gettext, migraciones, shell, etc.).
