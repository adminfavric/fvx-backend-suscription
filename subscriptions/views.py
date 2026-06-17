"""DRF views for subscription plans.

CRUD over plans for the admin frontend. On create/update the plan is pushed to
Flow (best-effort): a Flow failure does not fail the request — the error is
stored on ``plan.last_sync_error`` and surfaced via the serializer so the UI can
show it. Drafts (no amount) are never sent to Flow.
"""

from django.conf import settings
from django.http import HttpResponseRedirect, JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, generics, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import IsAdminOrReadOnly

import secrets

from django.db.models import Q
from django.db.models.deletion import ProtectedError
from django.utils import timezone

from .models import CheckoutSession, ContentItem, ContentSchedule, Event, EventOrder, Lead, Plan
from .serializers import (
    ContentItemSerializer,
    ContentScheduleSerializer,
    EventSerializer,
    LeadSerializer,
    MemberContentSerializer,
    PlanSerializer,
    PublicEventSerializer,
    PublicMembershipSerializer,
)
from .services import FlowError, get_flow_client, import_plans_from_flow, sync_plan_to_flow
from .services import member_auth


class PlanViewSet(viewsets.ModelViewSet):
    queryset = Plan.objects.all().order_by("order", "name")
    serializer_class = PlanSerializer
    permission_classes = [IsAuthenticated, IsAdminOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["is_active", "is_public", "featured", "interval"]
    search_fields = ["name", "flow_plan_id", "tagline"]
    ordering_fields = ["name", "amount", "order", "created", "modified"]

    def list(self, request, *args, **kwargs):
        """El admin es un espejo de Flow: refrescamos desde Flow (best-effort)
        antes de listar, para que siempre muestre lo mismo que Flow (activos e
        inactivos). Si Flow falla, se devuelve el último espejo conocido."""
        try:
            import_plans_from_flow()
        except FlowError:
            pass
        return super().list(request, *args, **kwargs)

    def perform_create(self, serializer):
        self._sync(serializer.save())

    def perform_update(self, serializer):
        self._sync(serializer.save())

    def perform_destroy(self, instance):
        """ "Eliminar" un plan = desactivarlo en Flow + inactivarlo localmente.
        Si no tiene historial (sin CheckoutSession), se borra la fila; si lo
        tiene (PROTECT), se conserva inactiva (no se puede borrar de verdad)."""
        if instance.flow_plan_id and instance.flow_synced_at:
            try:
                get_flow_client().delete_plan(instance.flow_plan_id)
            except FlowError:
                pass
        try:
            instance.delete()
        except ProtectedError:
            instance.is_active = False
            instance.flow_status = 0
            instance.is_public = False
            instance.save(update_fields=["is_active", "flow_status", "is_public", "modified"])

    @action(detail=False, methods=["post"], url_path="import-from-flow")
    def import_from_flow(self, request):
        """Pull the plans that exist in Flow into the local catalogue."""
        try:
            result = import_plans_from_flow()
        except FlowError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(result)

    def _sync(self, plan: Plan) -> None:
        """Best-effort push to Flow; the error (if any) is stored on the plan."""
        if not plan.amount:
            return
        try:
            sync_plan_to_flow(plan)
        except FlowError:
            pass  # error already persisted to plan.last_sync_error


def _flow_list_params(request):
    """Parsea start/limit/filter de la query string para los listados de Flow."""
    try:
        start = max(int(request.query_params.get("start", 0)), 0)
    except (TypeError, ValueError):
        start = 0
    try:
        limit = min(max(int(request.query_params.get("limit", 100)), 1), 100)
    except (TypeError, ValueError):
        limit = 100
    return {"start": start, "limit": limit, "filter": request.query_params.get("filter") or None}


class FlowCustomersListView(APIView):
    """Clientes desde Flow (espejo de solo lectura para el admin). Flow es la
    fuente de verdad; no se persiste localmente."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            data = get_flow_client().list_customers(**_flow_list_params(request))
        except FlowError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(data)


class FlowSubscriptionsListView(APIView):
    """
    Suscripciones desde Flow (espejo de solo lectura para el admin). Flow exige
    ``planId`` en ``subscription/list`` (las lista por plan), así que aquí se
    agregan las suscripciones de TODOS los planes de Flow. Se enriquece cada
    suscripción con el nombre del plan (desde el espejo local) para mostrarlo.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        flow = get_flow_client()
        try:
            plans_resp = flow.list_plans(limit=100)
        except FlowError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        plan_names = dict(Plan.objects.values_list("flow_plan_id", "name"))
        customers = self._customer_map(flow)
        rows = []
        errors = []
        for fp in plans_resp.get("data", []) or []:
            plan_id = fp.get("planId")
            if not plan_id:
                continue
            try:
                sub_resp = flow.list_subscriptions(plan_id=plan_id, limit=100)
            except FlowError as exc:
                errors.append(f"{plan_id}: {exc}")
                continue
            for sub in sub_resp.get("data", []) or []:
                sub["planName"] = plan_names.get(plan_id) or fp.get("name") or plan_id
                sub["customer"] = customers.get(sub.get("customerId"))
                rows.append(sub)
        return Response({"total": len(rows), "data": rows, "errors": errors})

    @staticmethod
    def _customer_map(flow) -> dict:
        """Mapa customerId → {name, email} desde Flow (para mostrar el nombre del
        cliente en vez del id). Recorre customer/list paginado."""
        out: dict = {}
        start = 0
        while True:
            try:
                resp = flow.list_customers(start=start, limit=100)
            except FlowError:
                break
            rows = resp.get("data", []) or []
            for c in rows:
                cid = c.get("customerId")
                if cid:
                    out[cid] = {"name": c.get("name"), "email": c.get("email")}
            total = resp.get("total", 0)
            start += 100
            if start >= total or not rows:
                break
        return out


class PublicMembershipListView(generics.ListAPIView):
    """
    Catálogo público de membresías. Muestra los planes que están **activos en
    Flow** (``flow_status == 1``, columna "Flow" en el admin) y **marcados como
    públicos** (``is_public``, columna "Público"). Así Flow sigue siendo la
    fuente de verdad (el plan debe existir y estar sincronizado allí) y el admin
    controla qué planes se publican en el sitio + su enriquecimiento (textos,
    imagen). Para traer planes creados directamente en el panel de Flow se usa el
    botón "Importar desde Flow" del admin (acción manual, no en cada carga).
    """

    queryset = Plan.objects.filter(is_public=True, flow_status=1).order_by("order", "name")
    serializer_class = PublicMembershipSerializer
    permission_classes = [AllowAny]
    authentication_classes = []
    pagination_class = None


class EventViewSet(viewsets.ModelViewSet):
    """CRUD admin de eventos especiales (compra única)."""

    queryset = Event.objects.all().order_by("order", "name")
    serializer_class = EventSerializer
    permission_classes = [IsAuthenticated, IsAdminOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["is_active", "is_public"]
    search_fields = ["name", "subtitle"]
    ordering_fields = ["name", "price", "order", "date", "created"]

    def perform_destroy(self, instance):
        """Si el evento tiene compras (PROTECT), no se borra: se inactiva."""
        try:
            instance.delete()
        except ProtectedError:
            instance.is_active = False
            instance.is_public = False
            instance.save(update_fields=["is_active", "is_public", "modified"])


class PublicEventListView(generics.ListAPIView):
    """Eventos públicos para la página de eventos (compra directa)."""

    queryset = Event.objects.filter(is_public=True, is_active=True).order_by("order", "date", "name")
    serializer_class = PublicEventSerializer
    permission_classes = [AllowAny]
    authentication_classes = []
    pagination_class = None


class EventCheckoutView(APIView):
    """
    Pago ÚNICO de un evento: crea la orden y un pago en Flow (``payment/create``).
    Devuelve la URL de Flow a la que redirigir al comprador.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        slug = (request.data.get("event_slug") or "").strip()
        name = (request.data.get("name") or "").strip()
        email = (request.data.get("email") or "").strip()
        if not (slug and name and email):
            return Response({"detail": "event_slug, name y email son requeridos."}, status=400)

        event = Event.objects.filter(slug=slug, is_public=True, is_active=True).first()
        if not event:
            return Response({"detail": "Evento no encontrado."}, status=404)
        if not event.price:
            return Response({"detail": "Este evento no tiene precio definido aún."}, status=409)

        commerce_order = f"EVT-{event.id}-{secrets.token_hex(5)}"
        order = EventOrder.objects.create(
            event=event, name=name, email=email,
            commerce_order=commerce_order, amount=event.price,
            status=EventOrder.Status.PENDING,
        )

        flow = get_flow_client()
        base = settings.PUBLIC_API_BASE_URL
        try:
            pay = flow.create_payment(
                commerceOrder=commerce_order,
                subject=event.name,
                amount=event.price,
                currency=event.currency or "CLP",
                email=email,
                urlConfirmation=f"{base}/api/v1/public/events/confirm/",
                urlReturn=f"{base}/api/v1/public/events/return/",
            )
        except FlowError as exc:
            order.status = EventOrder.Status.FAILED
            order.save(update_fields=["status", "modified"])
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        order.flow_token = pay.get("token", "")
        order.flow_order = str(pay.get("flowOrder", ""))
        order.save(update_fields=["flow_token", "flow_order", "modified"])
        return Response({"redirect_url": f"{pay['url']}?token={pay['token']}"})


def _settle_event_payment(token: str) -> EventOrder | None:
    """Consulta el estado del pago en Flow y actualiza la orden. Compartido por
    el retorno (browser) y la confirmación (webhook)."""
    if not token:
        return None
    order = EventOrder.objects.filter(flow_token=token).first()
    if not order:
        return None
    try:
        st = get_flow_client().get_payment_status(token)
        order.status = (
            EventOrder.Status.PAID if str(st.get("status")) == "2" else EventOrder.Status.FAILED
        )
        order.flow_order = str(st.get("flowOrder", order.flow_order))
        order.save(update_fields=["status", "flow_order", "modified"])
    except FlowError:
        pass
    return order


@method_decorator(csrf_exempt, name="dispatch")
class EventConfirmView(View):
    """Webhook server-to-server de Flow (``urlConfirmation``). Solo en prod/URL pública."""

    def post(self, request):
        _settle_event_payment(request.POST.get("token", ""))
        return JsonResponse({"ok": True})


@method_decorator(csrf_exempt, name="dispatch")
class EventReturnView(View):
    """Retorno del navegador tras el pago (``urlReturn``)."""

    def get(self, request):
        return self._handle(request)

    def post(self, request):
        return self._handle(request)

    def _handle(self, request):
        token = request.POST.get("token") or request.GET.get("token")
        order = _settle_event_payment(token)
        result = "ok" if order and order.status == EventOrder.Status.PAID else "fail"
        slug = order.event.slug if order else ""
        return HttpResponseRedirect(f"{settings.FRONTEND_BASE_URL}/eventos?pago={result}&evento={slug}")


class ContentItemViewSet(viewsets.ModelViewSet):
    """CRUD admin de las piezas de la biblioteca (independientes del plan)."""

    queryset = ContentItem.objects.all().order_by("order", "-created")
    serializer_class = ContentItemSerializer
    permission_classes = [IsAuthenticated, IsAdminOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["kind", "is_published"]
    search_fields = ["title", "text"]
    ordering_fields = ["title", "order", "created"]


class ContentScheduleViewSet(viewsets.ModelViewSet):
    """CRUD admin de la Programación: asigna contenido a planes con rango de fechas."""

    queryset = ContentSchedule.objects.select_related("content", "plan").all()
    serializer_class = ContentScheduleSerializer
    permission_classes = [IsAuthenticated, IsAdminOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["plan", "content"]
    search_fields = ["content__title", "plan__name"]
    ordering_fields = ["starts_at", "ends_at", "created"]


class FlowSubscriptionCancelView(APIView):
    """POST {subscription_id, at_period_end?} → cancela la suscripción en Flow (admin)."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        sub_id = (request.data.get("subscription_id") or "").strip()
        if not sub_id:
            return Response({"detail": "subscription_id requerido."}, status=400)
        at_period_end = request.data.get("at_period_end", True)
        try:
            res = get_flow_client().cancel_subscription(sub_id, at_period_end=bool(at_period_end))
        except FlowError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(res)


class FlowSubscriptionReactivateView(APIView):
    """
    POST {subscription_id} → "reactiva" re-suscribiendo: Flow no tiene resume, pero
    la tarjeta del cliente sigue registrada, así que se crea una nueva suscripción
    al mismo plan/cliente (admin).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        sub_id = (request.data.get("subscription_id") or "").strip()
        if not sub_id:
            return Response({"detail": "subscription_id requerido."}, status=400)
        flow = get_flow_client()
        try:
            sub = flow.get_subscription(sub_id)
            plan_id = sub.get("planId")
            customer_id = sub.get("customerId")
            if not (plan_id and customer_id):
                return Response({"detail": "No se pudo determinar plan/cliente de la suscripción."}, status=400)
            res = flow.create_subscription(plan_id=plan_id, customer_id=customer_id)
        except FlowError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(res)


class PublicLeadCreateView(generics.CreateAPIView):
    """Captura pública de leads (newsletter / contacto / maratón). Sin auth."""

    serializer_class = LeadSerializer
    permission_classes = [AllowAny]
    authentication_classes = []


class LeadViewSet(viewsets.ReadOnlyModelViewSet):
    """Mensajes entrantes (contacto/newsletter/maratón) — solo lectura, admin."""

    queryset = Lead.objects.all().order_by("-created")
    serializer_class = LeadSerializer
    permission_classes = [IsAuthenticated, IsAdminOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["kind", "source"]
    search_fields = ["name", "email", "subject", "message"]
    ordering_fields = ["created", "kind"]


# ── Área de miembros (login sin contraseña + contenido por suscripción) ──────
class MemberRequestCodeView(APIView):
    """POST {email} → envía un código de acceso por email."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        email = (request.data.get("email") or "").strip()
        if not email:
            return Response({"detail": "Email requerido."}, status=400)
        try:
            member_auth.request_code(email)
        except Exception:  # noqa: BLE001 — no filtrar detalles del email al cliente
            return Response({"detail": "No se pudo enviar el código. Intenta más tarde."}, status=502)
        return Response({"detail": "Código enviado."})


class MemberVerifyCodeView(APIView):
    """POST {email, code} → si es válido, devuelve un token de sesión de miembro."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        email = (request.data.get("email") or "").strip()
        code = (request.data.get("code") or "").strip()
        if not (email and code):
            return Response({"detail": "Email y código requeridos."}, status=400)
        if not member_auth.verify_code(email, code):
            return Response({"detail": "Código inválido o expirado."}, status=401)
        return Response({"token": member_auth.issue_token(email), "email": email.lower()})


def _member_email(request) -> str | None:
    """Lee el Bearer token de miembro y devuelve su email (o None)."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    return member_auth.email_from_token(auth[7:].strip())


class MemberContentView(APIView):
    """
    GET (Bearer token de miembro) → contenido de los planes a los que el miembro
    tiene una suscripción ACTIVA. El acceso se determina por las
    ``CheckoutSession`` con estado ``subscribed`` para ese email (espejo local de
    Flow). Devuelve también la lista de planes suscritos.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        email = _member_email(request)
        if not email:
            return Response({"detail": "No autenticado."}, status=401)

        plan_ids = self._active_plan_ids(email)
        plans = Plan.objects.filter(id__in=plan_ids).values("slug", "name")

        # Biblioteca = contenido cuya PROGRAMACIÓN está vigente hoy en alguno de
        # los planes activos del miembro (desde ≤ hoy ≤ hasta, o sin fin).
        today = timezone.localdate()
        content_ids = (
            ContentSchedule.objects.filter(
                plan_id__in=plan_ids,
                content__is_published=True,
                starts_at__lte=today,
            )
            .filter(Q(ends_at__isnull=True) | Q(ends_at__gte=today))
            .values_list("content_id", flat=True)
            .distinct()
        )
        items = ContentItem.objects.filter(id__in=content_ids).order_by("order", "-created")
        return Response(
            {
                "email": email,
                "plans": list(plans),
                "content": MemberContentSerializer(items, many=True).data,
            }
        )

    def _active_plan_ids(self, email: str) -> list[int]:
        """
        Planes con suscripción ACTIVA del miembro, verificada EN VIVO contra Flow
        (Flow es la fuente de verdad). Recorre las ``CheckoutSession`` suscritas
        de ese email y consulta el estado real de cada suscripción en Flow
        (``status == 1`` = activa). Si Flow no responde, cae al registro local
        para no bloquear a un miembro al día por una caída puntual de Flow.
        """
        flow = get_flow_client()
        active: set[int] = set()
        sessions = CheckoutSession.objects.filter(
            email__iexact=email, status=CheckoutSession.Status.SUBSCRIBED
        )
        for cs in sessions:
            if not cs.subscription_id:
                active.add(cs.plan_id)
                continue
            try:
                sub = flow.get_subscription(cs.subscription_id)
                if str(sub.get("status")) == "1":
                    active.add(cs.plan_id)
                # status != 1 → cancelada/inactiva → NO se agrega (sin acceso)
            except FlowError:
                active.add(cs.plan_id)  # fallback: no bloquear por caída de Flow
        return list(active)


class MemberAccountView(APIView):
    """GET (Bearer) → suscripciones del miembro con estado real (Flow) + método
    de pago (tarjeta). Base de la sección 'Mi suscripción'."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        email = _member_email(request)
        if not email:
            return Response({"detail": "No autenticado."}, status=401)
        flow = get_flow_client()
        subs, seen = [], set()
        sessions = (
            CheckoutSession.objects.filter(
                email__iexact=email, status=CheckoutSession.Status.SUBSCRIBED
            )
            .exclude(subscription_id="")
            .select_related("plan")
            .order_by("-created")
        )
        for cs in sessions:
            if cs.subscription_id in seen:
                continue
            seen.add(cs.subscription_id)
            info = {
                "subscription_id": cs.subscription_id,
                "plan_name": cs.plan.name,
                "plan_slug": cs.plan.slug,
                "amount": cs.plan.amount,
                "interval": cs.plan.interval,
                "status": None,
                "period_end": None,
                "next_invoice_date": None,
                "cancel_at_period_end": None,
                "card": None,
            }
            try:
                sub = flow.get_subscription(cs.subscription_id)
                info["status"] = sub.get("status")
                info["period_end"] = sub.get("period_end")
                info["next_invoice_date"] = sub.get("next_invoice_date")
                info["cancel_at_period_end"] = sub.get("cancel_at_period_end")
            except FlowError:
                pass
            try:
                cust = flow.get_customer(cs.flow_customer_id)
                info["card"] = {
                    "type": cust.get("creditCardType"),
                    "last4": cust.get("last4CardDigits"),
                }
            except FlowError:
                pass
            subs.append(info)
        return Response({"email": email, "subscriptions": subs})


class MemberCancelView(APIView):
    """POST (Bearer) {subscription_id} → el miembro cancela su propia suscripción
    (al final del período: conserva el acceso hasta que termine lo ya pagado)."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        email = _member_email(request)
        if not email:
            return Response({"detail": "No autenticado."}, status=401)
        sub_id = (request.data.get("subscription_id") or "").strip()
        owns = CheckoutSession.objects.filter(email__iexact=email, subscription_id=sub_id).exists()
        if not (sub_id and owns):
            return Response({"detail": "Suscripción no encontrada."}, status=404)
        try:
            res = get_flow_client().cancel_subscription(sub_id, at_period_end=True)
        except FlowError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(res)


class CheckoutStartView(APIView):
    """
    Public checkout step 1: create the Flow customer and start credit-card
    registration. Returns the Flow URL the browser must be redirected to (where
    the customer enters the card — sandbox test cards apply).
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        data = request.data
        slug = (data.get("plan_slug") or "").strip()
        name = (data.get("name") or "").strip()
        email = (data.get("email") or "").strip()
        if not (slug and name and email):
            return Response({"detail": "plan_slug, name and email are required."}, status=400)

        plan = Plan.objects.filter(slug=slug, flow_status=1).first()
        if not plan:
            return Response({"detail": "Plan not found."}, status=404)
        if not plan.flow_synced_at or not plan.flow_plan_id:
            return Response(
                {"detail": "This plan is not available for subscription yet (not synced to Flow)."},
                status=409,
            )

        flow = get_flow_client()
        url_return = f"{settings.PUBLIC_API_BASE_URL}/api/v1/public/checkout/return/"
        try:
            customer_id = self._resolve_customer(flow, name=name, email=email)
            reg = flow.register_customer_card(customer_id=customer_id, url_return=url_return)
        except FlowError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        CheckoutSession.objects.create(
            plan=plan,
            name=name,
            email=email,
            flow_customer_id=customer_id,
            register_token=reg["token"],
            status=CheckoutSession.Status.PENDING_CARD,
        )
        return Response({"redirect_url": f"{reg['url']}?token={reg['token']}"})

    def _resolve_customer(self, flow, *, name: str, email: str) -> str:
        """
        Devuelve el ``customerId`` de Flow para este email, reutilizándolo si ya
        existe (Flow usa el email como ``externalId`` único y rechaza duplicados,
        p. ej. al suscribirse a un 2º plan o reintentar). Estrategia:
        1) Reusar el de una ``CheckoutSession`` previa con el mismo email.
        2) Intentar crearlo.
        3) Si Flow dice que ya existe, buscarlo paginando ``customer/list``
           (el ``filter`` por email de Flow no es fiable).
        """
        prev = (
            CheckoutSession.objects.filter(email=email)
            .exclude(flow_customer_id="")
            .order_by("-created")
            .first()
        )
        if prev:
            return prev.flow_customer_id

        try:
            return flow.create_customer(name=name, email=email, external_id=email)["customerId"]
        except FlowError as exc:
            found = self._find_customer_id(flow, email)
            if found:
                return found
            raise exc

    @staticmethod
    def _find_customer_id(flow, email: str) -> str | None:
        start = 0
        target = email.lower()
        while True:
            resp = flow.list_customers(start=start, limit=100)
            rows = resp.get("data", []) or []
            for cust in rows:
                if (cust.get("externalId") or "").lower() == target or (
                    cust.get("email") or ""
                ).lower() == target:
                    return cust.get("customerId")
            total = resp.get("total", 0)
            start += 100
            if start >= total or not rows:
                return None


@method_decorator(csrf_exempt, name="dispatch")
class CheckoutReturnView(View):
    """
    Public checkout step 2: Flow redirects the customer back here after card
    registration. We confirm the card, create the subscription, then redirect the
    browser to the frontend result page.
    """

    def get(self, request):
        return self._handle(request)

    def post(self, request):
        return self._handle(request)

    def _handle(self, request):
        token = request.GET.get("token") or request.POST.get("token")
        session = CheckoutSession.objects.filter(register_token=token).first() if token else None
        if not session:
            return JsonResponse({"detail": "Unknown checkout token."}, status=400)

        flow = get_flow_client()
        result = "fail"
        try:
            reg = flow.get_register_status(token)
            if str(reg.get("status")) == "1":
                sub = flow.create_subscription(
                    plan_id=session.plan.flow_plan_id,
                    customer_id=session.flow_customer_id,
                )
                session.status = CheckoutSession.Status.SUBSCRIBED
                session.subscription_id = sub.get("subscriptionId", "")
                session.save(update_fields=["status", "subscription_id", "modified"])
                result = "ok"
            else:
                session.status = CheckoutSession.Status.FAILED
                session.save(update_fields=["status", "modified"])
        except FlowError as exc:
            session.error = str(exc)
            session.status = CheckoutSession.Status.FAILED
            session.save(update_fields=["status", "error", "modified"])

        return HttpResponseRedirect(
            f"{settings.FRONTEND_BASE_URL}/membresias/{session.plan.slug}?checkout={result}"
        )
