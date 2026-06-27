# Sesiones en vivo por Zoom (embebidas, con control de acceso)

Esta guía documenta la funcionalidad de **sesiones en vivo de Zoom** integrada en
la plataforma de membresías de Experiencias Lita Donoso, y el **paso a paso en
Zoom** (crear cuenta, crear la app, generar las llaves, etc.).

> **Resumen en una línea:** un miembro con el plan correcto entra a `/mi-contenido`,
> hace clic en la sesión en vivo y **Zoom se abre embebido dentro del sitio**, sin
> ver ni poder reenviar ningún link. El acceso lo decide el servidor según el
> **plan** y el **horario**.

---

## 1. Qué se implementó

- **Zoom embebido** en el sitio (no se abre zoom.us ni se muestra un link): el
  miembro se une dentro de `/sala/:id` usando el **Zoom Meeting SDK (Client View)**.
- **Acceso por plan + horario**: solo entra quien tiene una membresía activa que
  incluye esa sesión (ej. Oro) y dentro de la franja horaria (se abre unos minutos
  antes del inicio y se cierra al final).
- **Sin link reenviable**: el número de reunión y la clave viven **solo en el
  servidor**; al cliente se le entrega una **firma de vida corta**, no un enlace.
- **Cuenta regresiva** en la tarjeta: muestra "EN VIVO", "En 2h 15m" o "Finalizada".
- **Anti-compartir cuenta**:
  - **Sesión única**: el último login con un correo invalida los anteriores.
  - **Entrada única en vivo**: un segundo dispositivo con el mismo correo recibe
    *"Ya estás conectado en otro dispositivo"* y no puede entrar a la vez.
- **Interfaz de la reunión en español**.

---

## 2. Cambios técnicos (referencia rápida)

### Backend (`fvx-backend`, app `subscriptions/`)
- **`models.py`** — `ContentItem` (kind `zoom`) gana: `zoom_meeting_number`,
  `zoom_passcode`, `live_start`, `live_end` + propiedades `live_opens_at`,
  `live_closes_at`, `is_live_open()`. Migración `0013_contentitem_zoom_live`.
- **`services/zoom.py`** — `meeting_signature()`: arma la firma JWT del Meeting SDK
  con `ZOOM_SDK_KEY` / `ZOOM_SDK_SECRET` (sin dependencias extra).
- **`services/member_auth.py`** — sesión única (`sid` por correo en caché),
  `identity_from_token()`, `logout()`, y remitente del correo con nombre de marca.
- **`views.py`** — endpoints de miembro:
  - `POST /api/v1/public/member/content/<id>/zoom/` → firma (valida plan + horario
    + candado de entrada única).
  - `POST .../zoom/heartbeat/` → latido que mantiene la presencia.
  - `POST .../zoom/leave/` → libera la presencia al salir.
  - Endpoints de miembro **exentos de throttle** (el latido superaría el cupo anon).
- **`serializers.py`** — `MemberContentSerializer` expone `live_start/live_end`,
  `live_open`, `has_zoom`, `opens_at`, `closes_at`.
- **`admin.py`** — sección "Sesión en vivo (Zoom)" en el contenido.
- **`core/settings/base.py`** y **`.env.example`** — variables `ZOOM_*`.

### Frontend (`fvx-frontend`)
- **`public/zoom-room/zoom-room.component.ts`** — sala `/sala/:id` que carga el
  Client View 6.2.0 desde el CDN de Zoom, en español, con latido de presencia.
- **`features/content/content.component.ts`** — campos de Zoom en el formulario de
  contenido del admin.
- **`shared/components/entity-form-dialog`** + **`core/models/api.model.ts`** —
  nuevo tipo de campo `datetime` que usa el calendario `app-calendar` con hora.
- **`public/member-content/`** — tarjeta con estado EN VIVO / cuenta regresiva y
  navegación a la sala.
- **`index.html`** — CSP ampliada para permitir `source.zoom.us` y `*.zoom.us`.

---

## 3. Configuración en Zoom (paso a paso)

### 3.1. Crear / usar una cuenta de Zoom
1. Ve a <https://zoom.us> y crea una cuenta (o inicia sesión con la cuenta de la
   marca, ej. `admin@favric.cl`).
2. La **cuenta gratis sirve para probar** (límite de **40 minutos** por reunión).
   Para sesiones más largas se necesita un plan de pago (Pro o superior).

