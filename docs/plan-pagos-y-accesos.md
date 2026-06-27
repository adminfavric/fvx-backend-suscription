# Plan: pagos multi-pasarela, accesos por período y multi-cliente

> **Estado: BORRADOR para discutir.** Este documento NO es implementación; es el
> mapa para alinearnos antes de construir. Las decisiones abiertas están marcadas
> con 🟡 y mi recomendación con ✅.

## 0. Objetivo general

Hoy el acceso a contenido depende de una **suscripción automática** (Flow tarjeta
o PayPal) que se **consulta en vivo** a la pasarela. Queremos poder dar acceso
también cuando el pago **no** es una suscripción automática:

- Pagos por **transferencia** o medios online sin cobro recurrente.
- **Alta manual** para casos internacionales donde la suscripción no se puede.
- **Importar** suscriptores de otra plataforma (vía API key, como con Flow).
- A futuro: que **cada cliente** (SaaS) cobre con **su propia** cuenta de PayPal/Flow.

En todos los casos: **nosotros administramos el contenido** y el sistema **le
recuerda al miembro** cuándo renovar.

---

## 1. La idea central: ACCESO POR PERÍODO

El cambio de fondo: dejar de depender solo de la pasarela y guardar **localmente
hasta cuándo vale** una membresía.

- Nuevo campo en la suscripción: **`acceso_hasta`** (fecha/hora de vencimiento).
- Regla de acceso unificada:
  - **Recurrente (tarjeta Flow / PayPal):** sigue mandando la pasarela (o se
    actualiza `acceso_hasta` con cada cobro vía webhook).
  - **Transferencia / manual / importado / pago mensual:** hay acceso mientras
    `hoy ≤ acceso_hasta`. Cada pago confirmado **extiende** la fecha (+1 mes, etc.).
- Ventaja: un único criterio de acceso para todas las formas de pago.

🟡 **Decisión:** ¿`acceso_hasta` va como campo nuevo en `CheckoutSession`, o
creamos un modelo `Membresia`/`Acceso` separado? ✅ *Recomiendo campo en
`CheckoutSession` para no romper lo existente; migrar a modelo propio si crece.*

---

## 2. Multi-pasarela (arquitectura)

Hoy `CheckoutSession.provider` es `flow` | `paypal`. Lo ampliamos a un conjunto
extensible y estandarizamos qué hace cada "método de pago":

| provider | ¿Cobro automático? | Acceso | Confirmación |
| --- | --- | --- | --- |
| `flow` (tarjeta) | Sí (recurrente) | live + período | webhook Flow |
| `paypal` | Sí (recurrente) | live + período | webhook PayPal |
| `flow_mensual` | No (pago único cada mes) | por período | retorno/webhook Flow |
| `transferencia` | No | por período | admin confirma (o comprobante) |
| `manual` | No | por período | admin lo crea |
| `importado` | No | por período | API key (otro sistema) |

Cada método implementa una interfaz común: *iniciar cobro*, *confirmar*,
*cancelar* (si aplica), *estado*. Los manuales no tienen pasarela.

🟡 **Decisión:** ¿"transferencia" pasa **por Flow** (Flow permite transferencia en
pago único, y confirma solo) o es **transferencia bancaria pura** que el admin
confirma a mano con el comprobante? ✅ *Recomiendo soportar ambas: Flow para lo
automático-confirmable; manual para lo offline/internacional.*

---

## 3. Pago mensual por Flow (con todos los medios, incl. transferencia)

- Flow **recurrente** exige tarjeta. La **transferencia NO se cobra sola**.
- Solución: usar Flow **pago único** (`payment/create`, permite todos los medios)
  → al confirmarse, se habilitan **30 días** (`acceso_hasta = hoy + 1 mes`).
- El miembro **vuelve a pagar** el mes siguiente; el recordatorio lo avisa.
- Reusa el mismo flujo que ya existe para **Eventos** (compra única vía Flow).

---

## 4. Importar suscripciones (vía API key)

- Endpoint protegido por **API key** (ya existe `ApiKeyAuthentication`) donde otro
  sistema empuja suscriptores: `{email, plan, acceso_hasta, origen}`.
- Crea `CheckoutSession` con `provider="importado"` y su período.
- Sirve para migrar desde planillas u otra web sin pasar por checkout.

🟡 **Decisión:** ¿importación **uno a uno por API** o también **carga masiva CSV**
desde el panel? ✅ *Recomiendo API + un import CSV simple en el admin.*

---

## 5. Recordatorios de pago

- Tarea programada (ya hay **Celery + celery-beat**) que cada día busca membresías
  **por vencer** y envía email al miembro (y opcional al admin).
- Reusa el sistema de email/notificaciones existente; plantillas con la marca.

🟡 **Decisiones:**
- ¿A quién avisa? ✅ *Al miembro siempre; al admin opcional (resumen).*
- ¿Cuándo? ✅ *Sugiero a 3 días y a 1 día antes de `acceso_hasta`, y un aviso al vencer.*
- ¿Aplica también a recurrentes (aviso de "se cobrará")? 🟡 *A definir.*

---

## 6. Multi-cliente / SaaS: cada cliente con su PayPal (y Flow)

El objetivo: que **cada cliente** conecte **su propia** cuenta y la plata le llegue
**directo**, sin que nosotros seamos intermediarios del dinero.

