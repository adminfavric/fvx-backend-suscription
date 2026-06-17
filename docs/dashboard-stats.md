# API de métricas del dashboard (`GET /api/v1/stats/`)

## Rol

- Devuelve **KPIs agregados** para el shell Angular (`/dashboard`) mostrados con **`app-stat-card`**.
- **Requiere JWT** (`IsAuthenticated`); mismo token que el resto del `api/v1/`.
- Contrato versionable: el front consume `items` + `generated_at`.

## Contrato JSON (respuesta)

```http
GET /api/v1/stats/
Authorization: Bearer <access>
```

Cuerpo típico:

```json
{
  "generated_at": "2026-04-24T12:00:00.123456+00:00",
  "items": [
    {
      "id": "users_active",
      "value": 32,
      "label": "Active users",
      "label_key": "dashboard.stats.usersActive",
      "icon": "person",
      "tone": "primary",
      "variant": "default",
      "description": "User accounts with is_active=True",
      "trend": null,
      "trend_value": null,
      "trend_label": null
    }
  ]
```

| Campo | Tipo | Notas |
|--------|------|--------|
| `id` | string | Identificador estable (clave en caché / tests). |
| `value` | number | Número entero o decimal. |
| `label` | string | Texto por defecto (inglés) si no hay i18n en el SPA. |
| `label_key` | string | Clave Transloco bajo `public/assets/i18n/{en,es}.json` (mismo path en ambos). |
| `icon` | string | Nombre de ligature **Material** (`<mat-icon>`), p. ej. `person`, `map`. |
| `tone` | string | `neutral` \| `primary` \| `success` \| `warning` \| `danger` \| `info` (alineado a `StatCardComponent`). |
| `variant` | string | `default` \| `filled` \| `outline` \| `minimal` \| `solid` \| `split` \| `split-solid`. |
| `description` | string (opcional) | Subtítulo bajo el valor. |
| `trend` | string (opcional) | `up` \| `down` \| `neutral` si aplica. |
| `trend_value` | string (opcional) | P. ej. `+3.2%`. |
| `trend_label` | string (opcional) | P. ej. *vs. last month* (a futuro; hoy el backend puede omitirlo). |
| `icon_position` | string (opcional) | `start` \| `end` — columna del icono en la tarjeta (LTR). |
| `icon_surface` | string (opcional) | `soft` \| `filled` \| `muted` — estilo del tile del icono. |
| `progress` | number (opcional) | 0–100; barra de progreso en `app-stat-card`. |
| `generated_at` | string (ISO 8601) | Marca de tiempo de generación en el servidor. |

Omita campos opcionales o envíe `null` en JSON; el front no los pasa a la tarjeta.

## Dónde extender (backend)

1. Archivo: **`api/shell/dashboard_stats.py`**.
2. Añada una función que devuelva `List[dict]` (varios KPI) usando el helper **`_stat(...)`**, o añada la función a la lista **`STAT_SECTIONS`**.
3. Ejemplo: del modelo `User` quiere *usuarios activos*, y del `Profile` los conteos por *rol*:

```python
def _mi_bloque() -> list[dict[str, Any]]:
    from django.contrib.auth import get_user_model
    from ..choices import ROLE_ADMIN
    from ..models import Profile

    User = get_user_model()
    n = User.objects.filter(is_active=True).count()
    n_admin = Profile.objects.filter(
        is_active=True, user__is_active=True, role=ROLE_ADMIN
    ).count()
    return [
        _stat("my_metric", n, label="…", label_key="dashboard.stats.myMetric", ...),
        _stat("my_admins", n_admin, ...),
    ]
```

4. Al final: `STAT_SECTIONS.append(_mi_bloque)` (o inserte en la lista con un comentario claro).
5. **i18n**: añada las claves de `label_key` en el front `en.json` y `es.json` (ver sección abajo).
6. **Recomendado**: añada prueba en `api/tests/` que llame a `get_dashboard_stats()` o al endpoint (sin romper con BD vacía).

**No hace falta** modificar `urls.py` mientras se reutilice `DashboardStatsAPIView` (la plantilla ya expone `stats/`). Si hizo fork y eliminó el endpoint, restaurelo desde el `code-master` o copie el patrón de `api/views/ui.py` + `api/urls.py` + `api/shell/dashboard_stats.py`.

## Cómo pedir un “nuevo cuadro” (comunicación a IA o ticket)

> Del modelo **User**, necesito en el dashboard: cantidad de usuarios con `is_active=True`, y del **Profile** las cantidades con rol **ADMIN**, **EDITOR** y **VIEWER** (usuarios y perfil activos).

> Del modelo **Organization**: cantidad de organizaciones activas (excl. soft delete).

Basta con nombrar **modelo(s)**, **filtro** (QuerySet) y el **texto/label** deseado; el implementador añade ítems en `api/shell/dashboard_stats.py` y claves en i18n.

## i18n en el front

Para cada `label_key` (p. ej. `dashboard.stats.usersActive`):

- `code-master/fvx-frontend/public/assets/i18n/en.json`
- `code-master/fvx-frontend/public/assets/i18n/es.json`

Bajo un objeto anidado, p. ej.:

```json
"dashboard": {
  "stats": {
    "usersActive": "Active users",
    "roleAdmin": "Admin (directory)"
  }
}
```

## `install.sh` y `start.sh`

- El endpoint forma parte de la **plantilla en el repositorio**; no se genera en tiempo de `install` ni se duplica.
- Un segundo `./start.sh local` con el stack ya levantado: el script emite un **aviso** para preferir **`./update.sh local`** (rebuild y migraciones). Proyecto nuevo: use `./start.sh` una vez, luego actualice con `./update.sh`.

## Prueba rápida (curl)

```bash
# Tras login, sustituya ACCESS
curl -sS -H "Authorization: Bearer ACCESS" http://localhost:8080/api/v1/stats/ | python -m json.tool
```

También aparece bajo el tag **stats** en `GET /api/docs/` (Swagger).