> ⚠️ **Importante (Error 4011):** la app del SDK **y** las reuniones que se hospedan
> deben pertenecer a la **MISMA cuenta de Zoom**. Una app sin publicar solo puede
> entrar a reuniones de su propia cuenta. Si creas la app con una cuenta y hospedas
> con otra, saldrá el error 4011.

### 3.2. Crear la app del Meeting SDK
> Zoom cambió el flujo: ya **no existe** el tipo "Meeting SDK" como app aparte.
> Ahora se crea una **General App** y dentro se habilita el Meeting SDK.

1. Entra al portal de desarrollador: <https://marketplace.zoom.us> →
   menú **Develop → Build App** (o el link **"Developer"** de la barra lateral).
   Si te pide aceptar el *API License Agreement*, acéptalo.
2. Elige **General App** → **Create**.
3. Ponle un nombre (ej. "Lita Donoso Web").
4. Ve a **Features → Embed** y **activa Meeting SDK**.
5. En **Basic Information / App Credentials** verás el **Client ID** y el
   **Client Secret**. Para pruebas basta con las credenciales de **desarrollo**;
   **no necesitas publicar** la app en el Marketplace.

### 3.3. Poner las llaves en el backend (`.env`)
En el archivo `fvx-backend/.env` (NO se sube a git, contiene secretos):

```env
# Llaves del Meeting SDK (de la General App → Embed → Meeting SDK)
ZOOM_SDK_KEY=el-CLIENT-ID-de-la-app
ZOOM_SDK_SECRET=el-CLIENT-SECRET-de-la-app

# Opcionales (tienen valores por defecto)
ZOOM_LIVE_OPEN_BEFORE_MIN=15   # minutos antes del inicio en que se abre el acceso
ZOOM_DEFAULT_DURATION_MIN=240  # duración por defecto si no defines "Fin en vivo"
ZOOM_LIVE_LOCK_TTL=75          # segundos del candado de entrada única (renovado por latido)
```

| Variable `.env`     | Valor en Zoom            |
| ------------------- | ------------------------ |
| `ZOOM_SDK_KEY`      | **Client ID** de la app  |
| `ZOOM_SDK_SECRET`   | **Client Secret** de la app |

### 3.4. Reiniciar el backend
Después de editar el `.env`:

```bash
docker compose restart web
```

---

## 4. Cómo programar una sesión (en el panel admin)

### Paso 1 — Crear la reunión en Zoom
En la cuenta de Zoom (la misma de la app), **programa una reunión** (Reuniones →
Programar) o usa una **reunión recurrente / tu PMI** para no cambiar el ID cada vez.
Anota el **ID de reunión** y el **Código de acceso (Passcode)**.

> Copia el **Código de acceso** que muestra Zoom, **no** el `pwd=...` largo del link
> de invitación (ese está encriptado y no sirve para el SDK).

### Paso 2 — Cargar la sesión en `/admin/content`
Crea un contenido nuevo:
- **Tipo** → "Sesión Zoom (en vivo)"
- **Título** → ej. "Encuentro en vivo · Junio"
- **Zoom · N° de reunión** → el Meeting ID (los espacios se limpian solos)
- **Zoom · Clave** → el passcode
- **Inicio en vivo** → fecha y hora (el acceso se abre 15 min antes)
- **Fin en vivo** → opcional (vacío = duración por defecto)
- **Publicado** → activado

### Paso 3 — Asignarla a un plan en `/admin/programacion`
Crea una entrada de Programación:
- **Contenido** → la sesión Zoom
- **Plan** → el que tendrá acceso (ej. **Oro**)
- **Desde / Hasta** → rango de fechas en que aparece

> La **Programación** decide **quién** entra (qué plan) y **cuándo** (rango de
> fechas); el **Inicio/Fin en vivo** decide la **franja horaria** exacta de la sala.

### Durante la sesión
Tú (anfitriona) **inicias la reunión** en tu Zoom normal a la hora indicada. Los
miembros entran embebidos como participantes. Si no inicias la reunión, verán
"Espera a que el anfitrión inicie la reunión".

---

## 5. Cómo lo ve el miembro

1. Entra a **`/acceso`**, pone su correo y el código que recibe por email.
2. En **`/mi-contenido`** ve la tarjeta de la sesión:
   - Antes: **cuenta regresiva** ("En 2h 15m") + fecha.
   - Dentro de la franja: **● EN VIVO** (clickable).