- **Forma simple y recomendada ✅:** cada cliente guarda en el sistema **sus
  propias credenciales** (PayPal Client ID/Secret, Flow API key/secret). El sistema
  cobra *usando esas credenciales* → el dinero entra a **su** cuenta. **No** requiere
  el "PayPal Partner/Commerce Platform" (que es oneroso y burocrático).
- Implica **multi-tenancy**: un modelo `Cliente/Organización` con su config de pago
  (credenciales **encriptadas**), y que los servicios `flow.py`/`paypal.py` lean las
  credenciales **del cliente actual** en vez de las globales del `.env`.
- Encaja con la dirección SaaS ya planteada (tenancy + pago por-cliente + subdominio).

🟡 **Decisiones grandes:**
- ¿Multi-tenant **ahora** o lo dejamos para una fase posterior? ✅ *Recomiendo
  fases 1–3 primero (resuelven "dar acceso ya"); multi-tenant como fase aparte.*
- ¿Las credenciales se cargan en un **panel de configuración** del cliente?
  ✅ *Sí: pantalla "Medios de pago" donde pega sus llaves; se guardan encriptadas.*

> **Sobre PayPal por API:** conectar la cuenta de cada cliente NO necesita nada
> "extra" raro: basta con que **cada cliente cree su propia app en PayPal** (como
> hiciste con Zoom) y pegue su **Client ID/Secret** en el sistema. Con eso la
> plataforma cobra en su nombre y el dinero llega a su cuenta.

---

## 7. Cambios de datos (borrador)

- `CheckoutSession`:
  - `provider`: agregar `flow_mensual`, `transferencia`, `manual`, `importado`.
  - `acceso_hasta` (datetime, nullable).
  - `origen` / `nota` (texto, para registrar de dónde vino el alta manual/importada).
  - opcional: `comprobante_url` (para transferencias con comprobante).
- (Fase SaaS) Modelo `Cliente/Organización` + `ConfigPago` (credenciales encriptadas).
- Ajustar la **lógica de acceso** (`_member_active_plan_ids`) para considerar
  `acceso_hasta` en los métodos no recurrentes.

---

## 8. Roadmap por fases (propuesta)

| Fase | Qué incluye | Valor | Tamaño | Estado |
| --- | --- | --- | --- | --- |
| **1** | Acceso por período + alta manual + **recordatorios** | Resuelve "dar acceso ya", casos internacionales | Medio | 🔁 **Reemplazado por link de pago** (la alta manual se quitó); recordatorios pendientes |
| **2** | **Link de pago de Flow** (todos los medios → período) | Cobro online sin tarjeta recurrente, sin tracking manual | Medio | 🟢 **LISTO** (sandbox verificado) |
| **3** | **Importar** suscripciones (API key + CSV) | Migrar desde otras plataformas | Chico-Medio | ⏳ Pendiente |
| **4** | **Multi-cliente (SaaS)**: credenciales de pago por cliente (PayPal/Flow propios) | Escalar a varios clientes | **Grande** | ⏳ Planificado (no este ciclo) |

✅ **Recomendación:** arrancar por **Fase 1 + 2** (cubren lo urgente: dar acceso a
gente que paga por transferencia / internacional). Fases 3 y 4 después.

### Avance Fase 1 (implementado el 2026-06-24)
- `CheckoutSession`: proveedores `manual`/`imported`/`flow_mensual` + campos
  `access_until` y `origin_note` (migración `0014`).
- Lógica de acceso: los proveedores por período valen mientras `access_until >= hoy`
  (probado: da acceso vigente, lo quita al vencer).
- "Mi suscripción" muestra las membresías por período (estado + vence el …).
- Panel admin: **CRUD `/admin/membresias-manuales`** (endpoint `manual-subscriptions`,
  con acción `extend` para renovar +N meses).
- **Pendiente de Fase 1:** recordatorios automáticos de vencimiento (tarea Celery).

### Decisiones tomadas
1. Multi-tenant (Fase 4): **planificado para después**, no este ciclo.
2. Transferencia: por ahora **alta manual** (admin confirma); Flow mensual en Fase 2.
3. Recordatorios: al **miembro**; a **3 días y 1 día antes** + aviso al vencer *(por implementar)*.
4. Importar: **API + CSV** (Fase 3).
5. El admin **puede extender/acortar** `access_until` desde el panel (✓ incluido).

---

## 9. Riesgos y cosas a cuidar

- **Conciliación de pagos manuales:** depende de que el admin confirme/extienda;
  definir bien el flujo para no dar/quitar acceso por error.
- **Encriptado de credenciales** (fase SaaS): nunca en texto plano ni en git.
- **Reembolsos/contracargos** en pagos únicos: definir política.
- **Webhooks** de Flow/PayPal para que el período se extienda solo cuando se pueda.

---

## 10. Preguntas abiertas (para cerrar el plan)

1. ¿Multi-tenant (Fase 4) es objetivo de **este** ciclo o lo dejamos planificado?
2. Transferencia: ¿**por Flow** (auto-confirmable) y/o **bancaria manual** (admin)?
3. Recordatorios: ¿a cuántos días y a quién (miembro/admin)?
4. Importación: ¿solo API o también **CSV** desde el panel?
5. ¿El admin podrá **extender/acortar** manualmente el `acceso_hasta` de cualquiera?
