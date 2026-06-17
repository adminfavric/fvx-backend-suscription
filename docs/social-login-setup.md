# Configuración: login con Google, Apple y Microsoft (id_token → API → JWT)

## 1. Resumen

El navegador obtiene un **id_token** (JWT) de Google Identity Services, Sign in with Apple JS o MSAL Browser (Microsoft Entra ID). El frontend lo envía al backend en `POST /api/auth/social/google/`, `POST /api/auth/social/apple/` o `POST /api/auth/social/microsoft/` con cuerpo `{ "id_token": "..." }` (Apple puede incluir `user` la primera vez). El servidor valida firma, emisor y audiencia, crea o enlaza el usuario y, si la cuenta está **activa**, devuelve el **mismo JSON** que SimpleJWT (`access`, `refresh`). El SPA reutiliza `GET /api/v1/users/me/` como con usuario/contraseña.

> Los tres proveedores comparten el mismo flujo (`_issue` en `api/social/views.py`): validar id_token contra el JWKS del proveedor → `get_or_create_user_for_social` → cookies JWT. Microsoft es estructuralmente idéntico a Apple (JWT RS256 verificado contra JWKS), con la salvedad del **issuer multi-tenant** (ver §4b).

### Cuentas nuevas vs existentes (`is_active`)

| Situación | Comportamiento |
|-----------|----------------|
| **Correo nuevo** (primera vez en el sistema vía Google/Apple) | Se crea el usuario con **`is_active=False`**. No se emiten JWT. Respuesta **403** con mensaje indicando que la cuenta está **pendiente de validación** y que será notificado cuando pueda acceder. Un administrador debe marcar **`is_active=True`** en Django Admin (o el flujo que definas) antes de que pueda entrar. |
| **Usuario ya existía** y **`is_active=False`** (inactivo por política o administración) | No se emiten JWT. Respuesta **403** con mensaje de que la **cuenta está inactiva** y debe ser activada por un administrador. |
| **Usuario ya existía** y **`is_active=True`** | Se enlaza `SocialAccount` si hace falta y se devuelve **200** con `access` y `refresh`. |

La notificación al usuario final cuando quede aprobado **no está implementada en este backend** (solo el mensaje en la respuesta 403 en el primer login); puedes añadir email/push en otro módulo o proceso.

**Backend:** `api/social/`, flags en `core/settings.py`, variables en `.env`. **Frontend:** botones y client IDs vienen de `GET /api/v1/settings/ui/` (`social.google`, `social.apple`, `social.microsoft`, `google_client_id`, `apple_client_id`, `microsoft_client_id`, `microsoft_tenant_id`). Cada botón se muestra solo si su flag está **on** y su `client_id` presente; el botón oficial de Google (GIS) no se toca, Apple y Microsoft usan botones sobrios con popup.

Tras validar el id_token, si vienen en los claims, se actualizan **`User.first_name` / `User.last_name`** (desde `given_name`, `family_name` o, en su defecto, `name`) y **`Profile.photo_url`** (desde `picture`, típico de Google). Solo se escribe cuando el claim trae texto no vacío; si falta el claim, no se borra lo ya guardado.

## 2. Google (Google Cloud Console)