3. Hace clic → entra a **`/sala/:id`** con Zoom embebido (en español).

---

## 6. Controles anti-compartir cuenta

- **Sesión única:** cada login invalida el anterior. Si alguien comparte su código,
  el último que entra expulsa a los demás. *(Tras desplegar, los ya logueados deben
  reingresar una vez.)*
- **Entrada única en vivo:** un segundo dispositivo con el mismo correo recibe
  *"Ya estás conectado a esta sesión en otro dispositivo"* (HTTP 409) y no obtiene
  la firma. Si alguien "roba" la sesión, al primero se le expulsa en el siguiente
  latido (~30s).
- **Visibilidad para la anfitriona:** en la lista de participantes de Zoom aparece
  el correo de cada miembro; si ves un duplicado, puedes expulsarlo con un clic.

> No existe forma 100% infalible (alguien podría grabar su pantalla), pero estos
> controles hacen impráctico compartir la cuenta.

---

## 7. Limitaciones y notas

- **Cuenta gratis:** reuniones de máximo **40 minutos**. Para más, plan de pago.
- **Error 4011:** app del SDK y reunión deben ser de la **misma cuenta** de Zoom
  (mientras la app no esté publicada en el Marketplace).
- **Versión del SDK:** `6.2.0` (constante `ZOOM_VERSION` en `zoom-room.component.ts`);
  se puede subir cuando Zoom publique una nueva.
- **Permisos del navegador:** la primera vez Chrome pedirá acceso a cámara/micrófono;
  hay que **Permitir**.

---

## 8. Solución de problemas (errores que pueden aparecer)

| Mensaje / síntoma | Causa | Solución |
| --- | --- | --- |
| **"No se pudo cargar Zoom"** | La CSP bloquea `source.zoom.us` o faltan dependencias del SDK | Verificar la CSP en `index.html` (debe incluir `source.zoom.us`, `'wasm-unsafe-eval'`, `wss://*.zoom.us`, `*.zoom.us`) |
| **`meetingNumber length > 12`** | El N° de reunión tiene espacios/guiones | Ya se limpia en el backend; revisar que sea un ID válido |
| **Error 4011** ("external Zoom account") | La reunión es de otra cuenta distinta a la de la app SDK | Hospedar la reunión con la **misma cuenta** dueña de la app |
| **Pantalla negra** | Parámetro inválido en `ZoomMtg.init` o la reunión no ha iniciado | El idioma se setea con `i18n.load`, no en `init`; iniciar la reunión como anfitrión |
| **HTTP 429 (Too Many Requests)** | Límite anti-abuso (throttle) agotado | Los endpoints de miembro ya están exentos; si pasa, esperar a que pase la hora o limpiar las claves `*throttle*` en Redis |
| **HTTP 500 al pedir la firma** | Error de servidor (revisar logs) | `docker compose logs web` y revisar el traceback |
| **"Zoom no está configurado en el servidor" (503)** | Faltan `ZOOM_SDK_KEY` / `ZOOM_SDK_SECRET` | Configurarlas en el `.env` y `docker compose restart web` |

### Comandos útiles
```bash
# Aplicar migraciones (incluida la de Zoom)
docker compose exec web python manage.py migrate

# Ver logs del backend
docker compose logs web --tail=50

# Limpiar el cupo de throttle en Redis (si hay 429 por pruebas)
docker compose exec redis sh -c "redis-cli --scan --pattern '*throttle*' | xargs -r redis-cli del"
```

---

## 9. Historial de errores y cómo los resolvimos (bitácora)

Orden cronológico real de los problemas que aparecieron durante la
implementación y prueba, con su causa y la solución aplicada. Sirve como
referencia si algo similar vuelve a ocurrir.

### 1) `ProgrammingError: column subscriptions_contentitem.zoom_meeting_number does not exist`
- **Síntoma:** `/admin/content`, `/admin/programacion` y `/mi-contenido` daban
  error 500; el código nuevo ya esperaba las columnas Zoom.
- **Causa:** el código se desplegó pero **faltó aplicar la migración** en la base
  de datos (la tabla aún no tenía las columnas nuevas).
- **Solución:** aplicar la migración dentro del contenedor:
  ```bash
  docker compose exec web python manage.py migrate subscriptions
  ```

