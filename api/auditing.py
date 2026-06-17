"""Registro central de modelos en ``django-auditlog``.

`AuditlogMiddleware` (declarado en ``core.settings.MIDDLEWARE``) inyecta el
``actor`` (usuario autenticado) en cada operación HTTP. La librería intercepta
los signals ``post_save`` / ``post_delete`` y persiste un ``LogEntry`` por
cambio. Sin registrar explícitamente cada modelo (lo que hace este módulo) la
captura es **silenciosa**: la dependencia está instalada pero no produce
ninguna traza — ese fue el hallazgo crítico del audit.

**Política para fvx-med (admin de edificios / dinero / PII)**

Auditamos los modelos que afectan:

1. **Identidad y privilegios** — `User`, `SocialAccount`.
   Cambios de password, rol, is_staff, vinculación social → no-repudio.
   (Los campos antes en ``Profile`` ahora viven en ``User`` directamente.)
2. **Credenciales programáticas** — `ApiKey`. Creación/revocación.
3. **Capacidades de la UI** — `Menu`, `MenuSection`, `MenuItem`.
   Alterar el menú cambia QUÉ ve un rol → poder admin disfrazado.

**NO auditamos** modelos que solo guardan estado UI per-user (`UiSettings`)
ni notificaciones efímeras (`Notification`).

**Campos excluidos del log**
- ``User.password`` — es un hash de Django, no aporta info diff; ensucia.
- ``ApiKey.secret_hash`` — mismo razonamiento; además, dejar registro de
  cuándo cambia el hash equivale a registrar rotación, lo cual ya queda
  reflejado por el cambio en ``last_rotated_at`` o ``modified``.
- Campos auto (``created``, ``modified``) — auditlog ya tiene ``timestamp``.

Para modelos futuros (Building, Expense, Transaction, Document) **registrar
acá inmediatamente al crearlos**, antes de mergear la PR. Se recomienda un
check de CI que falle si un modelo nuevo no queda registrado aquí, para forzar
este patrón.
"""

from auditlog.registry import auditlog
from django.contrib.auth import get_user_model

from .models.base import ApiKey, Menu, MenuItem, MenuSection
from .models.social import SocialAccount

User = get_user_model()

# ── Identidad y permisos ───────────────────────────────────────────────
auditlog.register(
    User,
    exclude_fields=["password", "last_login", "date_joined"],
)
auditlog.register(
    SocialAccount,
    exclude_fields=["created", "modified"],
)

# ── Credenciales programáticas ─────────────────────────────────────────
auditlog.register(
    ApiKey,
    exclude_fields=["secret_hash", "created", "modified"],
)

# ── Configuración de UI con poder admin (menú visible por rol) ─────────
auditlog.register(Menu, exclude_fields=["created", "modified"])
auditlog.register(MenuSection, exclude_fields=["created", "modified"])
auditlog.register(MenuItem, exclude_fields=["created", "modified"])