1. Crea o elige un proyecto; **APIs & Services** → **Credentials** → **Create credentials** → **OAuth client ID**.
2. Tipo **Web application**. En **Authorized JavaScript origins** añade **el origen exacto de la barra de direcciones del navegador** (protocolo + host + puerto, sin path): p. ej. `http://localhost:4200` si abres Angular ahí. Si usas otro puerto u otro host, debes añadir **ese** origen también (`http://127.0.0.1:4200` cuenta como distinto de `localhost`). Sin eso, la consola muestra `[GSI_LOGGER]: The given origin is not allowed for the given client ID` y el botón puede fallar.
3. Completa la **OAuth consent screen**; en modo *Testing*, añade usuarios de prueba.
4. Copia el **Client ID** al backend: `GOOGLE_OAUTH_CLIENT_ID` y asegúrate de que el mismo valor (o el configurado en GIS en el front) coincida con la audiencia del token. Documentación GIS: [Google Identity Services](https://developers.google.com/identity/gsi/web).

## 3. Apple (Apple Developer)

1. Cuenta de desarrollador con capacidad de **Sign in with Apple**.
2. **Identifiers:** App ID con Sign in with Apple; crea un **Services ID** para web (client id distinto del bundle de app).
3. En el Services ID, **Configure** dominio principal, subdominios y **Return URLs** acordes con tu SPA (HTTPS en producción).
4. **Keys:** crea una clave `.p8` si más adelante el backend intercambia *authorization code*; para el flujo solo **id_token** en web suele bastar con `APPLE_CLIENT_ID` (Services ID) y validación JWKS en servidor.
5. **Localhost:** Sign in with Apple en web a menudo exige dominio HTTPS; muchos equipos usan un dominio de staging o un túnel HTTPS para pruebas. Ver [Sign in with Apple JS](https://developer.apple.com/documentation/sign_in_with_apple/sign_in_with_apple_js).

## 3b. Microsoft (Microsoft Entra ID / Azure AD)

1. En el **portal de Entra ID** (entra.microsoft.com) → **App registrations** → **New registration**.
2. **Supported account types**: elige según el `tenant` que vayas a usar (ver abajo). Para uso interno de una organización, *Single tenant*; para cualquier organización + cuentas personales, *Multitenant + personal*.
3. **Platform / Redirect URI**: añade plataforma **Single-page application (SPA)** y pon el **origen exacto** de la SPA (`http://localhost:4200` en dev, la URL HTTPS real en prod). MSAL usa el flujo *auth code + PKCE* desde el navegador, por eso debe ser tipo **SPA** (no *Web*).
4. Copia el **Application (client) ID** → `MICROSOFT_OAUTH_CLIENT_ID`.
5. **Tenant** → `MICROSOFT_OAUTH_TENANT_ID`:
   - `common` — cualquier organización + cuentas personales Microsoft (default).
   - `organizations` — cualquier organización (sin personales).
   - `consumers` — solo cuentas personales.
   - un **GUID** o **dominio** concreto — restringe a tu organización.
   El mismo valor debe usarse en el backend (define issuer/JWKS aceptados) y se expone al front vía UiSettings para construir la *authority* de MSAL.
6. **Optional claims** (recomendado): en *Token configuration*, añade el claim `email` al **ID token** para que el backend reciba el correo de forma directa. Si no, se usa `preferred_username` (UPN) cuando parezca un email.

> **Issuer multi-tenant:** con `common`/`organizations`/`consumers`, cada usuario trae el GUID de **su** tenant en el `iss` del token, así que no se puede fijar un issuer exacto; el backend valida el **patrón** (`https://login.microsoftonline.com/<algo>/v2.0`). Con un tenant GUID concreto sí se valida el issuer por igualdad.

## 4. Checklist de variables

| Variable | Dónde se obtiene | Obligatoria si… |
|----------|------------------|-----------------|
| `SOCIAL_AUTH_GOOGLE_ENABLED` | `.env` (`true`/`false`) | No, si Google está desactivado (endpoints responden 403). |
| `SOCIAL_AUTH_APPLE_ENABLED` | `.env` | No, si Apple está desactivado. |
| `SOCIAL_AUTH_MICROSOFT_ENABLED` | `.env` | No, si Microsoft está desactivado. |
| `GOOGLE_OAUTH_CLIENT_ID` | OAuth client web (Google Cloud) | Sí, si `SOCIAL_AUTH_GOOGLE_ENABLED=true`. |
| `APPLE_CLIENT_ID` | Services ID (Apple) | Sí, si `SOCIAL_AUTH_APPLE_ENABLED=true`. |
| `MICROSOFT_OAUTH_CLIENT_ID` | Application (client) ID (Entra) | Sí, si `SOCIAL_AUTH_MICROSOFT_ENABLED=true`. |
| `MICROSOFT_OAUTH_TENANT_ID` | Tenant Entra (`common` por defecto) | No (default `common`); fíjalo para restringir a tu organización. |

## 5. Producción

- HTTPS en front y API; orígenes CORS y orígenes JS de Google alineados con URLs reales.
- Revisa políticas de privacidad y pantallas de consentimiento en ambas consolas.
- Rotación de secretos y claves según calendario del proveedor.

## 6. Problemas frecuentes

| Síntoma | Causa típica |
|---------|----------------|
| `redirect_uri_mismatch` (Google) | Origen no listado en credenciales web o URL incorrecta. |
| Dominio no verificado (Apple) | Services ID / dominio no configurados o sin HTTPS donde se exige. |
| 403 en `/api/auth/social/*` | Flag `SOCIAL_AUTH_*_ENABLED=false`, **cuenta pendiente de validación** (registro social nuevo con `is_active=False`), o **cuenta inactiva**; el cuerpo JSON incluye `detail` en español según el caso. |
| Token inválido / audiencia | `aud` del id_token no coincide con `GOOGLE_OAUTH_CLIENT_ID`, `APPLE_CLIENT_ID` o `MICROSOFT_OAUTH_CLIENT_ID` configurados. |
| `AADSTS50011` redirect URI mismatch (Microsoft) | El origen de la SPA no está como **Redirect URI tipo SPA** en el App registration de Entra (debe ser SPA, no Web). |
| `Microsoft token issuer is not trusted` | El `tenant` configurado no concuerda con el del token. Revisa `MICROSOFT_OAUTH_TENANT_ID` (un GUID concreto solo acepta tokens de ese tenant). |
| Microsoft entra pero sin email | Falta el **optional claim `email`** en el ID token y `preferred_username` no es un correo; añade el claim en *Token configuration*. |
| `[GSI_LOGGER]: origin is not allowed` / 403 en recursos del botón | El **JavaScript origin** en Google Cloud no coincide con la URL real de la SPA; edita el cliente OAuth y añade ese origen (incluido el puerto). Añade **varias variantes** si las usas: `http://localhost:4200`, `http://127.0.0.1:4200`, staging, etc. (`localhost` ≠ `127.0.0.1`). |
| Login correcto pero siguen avises **GSI** / **COOP** / `postMessage` en consola | Suele ser **normal en desarrollo**: Chrome + iframe de Google y políticas del navegador. Si el **POST** a `/api/auth/social/google/` devuelve 200 y entras a la app, puedes ignorarlos o completar orígenes en la consola Google; el front llama a `google.accounts.id.cancel()` tras éxito para reducir ruido. |

## 7. Unificación de cuentas

Si un usuario ya existía con email/contraseña y entra con Google/Apple con el mismo email, el backend **enlaza** `SocialAccount` al mismo `User`. Si ese usuario está inactivo, aplica el mismo **403** que para cualquier cuenta inactiva (no el mensaje de “pendiente de validación”, reservado al alta social **nueva**).

## 8. Validación administrativa de altas sociales

- Los registros **solo por redes sociales** con correo que no existía antes quedan en **`is_active=False`** hasta que un administrador los active.
- Tras activar al usuario en Django Admin (`Usuarios` → marcar **Activo**), el mismo usuario podrá volver a usar “Continuar con Google/Apple” y recibirá JWT con **200**.
- Conviene definir en producto quién revisa altas y cómo se “notifica” al usuario fuera de este API si lo necesitas (correo transaccional, etc.).