### 2) Selector de fecha/hora poco amigable
- **Síntoma:** los campos "Inicio/Fin en vivo" usaban un input nativo `dd-mm-aaaa`.
- **Causa:** el formulario CRUD solo tenía tipo `date`.
- **Solución:** se agregó el tipo de campo **`datetime`** que reutiliza el
  componente `app-calendar` (calendario con hora) en el formulario del admin.

### 3) No aparecía el tipo de app "Meeting SDK" en Zoom
- **Síntoma:** en el Marketplace no se encontraba dónde crear una app "Meeting SDK".
- **Causa:** Zoom **cambió el flujo**: ese tipo ya no existe por separado.
- **Solución:** crear una **General App** y dentro **Features → Embed → activar
  Meeting SDK**. Las llaves son el **Client ID** (→ `ZOOM_SDK_KEY`) y el
  **Client Secret** (→ `ZOOM_SDK_SECRET`).

### 4) "No se pudo cargar Zoom"
- **Síntoma:** la sala `/sala/:id` mostraba ese error y no cargaba el SDK.
- **Causa (doble):** (a) la **CSP** del sitio no permitía `source.zoom.us`;
  (b) versión vieja del SDK (3.13.2) y **faltaban las dependencias** (React, Redux…).
- **Solución:** ampliar la CSP en `index.html` (`source.zoom.us`,
  `'wasm-unsafe-eval'`, `wss://*.zoom.us`, `*.zoom.us`) y usar la **versión 6.2.0**
  cargando primero `react`, `react-dom`, `redux`, `redux-thunk`, `react-redux`,
  `lodash` y luego el bundle `zoom-meeting-6.2.0.min.js`.

### 5) `Joining Meeting Timeout or Browser restriction — meetingNumber length > 12`
- **Síntoma:** error al intentar unirse a la reunión.
- **Causa:** el N° de reunión se guardó **con espacios** (`858 0229 1303` = 13
  caracteres); el SDK exige solo dígitos (máx. 12).
- **Solución:** el backend **limpia** el número con `re.sub(r"\D", "", ...)` antes
  de firmar (acepta el ID con o sin espacios).

### 6) `Error Code 4011` — "to join a meeting hosted by an external Zoom account…"
- **Síntoma:** el SDK no dejaba unirse a la reunión.
- **Causa:** la **app del SDK** y la **reunión** estaban en **cuentas de Zoom
  distintas**; una app sin publicar solo entra a reuniones de su propia cuenta.
- **Solución:** hospedar la reunión con la **misma cuenta** de Zoom dueña de la app
  (no hace falta publicar la app en el Marketplace).

### 7) Pantalla negra al entrar a la sala
- **Síntoma:** Zoom cargaba (en consola: `load success`, `wasm success`) pero la
  pantalla quedaba negra; en consola aparecía **`Init invalid parameter !!!`**.
- **Causa:** se le pasó `language: 'es-ES'` a `ZoomMtg.init()`, que **no acepta**
  ese parámetro en la 6.2.0 → `init` fallaba y nunca se ejecutaba el "join".
- **Solución:** quitar `language` de `init` y poner el idioma con
  `ZoomMtg.i18n.load('es-ES')` / `i18n.reload('es-ES')`.

### 8) `DateFnsAdapter: Cannot format invalid date` + `RangeError: Invalid time value`
- **Síntoma:** al configurar/guardar la sesión, la consola se llenaba de errores y
  **Guardar** reventaba con `Invalid time value` (en `toISOString`).
- **Causa:** el calendario, al combinar fecha + hora, podía generar
  momentáneamente una **fecha inválida** (hora del timepicker a medio escribir).
- **Solución:** guardas defensivas — el `app-calendar` ignora una hora inválida y
  el diálogo solo serializa a ISO si el `Date` es válido (si no, manda `null`).

### 9) Se podía entrar dos veces con el mismo correo (incógnito)
- **Síntoma:** desde una ventana incógnito, el mismo correo+código entraba a la
  **misma reunión** en paralelo (compartir cuenta).
- **Causa:** el token de sesión era **stateless** (sin control de sesiones).
- **Solución:** **sesión única** (el último login invalida los anteriores) +
  **candado de entrada única en vivo** (endpoints `heartbeat`/`leave` + marca de
  presencia en caché); el 2º dispositivo recibe 409 *"Ya estás conectado en otro
  dispositivo"*.

### 10) `Error del servidor (500)` al pedir la firma de Zoom
- **Síntoma:** "Error del servidor. Vuelva a intentarlo más tarde." al conectarse.
- **Causa:** se usó `cache` en `views.py` pero **faltó importarlo**
  (`NameError: name 'cache' is not defined`).
