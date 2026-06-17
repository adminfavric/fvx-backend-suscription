# Multi-tenant — Blueprint pendiente de implementación

> Este documento captura el diseño recomendado para introducir aislamiento
> por "tenant" (comunidad / edificio / organización) cuando se agreguen los
> modelos financieros (`Expense`, `Income`, `Transaction`, `Document`, etc.).
>
> **No hay código todavía**. Cuando estés listo para implementar:
> 1. Decide el nombre del tenant (sección 1).
> 2. Crea el modelo y la M2M con `User` (sección 2).
> 3. Agrega middleware + abstract `TenantScopedModel`/`TenantScopedViewSet` (sección 3).
> 4. Aplica el patrón a **cada** modelo financiero nuevo (sección 4).
> 5. Habilita el check de CI (sección 5).
>
> El audit de seguridad de 2026-05-27 marcó esto como ALTA prioridad —
> sin enforcement automático, **un solo bug de filtrado expone datos
> entre comunidades distintas** (riesgo legal + financiero).

---

## Contexto: por qué importa

`fvx-med` va a manejar:
- **Dinero**: gastos comunes, ingresos, transferencias entre cuentas.
- **PII**: residentes con RUT, teléfonos, direcciones (Ley 19.628 en Chile).
- **Documentos contables**: PDFs de facturas, actas, balances.

Si una comunidad A puede ver/modificar datos de una comunidad B, no es solo
un bug — es una **brecha legal** que termina en multa de la SBIF / SII /
demanda civil de la comunidad afectada. Por eso este patrón no es
"nice-to-have", es la fundación que define cómo se escribe el resto.

## Decisión 1: nombre del tenant

Pendiente. Recomendado **`Community`** porque:
- En Chile la entidad jurídica que firma el contrato del administrador es
  la "comunidad de copropietarios" (Ley 19.537), no el edificio físico.
- Una community puede agrupar varios edificios (`Building`) — flexible
  para condominios.
- Independiza el dominio financiero del dominio inmobiliario.

Alternativas evaluadas:
- `Building` — más simple pero no representa la entidad legal.
- `Organization` — neutro, sirve si el template se reutiliza para clínicas
  multi-sede o estudios contables. Costo: no captura "edificios físicos"
  como concepto.

## Decisión 2: relación usuario ↔ tenant

**M2M vía `CommunityMembership`** (tabla intermedia con metadata):

```python
class CommunityMembership(TimeStampedModel):
    user = models.ForeignKey(User, on_delete=CASCADE, related_name='memberships')
    community = models.ForeignKey(Community, on_delete=CASCADE, related_name='memberships')
    role = models.CharField(max_length=20, choices=[
        ('owner', 'Propietario'),
        ('admin', 'Administrador'),
        ('treasurer', 'Tesorero'),
        ('viewer', 'Visualizador'),
    ])
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [('user', 'community')]
        indexes = [models.Index(fields=['user', 'is_active'])]
```

Por qué M2M y no FK simple:
- Un property manager profesional administra 5–50 comunidades distintas.
- Un residente solo pertenece a 1, pero forzar siempre M2M deja el modelo
  simétrico y soporta "soy dueño de un depto en edificio X y también soy
  miembro del comité de edificio Y".
- El `role` puede diferir entre comunidades para el mismo usuario.

## Decisión 3: cómo viaja el tenant activo