- **Solución:** agregar `from django.core.cache import cache` en `views.py`.

### 11) `HTTP 429 Too Many Requests` (se bloqueaba todo)
- **Síntoma:** `/mi-contenido` mostraba "No se pudo cargar tu contenido" y varios
  endpoints (incluido admin) devolvían 429.
- **Causa:** el límite anti-abuso `anon` (120/h) por IP se agotó: los endpoints de
  miembro contaban como anónimos y el **latido cada 30s** + las recargas de prueba
  lo consumieron.
- **Solución:** **eximir del throttle** los endpoints del área de miembros (siguen
  protegidos por su token) y **limpiar** las claves `*throttle*` en Redis para
  desbloquear de inmediato. El límite se mantiene en pedir/verificar código.

---

## 10. Endpoints (referencia)

| Método | Ruta | Descripción |
| --- | --- | --- |
| POST | `/api/v1/public/member/content/<id>/zoom/` | Firma para unirse (valida plan + horario + candado) |
| POST | `/api/v1/public/member/content/<id>/zoom/heartbeat/` | Latido de presencia (cada ~30s) |
| POST | `/api/v1/public/member/content/<id>/zoom/leave/` | Libera la presencia al salir |

---

## 11. Para el cliente: qué ofrece y qué necesitas saber

Resumen en lenguaje simple de lo que esta función aporta al negocio.

### ✨ Qué permite hacer
- **Clases y encuentros en vivo solo para suscriptores.** Tus sesiones de Zoom se
  ven **dentro de tu propia página**, no en un enlace suelto.
- **Acceso automático por membresía.** Tú decides qué plan entra a cada sesión
  (por ejemplo, solo **Oro**). El sistema lo controla solo: no tienes que repartir
  links ni revisar quién pagó.
- **Horario controlado.** La sala se abre sola unos minutos antes y se cierra al
  terminar. Nadie entra antes de tiempo ni queda dando vueltas después.

### 🔒 Por qué es más seguro que mandar un link de Zoom
- **El link nunca se ve ni se puede reenviar.** Aunque alguien quiera pasarlo a un
  amigo, no hay un enlace que copiar: el acceso lo da el sistema en el momento.
- **Una cuenta = una persona a la vez.** Si alguien presta su correo, el segundo
  que entra deja afuera al primero. Compartir la cuenta deja de ser útil.
- **Tú ves quién está dentro.** En la lista de participantes aparece el correo de
  cada miembro; si ves un duplicado o un colado, lo sacas con un clic.

### 🧭 Qué experimenta tu suscriptor
1. Entra a su área con su correo y un código (sin contraseñas que olvidar).
2. Ve la sesión con una **cuenta regresiva** ("En 2 h 15 min") y un sello **EN VIVO**
   cuando llega la hora.
3. Hace un clic y entra a la reunión **dentro del sitio, en español**. Simple.

### 🧰 Qué necesitas tú para usarlo
- **Una cuenta de Zoom** (la misma con la que se configuró la integración).
- **Crear la reunión** en Zoom (puedes usar una **reunión recurrente** para que el
  enlace y la clave no cambien cada semana) y **cargarla** en el panel.
- **Iniciar la reunión** a la hora, como anfitriona. El resto es automático.

### 💲 Costos y límites a tener presente
- **Plan gratis de Zoom:** funciona, pero las reuniones se cortan a los
  **40 minutos**. Ideal para probar.
- **Para sesiones largas** (clases completas, talleres) conviene un **plan de pago
  de Zoom** (Pro o superior). Ese costo es de Zoom, aparte de la plataforma.
- La plataforma no cobra nada extra por sesión: puedes hacer **todas las que
  quieras**.

### 📌 Recomendaciones prácticas
- Usa una **reunión recurrente** o tu **ID personal (PMI)** para no reconfigurar el
  ID/clave en cada sesión: solo ajustas la fecha y hora.
- Programa la sesión con varios minutos de anticipación y **inicia el Zoom** un
  poco antes para recibir a la gente.
- Si haces sesiones por niveles (ej. una para Oro y otra para Plata), basta con
  asignar cada sesión al plan correspondiente.

> **En una frase para el cliente:** *"Tus clases en vivo quedan exclusivas para tus
> miembros, se abren solas a la hora correcta y nadie puede compartir el acceso."*