**Header HTTP `X-Community-ID`** que el frontend envía con cada request.
Razones (vs subdominios o URL prefix):
- Cero cambio de URLs — los viewsets DRF actuales siguen igual.
- El selector del topbar (mockup que vimos antes con "Obra activa Planta
  Concón TEGA") despacha el header con `inject(HttpInterceptor)`.
- La community activa se persiste en `Profile.last_active_community_id`
  para que al re-abrir el browser vuelva a la última usada.

Implementación backend:

```python
# api/middleware/tenant.py
class CommunityScopeMiddleware:
    """Inyecta request.community y valida acceso del usuario."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.community = None
        community_id = request.headers.get('X-Community-Id')
        if community_id and request.user.is_authenticated:
            try:
                m = CommunityMembership.objects.select_related('community').get(
                    user=request.user, community_id=community_id, is_active=True,
                )
                request.community = m.community
                request.community_role = m.role
            except CommunityMembership.DoesNotExist:
                return JsonResponse(
                    {'detail': 'Community access denied'}, status=403,
                )
        return self.get_response(request)
```

## Implementación: `TenantScopedModel` + `TenantScopedViewSet`

### Abstract model

```python
# api/models/base.py — al final del archivo
class TenantScopedModel(models.Model):
    """
    Base abstracta para modelos cuyos datos pertenecen a UNA community.
    Todos los modelos financieros DEBEN heredar de esta.
    """
    community = models.ForeignKey(
        'api.Community',
        on_delete=models.PROTECT,  # no permitir borrar community con datos
        related_name='+',
        db_index=True,
    )

    class Meta:
        abstract = True
        indexes = [
            models.Index(fields=['community']),
        ]
```

### ViewSet con filtrado automático

```python
# api/views/base.py
class TenantScopedViewSetMixin:
    """
    Filtra automáticamente el queryset por request.community.
    Bloquea queries sin community activa.
    """
    def get_queryset(self):
        qs = super().get_queryset()
        community = getattr(self.request, 'community', None)
        if community is None:
            # Sin community activa = sin datos (mejor que 500).
            return qs.none()
        return qs.filter(community=community)

    def perform_create(self, serializer):
        community = getattr(self.request, 'community', None)
        if community is None:
            raise PermissionDenied('Selecciona una community antes de crear.')
        serializer.save(community=community)
```

Uso:

```python
class ExpenseViewSet(TenantScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Expense.objects.all()         # ← TenantScopedViewSetMixin filtra
    serializer_class = ExpenseSerializer
    permission_classes = [IsAuthenticated]
```

**Imposible olvidar el filtro**. Aunque el dev escriba `Expense.objects.all()`,
el mixin filtra antes de salir el response.

## Decisión 4: checklist obligatorio al crear un modelo financiero nuevo

Antes de mergear cualquier PR que agregue un modelo de dominio financiero:

- [ ] `class XYZ(TenantScopedModel, ...)` — hereda la base
- [ ] Su `ViewSet` hereda `TenantScopedViewSetMixin`
- [ ] Si tiene relaciones a otros modelos del mismo dominio, esas relaciones
      apuntan SOLO a registros de la misma community (validar en `clean()`)
- [ ] El admin de Django filtra por community para staff non-superuser
- [ ] Auditlog: `auditlog.register(XYZ)` en `api/auditing.py`
- [ ] Test que verifica que un usuario de community A NO ve datos de B

## Decisión 5: Test de CI que enforza el patrón

```python
# api/tests/test_tenant_isolation.py
from django.apps import apps
from api.models.base import TenantScopedModel

# Modelos que LEGÍTIMAMENTE no son tenant-scoped (compartidos / globales).
TENANT_UNSCOPED_WHITELIST = {
    'User', 'Profile', 'Notification', 'UiSettings',
    'Menu', 'MenuSection', 'MenuItem',
    'ApiKey', 'SocialAccount',
    'Community', 'CommunityMembership',  # el tenant mismo
    'LogEntry',  # auditlog
}

def test_all_models_are_tenant_scoped_or_whitelisted():
    """
    Cualquier modelo nuevo bajo `api.` debe heredar TenantScopedModel
    o estar explícitamente en la whitelist (con justificación en code review).
    """
    offenders = []
    for model in apps.get_app_config('api').get_models():
        if model.__name__ in TENANT_UNSCOPED_WHITELIST:
            continue
        if not issubclass(model, TenantScopedModel):
            offenders.append(model.__name__)
    assert not offenders, (
        f"Modelos sin tenant scoping ni en whitelist: {offenders}. "
        f"Heredar `TenantScopedModel` o agregar a TENANT_UNSCOPED_WHITELIST "
        f"con justificación."
    )
```

Este test corre con `pytest`. Cualquier PR que agregue un modelo sin
heredar de la base **falla CI** — el dev tiene que tomar una decisión
consciente.

## Migración

Cuando se implemente:
1. Crear `Community` + `CommunityMembership` en una migración nueva.
2. Para cada usuario existente, asignarle membership a una community por
   defecto (idealmente, una community "Sistema" o la creada manualmente
   por el cliente).
3. Agregar middleware al `MIDDLEWARE` de settings.
4. Para CADA modelo financiero que se agregue después, hereda
   `TenantScopedModel` desde el día 1 — no se permite agregar `community`
   FK después porque genera datos legacy sin tenant.

## Notas operacionales

- **Backup**: respaldos por community (selectivos) facilitan recuperación
  ante pérdida parcial.
- **Exportación de datos**: comando management `dump_community_data <id>`
  útil para GDPR-like requests (Ley 19.628 art. 12 — derecho de acceso).
- **Cross-tenant queries (admin global)**: para reportes consolidados del
  super-admin (ver todas las communities), usar un mixin alterno
  `GlobalScopedViewSet` que NO filtra — exclusivo para superusers.
- **Cache de membership**: en cada request el middleware hace 1 query
  extra. Cachear con `cache_page` a nivel ruta o usar Redis con TTL bajo
  (60s) si el volumen crece.

## Cuándo se debe implementar

**Antes** de cualquiera de estos:
- Primer modelo de `Expense` / `Income` / `Transaction` / `Document`.
- Primer endpoint que devuelva datos financieros agregados.
- Primer endpoint de exportación de Excel/PDF que cruce datos.

**Si se posterga y luego se quieren agregar comunidades**: hay que hacer
backfill de `community` en todos los registros existentes — riesgo de
asignación errónea + downtime durante la migración. Por eso vale la pena
hacerlo el día que se decida agregar el primer modelo financiero, antes
de poblar datos reales.
