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

import re
import secrets
from datetime import timedelta

from django.core.cache import cache
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from django.utils import timezone

from .models import (
    CheckoutSession,
    ContentItem,
    ContentSchedule,
    Event,
    EventOrder,
    Lead,
    PaymentProvider,
    Plan,
)
from .serializers import (
    ContentItemSerializer,
    ContentScheduleSerializer,
    EventSerializer,
    LeadSerializer,
    MemberContentSerializer,
    PaymentLinkSerializer,
    PlanSerializer,
    PublicEventSerializer,
    PublicMembershipSerializer,
)
from .services import (
    FlowError,
    PayPalError,
    get_flow_client,
    get_paypal_client,
    import_plans_from_flow,
    sync_plan_to_flow,
    sync_plan_to_paypal,
)
from .services import member_auth, zoom


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
        """Best-effort push a las pasarelas; el error (si lo hay) queda en el plan.
        Flow se sincroniza siempre que haya precio CLP; PayPal solo si el plan lo
        tiene habilitado (``paypal_enabled``)."""
        if not plan.amount:
            return
        try:
            sync_plan_to_flow(plan)
        except FlowError:
            pass  # error already persisted to plan.last_sync_error
        if plan.paypal_enabled:
            try:
                sync_plan_to_paypal(plan)
            except PayPalError:
                pass  # error already persisted to plan.paypal_last_sync_error


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


_PROVIDER_LABELS = {
    PaymentProvider.FLOW: "Flow (tarjeta)",
    PaymentProvider.PAYPAL: "PayPal",
    PaymentProvider.FLOW_ONE_TIME: "Link de pago",
    PaymentProvider.MANUAL: "Manual / transferencia",
    PaymentProvider.IMPORTED: "Importado",
}


class AdminSubscriptionListView(APIView):
    """
    Lista GENÉRICA de suscripciones (todas las pasarelas) para el admin, desde el
    espejo local ``CheckoutSession`` que unifica Flow, PayPal, link de pago y
    manual. Muestra solo las ACTIVAS (``subscribed``) con su ``provider`` (origen),
    plan, cliente, estado y vencimiento (para las de período).
    """

    permission_classes = [IsAuthenticated, IsAdminOrReadOnly]

    def get(self, request):
        qs = (
            CheckoutSession.objects.filter(status=CheckoutSession.Status.SUBSCRIBED)
            .select_related("plan")
            .order_by("-created")
        )
        rows = []
        for cs in qs:
            rows.append(
                {
                    "id": cs.id,
                    "provider": cs.provider,
                    "provider_label": _PROVIDER_LABELS.get(cs.provider, cs.provider),
                    "plan_name": cs.plan.name if cs.plan_id else "—",
                    "name": cs.name,
                    "email": cs.email,
                    "subscription_id": cs.subscription_id,
                    "is_period": cs.is_period_based,
                    "access_until": cs.access_until,
                    # Para período: vigente si la fecha no venció. Para recurrente:
                    # se asume activa (el detalle de Flow lo da la vista en vivo).
                    "is_active": cs.has_period_access if cs.is_period_based else True,
                    "created": cs.created,
                }
            )
        return Response({"data": rows})


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
    throttle_classes = []  # catálogo público de lectura: no consumir el cupo anon
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
    throttle_classes = []  # catálogo público de lectura: no consumir el cupo anon
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


def _add_months(d, months: int):
    """Suma ``months`` meses a una fecha sin dependencias externas (ajusta el día
    al último del mes si hiciera falta)."""
    import calendar

    m = d.month - 1 + months
    year = d.year + m // 12
    month = m % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return d.replace(year=year, month=month, day=day)


def _settle_payment_link(token: str):
    """Consulta el estado del pago del link en Flow y, si está pagado (status 2),
    activa la membresía: ``subscribed`` + ``access_until = hoy + period_months``.
    Compartido por el botón 'Verificar pago' y el webhook de confirmación."""
    if not token:
        return None
    cs = CheckoutSession.objects.filter(
        register_token=token, provider=PaymentProvider.FLOW_ONE_TIME
    ).first()
    if not cs:
        return None
    try:
        st = get_flow_client().get_payment_status(token)
    except FlowError:
        return cs
    if str(st.get("status")) == "2":  # 2 = pagada
        cs.status = CheckoutSession.Status.SUBSCRIBED
        cs.access_until = _add_months(timezone.localdate(), max(1, cs.period_months))
        cs.save(update_fields=["status", "access_until", "modified"])
    return cs


def _create_flow_payment_link(plan, name: str, email: str, months: int) -> CheckoutSession:
    """Crea un pago (link de pago) en Flow y su ``CheckoutSession`` por período
    (pendiente). Devuelve la sesión. Lanza ``FlowError`` si Flow falla. Compartido
    por el panel (admin) y el checkout público (autoservicio)."""
    commerce_order = f"LINK-{plan.id}-{secrets.token_hex(5)}"
    base = settings.PUBLIC_API_BASE_URL
    pay = get_flow_client().create_payment(
        commerceOrder=commerce_order,
        subject=f"{plan.name} · {months} mes(es)",
        amount=plan.amount,
        currency=plan.currency or "CLP",
        email=email,
        urlConfirmation=f"{base}/api/v1/public/payment-link/confirm/",
        urlReturn=f"{base}/api/v1/public/payment-link/return/",
    )
    return CheckoutSession.objects.create(
        provider=PaymentProvider.FLOW_ONE_TIME,
        plan=plan,
        name=name,
        email=email,
        status=CheckoutSession.Status.PENDING_CARD,
        register_token=pay.get("token") or None,
        payment_url=f"{pay['url']}?token={pay['token']}",
        period_months=months,
    )


class PaymentLinkViewSet(viewsets.ModelViewSet):
    """
    Cobros por LINK DE PAGO de Flow (admin). ``create`` genera un link en Flow
    (pago único que habilita N meses) para enviar al cliente; ``verify`` consulta
    el estado del pago y activa la membresía si ya pagó. Reemplaza la modalidad
    manual/transferencia: el cliente paga con cualquier medio dentro de Flow.
    """

    serializer_class = PaymentLinkSerializer
    permission_classes = [IsAuthenticated, IsAdminOrReadOnly]
    queryset = (
        CheckoutSession.objects.filter(provider=PaymentProvider.FLOW_ONE_TIME)
        .select_related("plan")
        .order_by("-created")
    )
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["plan", "status"]
    search_fields = ["email", "name"]
    ordering_fields = ["created", "access_until", "email"]
    # Solo se crea/lista/borra y se verifica; no edición directa del link.
    http_method_names = ["get", "post", "delete", "head", "options"]

    def create(self, request, *args, **kwargs):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        plan = data["plan"]
        email = (data.get("email") or "").strip()
        name = (data.get("name") or "").strip()
        months = max(1, int(data.get("period_months", 1)))
        if not plan.amount:
            return Response(
                {"detail": "El plan no tiene precio definido; no se puede cobrar."},
                status=409,
            )
        try:
            cs = _create_flow_payment_link(plan, name, email, months)
        except FlowError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(self.get_serializer(cs).data, status=status.HTTP_201_CREATED)

    def list(self, request, *args, **kwargs):
        # Caducidad: elimina los cobros PENDIENTES (sin pagar) más antiguos que N
        # días (no tocan los pagados/activos). Limpieza perezosa al abrir la lista.
        days = getattr(settings, "PAYMENT_LINK_PENDING_TTL_DAYS", 7)
        self.get_queryset().filter(
            status=CheckoutSession.Status.PENDING_CARD,
            created__lt=timezone.now() - timedelta(days=days),
        ).delete()
        return super().list(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        # No permitir borrar un cobro ya pagado/activo (es el registro de acceso).
        if self.get_object().status == CheckoutSession.Status.SUBSCRIBED:
            return Response(
                {"detail": "No puedes eliminar un cobro ya pagado/activo."}, status=409
            )
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=["post"])
    def verify(self, request, pk=None):
        """Consulta a Flow si el link ya fue pagado y activa el acceso si corresponde."""
        cs = self.get_object()
        if not cs.register_token:
            return Response({"detail": "Este cobro no tiene token de Flow."}, status=409)
        cs = _settle_payment_link(cs.register_token) or cs
        return Response(
            {**self.get_serializer(cs).data, "paid": cs.status == CheckoutSession.Status.SUBSCRIBED}
        )


@method_decorator(csrf_exempt, name="dispatch")
class PaymentLinkConfirmView(View):
    """Webhook server-to-server de Flow (``urlConfirmation``). Activa el acceso al
    pagar. Solo opera en prod / con URL pública; en local se usa 'Verificar pago'."""

    def post(self, request):
        _settle_payment_link(request.POST.get("token", ""))
        return JsonResponse({"ok": True})


@method_decorator(csrf_exempt, name="dispatch")
class PaymentLinkReturnView(View):
    """Retorno del navegador del cliente tras pagar el link: liquida y redirige al
    sitio público con un parámetro de resultado."""

    def get(self, request):
        return self._handle(request)

    def post(self, request):
        return self._handle(request)

    def _handle(self, request):
        token = request.POST.get("token") or request.GET.get("token")
        cs = _settle_payment_link(token)
        ok = bool(cs and cs.status == CheckoutSession.Status.SUBSCRIBED)
        return HttpResponseRedirect(
            f"{settings.FRONTEND_BASE_URL}/acceso?pago={'ok' if ok else 'pendiente'}"
        )


class PaymentLinkStartView(APIView):
    """
    PÚBLICO (autoservicio del suscriptor): inicia un cobro por LINK DE PAGO de Flow
    para un plan. El visitante completa nombre + correo en el checkout y elige
    "pagar un mes / por transferencia"; aquí creamos el pago en Flow y devolvemos
    la URL a la que se le redirige. Al volver del pago, ``PaymentLinkReturnView``
    activa el acceso automáticamente (sin intervención del admin).
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        slug = (request.data.get("plan_slug") or "").strip()
        name = (request.data.get("name") or "").strip()
        email = (request.data.get("email") or "").strip()
        try:
            months = max(1, int(request.data.get("months", 1)))
        except (TypeError, ValueError):
            months = 1
        if not (slug and name and email):
            return Response({"detail": "plan_slug, name y email son requeridos."}, status=400)

        plan = Plan.objects.filter(slug=slug, is_active=True).first()
        if not plan:
            return Response({"detail": "Membresía no encontrada."}, status=404)
        if not plan.amount:
            return Response({"detail": "Esta membresía no tiene precio definido aún."}, status=409)

        try:
            cs = _create_flow_payment_link(plan, name, email, months)
        except FlowError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response({"redirect_url": cs.payment_url})


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


# ── Checkout PayPal (alternativa internacional en USD) ───────────────────────
class PaypalCheckoutStartView(APIView):
    """
    Checkout PayPal paso 1: crea la suscripción en PayPal (estado
    ``APPROVAL_PENDING``) y devuelve la URL de aprobación a la que redirigir al
    cliente. Es el equivalente internacional de ``CheckoutStartView`` (Flow): en
    vez de registrar una tarjeta chilena, el cliente aprueba la suscripción en su
    cuenta PayPal y se le cobra en USD.
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

        plan = Plan.objects.filter(slug=slug, is_active=True).first()
        if not plan:
            return Response({"detail": "Plan not found."}, status=404)
        if not plan.is_paypal_purchasable:
            return Response(
                {"detail": "Este plan no está disponible por PayPal todavía."},
                status=409,
            )

        # Guard anti-duplicado: si ya tiene una suscripción PayPal activa a este
        # plan, no iniciamos otra (evita el cobro doble).
        if self._has_active_paypal_sub(plan, email):
            return Response(
                {"detail": "Ya tienes una suscripción activa a esta membresía."},
                status=status.HTTP_409_CONFLICT,
            )

        first, _, last = name.partition(" ")
        pp = get_paypal_client()
        return_base = settings.PUBLIC_API_BASE_URL
        try:
            sub = pp.create_subscription(
                plan_id=plan.paypal_plan_id,
                subscriber={
                    "name": {"given_name": first or name, "surname": last or ""},
                    "email_address": email,
                },
                application_context={
                    "brand_name": getattr(settings, "PAYPAL_BRAND_NAME", "Lita Donoso"),
                    "user_action": "SUBSCRIBE_NOW",
                    "shipping_preference": "NO_SHIPPING",
                    "return_url": f"{return_base}/api/v1/public/paypal/checkout/return/",
                    "cancel_url": f"{return_base}/api/v1/public/paypal/checkout/return/?cancel=1",
                },
            )
        except PayPalError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        approval = pp.approval_url(sub)
        if not approval:
            return Response({"detail": "PayPal no devolvió la URL de aprobación."}, status=502)

        CheckoutSession.objects.create(
            provider=PaymentProvider.PAYPAL,
            plan=plan,
            name=name,
            email=email,
            subscription_id=sub.get("id", ""),
            status=CheckoutSession.Status.PENDING_CARD,
        )
        return Response({"redirect_url": approval})

    @staticmethod
    def _has_active_paypal_sub(plan: Plan, email: str) -> bool:
        """True si el email ya tiene una suscripción PayPal ACTIVE a este plan."""
        pp = get_paypal_client()
        sessions = CheckoutSession.objects.filter(
            provider=PaymentProvider.PAYPAL,
            plan=plan,
            email__iexact=email,
            status=CheckoutSession.Status.SUBSCRIBED,
        ).exclude(subscription_id="")
        for cs in sessions:
            try:
                sub = pp.get_subscription(cs.subscription_id)
                if sub.get("status") == "ACTIVE":
                    return True
            except PayPalError:
                continue
        return False


class PaypalSubscriptionRecordView(APIView):
    """
    Registra una suscripción de PayPal creada en el navegador por el botón del SDK
    (``paypal.Buttons`` con ``createSubscription`` → ``onApprove``). El front envía
    ``{plan_slug, name, email, subscription_id}`` con el ``subscriptionID`` que
    devuelve PayPal. Sin esto, PayPal cobraría pero la app no se enteraría (el
    miembro no tendría acceso ni se podría diferenciar/cancelar la suscripción).

    Si hay credenciales de PayPal (secret) verifica el estado real contra la API;
    si no, confía en el cliente (sandbox) y la marca como suscrita.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        data = request.data
        slug = (data.get("plan_slug") or "").strip()
        name = (data.get("name") or "").strip()
        email = (data.get("email") or "").strip()
        sub_id = (data.get("subscription_id") or "").strip()
        if not (slug and name and email and sub_id):
            return Response(
                {"detail": "plan_slug, name, email y subscription_id son requeridos."},
                status=400,
            )

        plan = Plan.objects.filter(slug=slug, is_active=True).first()
        if not plan:
            return Response({"detail": "Plan not found."}, status=404)

        # Idempotencia: si ya registramos esta suscripción, no la duplicamos.
        existing = CheckoutSession.objects.filter(
            provider=PaymentProvider.PAYPAL, subscription_id=sub_id
        ).first()
        if existing:
            return Response({"detail": "ok", "already": True})

        # Verificación en vivo si hay secret configurado (mejor garantía). Sin
        # secret (sandbox sin backend creds) confiamos en el SDK del cliente.
        status_ok = True
        if getattr(settings, "PAYPAL_SECRET", ""):
            try:
                sub = get_paypal_client().get_subscription(sub_id)
                status_ok = sub.get("status") in ("ACTIVE", "APPROVED")
            except PayPalError:
                status_ok = True  # no bloquear por fallo puntual de la API

        CheckoutSession.objects.create(
            provider=PaymentProvider.PAYPAL,
            plan=plan,
            name=name,
            email=email,
            subscription_id=sub_id,
            status=(
                CheckoutSession.Status.SUBSCRIBED
                if status_ok
                else CheckoutSession.Status.FAILED
            ),
        )
        return Response({"detail": "ok", "subscribed": status_ok})


@method_decorator(csrf_exempt, name="dispatch")
class PaypalCheckoutReturnView(View):
    """
    Checkout PayPal paso 2: PayPal redirige al cliente aquí tras aprobar (o
    cancelar) la suscripción. Confirmamos el estado real consultando PayPal y
    redirigimos al frontend con el resultado.
    """

    def get(self, request):
        return self._handle(request)

    def post(self, request):
        return self._handle(request)

    def _handle(self, request):
        # PayPal devuelve ?subscription_id=I-...&token=...&ba_token=...
        sub_id = request.GET.get("subscription_id") or request.POST.get("subscription_id")
        cancelled = request.GET.get("cancel") == "1"
        session = (
            CheckoutSession.objects.filter(
                provider=PaymentProvider.PAYPAL, subscription_id=sub_id
            ).first()
            if sub_id
            else None
        )
        if not session:
            return JsonResponse({"detail": "Unknown PayPal subscription."}, status=400)

        result = "fail"
        if not cancelled:
            try:
                sub = get_paypal_client().get_subscription(sub_id)
                if sub.get("status") in ("ACTIVE", "APPROVED"):
                    session.status = CheckoutSession.Status.SUBSCRIBED
                    session.save(update_fields=["status", "modified"])
                    result = "ok"
                else:
                    session.status = CheckoutSession.Status.FAILED
                    session.save(update_fields=["status", "modified"])
            except PayPalError as exc:
                session.error = str(exc)
                session.status = CheckoutSession.Status.FAILED
                session.save(update_fields=["status", "error", "modified"])
        else:
            session.status = CheckoutSession.Status.FAILED
            session.save(update_fields=["status", "modified"])

        return HttpResponseRedirect(
            f"{settings.FRONTEND_BASE_URL}/membresias/{session.plan.slug}?checkout={result}"
        )


@method_decorator(csrf_exempt, name="dispatch")
class PaypalWebhookView(View):
    """
    Webhook server-to-server de PayPal. Mantiene el estado local en sync cuando la
    suscripción cambia fuera del flujo de checkout (activación, cancelación, pago
    fallido). Verifica la firma si ``PAYPAL_WEBHOOK_ID`` está configurado.
    """

    def post(self, request):
        body = request.body.decode("utf-8") or "{}"
        webhook_id = getattr(settings, "PAYPAL_WEBHOOK_ID", "")
        if webhook_id:
            try:
                ok = get_paypal_client().verify_webhook(
                    headers=dict(request.headers), body=body, webhook_id=webhook_id
                )
            except PayPalError:
                ok = False
            if not ok:
                return JsonResponse({"detail": "invalid signature"}, status=400)

        import json

        try:
            event = json.loads(body)
        except ValueError:
            return JsonResponse({"ok": True})

        event_type = event.get("event_type", "")
        resource = event.get("resource", {}) or {}
        sub_id = resource.get("id")
        if sub_id and event_type.startswith("BILLING.SUBSCRIPTION."):
            session = CheckoutSession.objects.filter(
                provider=PaymentProvider.PAYPAL, subscription_id=sub_id
            ).first()
            if session:
                if event_type == "BILLING.SUBSCRIPTION.ACTIVATED":
                    session.status = CheckoutSession.Status.SUBSCRIBED
                elif event_type in (
                    "BILLING.SUBSCRIPTION.CANCELLED",
                    "BILLING.SUBSCRIPTION.EXPIRED",
                    "BILLING.SUBSCRIPTION.SUSPENDED",
                ):
                    session.status = CheckoutSession.Status.FAILED
                session.save(update_fields=["status", "modified"])
        return JsonResponse({"ok": True})


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
    filterset_fields = ["kind", "source", "is_read", "is_replied"]
    search_fields = ["name", "email", "subject", "message"]
    ordering_fields = ["created", "kind"]

    @action(detail=True, methods=["patch"])
    def mark(self, request, pk=None):
        """Marca el mensaje como leído / respondido. Body: ``{is_read?, is_replied?}``."""
        lead = self.get_object()
        changed = []
        for field in ("is_read", "is_replied"):
            if field in request.data:
                setattr(lead, field, bool(request.data[field]))
                changed.append(field)
        if changed:
            lead.save(update_fields=[*changed, "modified"])
        return Response(self.get_serializer(lead).data)


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


def _member_identity(request) -> tuple[str | None, str | None]:
    """Lee el Bearer token y devuelve ``(email, sid)`` del miembro. El ``sid``
    distingue el login/dispositivo concreto (para el candado de entrada en vivo)."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None, None
    return member_auth.identity_from_token(auth[7:].strip())


def _zoom_live_key(email: str, content_id: int) -> str:
    return f"zoomlive:{email}:{content_id}"


def _member_active_plan_ids(email: str) -> list[int]:
    """
    Planes con suscripción ACTIVA del miembro, verificada EN VIVO contra la
    pasarela correspondiente (Flow o PayPal según ``cs.provider``). Si la pasarela
    no responde, cae al registro local para no bloquear a un miembro al día por una
    caída puntual. Compartido por el contenido y la firma de Zoom.
    """
    active: set[int] = set()
    sessions = CheckoutSession.objects.filter(
        email__iexact=email, status=CheckoutSession.Status.SUBSCRIBED
    )
    for cs in sessions:
        # Acceso por período (manual/importado/pago único): vale mientras
        # access_until >= hoy. No se consulta ninguna pasarela.
        if cs.is_period_based:
            if cs.has_period_access:
                active.add(cs.plan_id)
            continue
        # Recurrente (Flow/PayPal): se verifica en vivo contra la pasarela.
        if not cs.subscription_id:
            active.add(cs.plan_id)
            continue
        if _subscription_is_active(cs):
            active.add(cs.plan_id)
        # inactiva/cancelada → NO se agrega (sin acceso)
    return list(active)


class _MemberApiView(APIView):
    """
    Base de los endpoints del ÁREA DE MIEMBROS. Usan token propio (Bearer firmado,
    no usuario Django) y quedan EXENTOS del throttle de DRF: el latido de la sala
    Zoom (~cada 30s) y las recargas normales superarían el cupo ``anon`` (120/h)
    y bloquearían al miembro. El anti-abuso real vive en request-code/verify-code.
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = []


class MemberContentView(_MemberApiView):
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

        plan_ids = _member_active_plan_ids(email)
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


class MemberZoomSignatureView(_MemberApiView):
    """
    POST (Bearer) ``/public/member/content/<id>/zoom/`` → firma de vida corta para
    unirse a la sesión Zoom EMBEBIDA (``/sala/:id`` en el frontend).

    El acceso lo decide el servidor en el momento de entrar. Solo devuelve la firma
    si TODO se cumple:
      1. el miembro está autenticado (Bearer token);
      2. el contenido es una sesión Zoom publicada;
      3. está programado HOY en uno de los planes ACTIVOS del miembro (p. ej. Oro);
      4. estamos dentro de la franja horaria (``live_start``/``live_end``).

    El número de reunión y el passcode NUNCA se exponen como link reenviable:
    viajan solo en esta respuesta, al miembro habilitado y dentro de la franja.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request, content_id: int):
        email, sid = _member_identity(request)
        if not email:
            return Response({"detail": "No autenticado."}, status=401)

        try:
            item = ContentItem.objects.get(
                id=content_id, kind=ContentItem.Kind.ZOOM, is_published=True
            )
        except ContentItem.DoesNotExist:
            return Response({"detail": "Sesión no encontrada."}, status=404)

        # ¿El miembro tiene un plan activo donde este contenido está programado hoy?
        plan_ids = _member_active_plan_ids(email)
        today = timezone.localdate()
        allowed = (
            ContentSchedule.objects.filter(
                content_id=item.id, plan_id__in=plan_ids, starts_at__lte=today
            )
            .filter(Q(ends_at__isnull=True) | Q(ends_at__gte=today))
            .exists()
        )
        if not allowed:
            return Response({"detail": "No tienes acceso a esta sesión."}, status=403)

        if not item.zoom_meeting_number:
            return Response(
                {"detail": "La sesión aún no tiene una reunión Zoom configurada."},
                status=409,
            )

        if not item.is_live_open():
            return Response(
                {
                    "detail": "La sala todavía no está abierta.",
                    "opens_at": item.live_opens_at,
                    "closes_at": item.live_closes_at,
                },
                status=409,
            )

        # Candado de ENTRADA ÚNICA EN VIVO: si este correo ya está dentro de la
        # sesión desde otro login/dispositivo (marca de presencia vigente con un
        # ``sid`` distinto), se rechaza. Evita compartir la cuenta en simultáneo.
        live_key = _zoom_live_key(email, item.id)
        holder = cache.get(live_key)
        if holder and holder != sid:
            return Response(
                {"detail": "Ya estás conectado a esta sesión en otro dispositivo."},
                status=409,
            )

        # El SDK exige el número de reunión SOLO con dígitos (sin espacios/guiones
        # como vienen al copiar "858 0229 1303"); si no, falla con length > 12.
        meeting_number = re.sub(r"\D", "", item.zoom_meeting_number)

        try:
            sig = zoom.meeting_signature(meeting_number)
        except zoom.ZoomConfigError:
            return Response(
                {"detail": "Zoom no está configurado en el servidor."}, status=503
            )

        # Tomamos la presencia para este login; el frontend la renueva con latidos.
        cache.set(live_key, sid, getattr(settings, "ZOOM_LIVE_LOCK_TTL", 75))

        return Response(
            {
                "signature": sig["signature"],
                "sdkKey": sig["sdkKey"],
                "meetingNumber": meeting_number,
                "passcode": item.zoom_passcode.strip(),
                "userName": email,
                "userEmail": email,
                "topic": item.title,
            }
        )


class MemberZoomHeartbeatView(_MemberApiView):
    """
    POST (Bearer) ``/public/member/content/<id>/zoom/heartbeat/`` → mantiene viva
    la marca de presencia mientras el miembro está en la sala. Si otro
    login/dispositivo tomó la sesión (``sid`` distinto), responde 409 para que
    este cliente sea expulsado.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request, content_id: int):
        email, sid = _member_identity(request)
        if not email:
            return Response({"detail": "No autenticado."}, status=401)
        live_key = _zoom_live_key(email, content_id)
        holder = cache.get(live_key)
        if holder and holder != sid:
            return Response(
                {"detail": "Tu sesión se abrió en otro dispositivo."}, status=409
            )
        cache.set(live_key, sid, getattr(settings, "ZOOM_LIVE_LOCK_TTL", 75))
        return Response({"ok": True})


class MemberZoomLeaveView(_MemberApiView):
    """POST (Bearer) ``/public/member/content/<id>/zoom/leave/`` → libera la marca
    de presencia al salir de la sala (si es de este login), para que el miembro
    pueda reentrar de inmediato desde otro lado sin esperar a que expire el TTL."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request, content_id: int):
        email, sid = _member_identity(request)
        if not email:
            return Response({"detail": "No autenticado."}, status=401)
        live_key = _zoom_live_key(email, content_id)
        if cache.get(live_key) == sid:
            cache.delete(live_key)
        return Response({"ok": True})


class MemberAccountView(_MemberApiView):
    """GET (Bearer) → suscripciones del miembro con estado real (Flow o PayPal
    según ``provider``) + método de pago. Base de la sección 'Mi suscripción'."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        email = _member_email(request)
        if not email:
            return Response({"detail": "No autenticado."}, status=401)
        subs, seen = [], set()
        sessions = (
            CheckoutSession.objects.filter(
                email__iexact=email, status=CheckoutSession.Status.SUBSCRIBED
            )
            .select_related("plan")
            .order_by("-created")
        )
        for cs in sessions:
            # Clave de deduplicado: la suscripción de la pasarela, o la fila local
            # para las membresías por período (que no tienen subscription_id).
            key = cs.subscription_id or f"period:{cs.id}"
            if not cs.is_period_based and not cs.subscription_id:
                continue  # recurrente sin id de pasarela: nada que mostrar
            if key in seen:
                continue
            seen.add(key)
            info = {
                "subscription_id": cs.subscription_id or f"manual-{cs.id}",
                "provider": cs.provider,
                "is_manual": cs.is_period_based,
                "plan_name": cs.plan.name,
                "plan_slug": cs.plan.slug,
                "amount": cs.plan.amount,
                "currency": cs.plan.currency,
                "interval": cs.plan.interval,
                "status": None,
                "period_end": None,
                "next_invoice_date": None,
                "cancel_at_period_end": None,
                "card": None,
            }
            if cs.is_period_based:
                self._fill_period(cs, info)
            elif cs.provider == PaymentProvider.PAYPAL:
                self._fill_paypal(cs, info)
            else:
                self._fill_flow(cs, info)
            subs.append(info)
        return Response({"email": email, "subscriptions": subs})

    @staticmethod
    def _fill_period(cs, info: dict) -> None:
        """Membresía por período (manual/importado/pago único): el estado y el
        vencimiento salen de ``access_until`` local, sin consultar pasarela."""
        info["status"] = 1 if cs.has_period_access else 0
        info["period_end"] = cs.access_until.isoformat() if cs.access_until else None

    @staticmethod
    def _fill_flow(cs, info: dict) -> None:
        flow = get_flow_client()
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
            info["card"] = {"type": cust.get("creditCardType"), "last4": cust.get("last4CardDigits")}
        except FlowError:
            pass

    @staticmethod
    def _fill_paypal(cs, info: dict) -> None:
        info["amount"] = float(cs.plan.paypal_price_usd) if cs.plan.paypal_price_usd is not None else None
        info["currency"] = cs.plan.paypal_currency
        try:
            sub = get_paypal_client().get_subscription(cs.subscription_id)
            info["status"] = sub.get("status")
            billing = sub.get("billing_info", {}) or {}
            info["next_invoice_date"] = billing.get("next_billing_time")
        except PayPalError:
            pass


class MemberCancelView(_MemberApiView):
    """POST (Bearer) {subscription_id} → el miembro cancela su propia suscripción.
    En Flow se cancela al final del período; en PayPal el corte es inmediato (la
    API no expone 'al final del período'), pero PayPal no reembolsa lo ya pagado."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        email = _member_email(request)
        if not email:
            return Response({"detail": "No autenticado."}, status=401)
        sub_id = (request.data.get("subscription_id") or "").strip()
        cs = CheckoutSession.objects.filter(email__iexact=email, subscription_id=sub_id).first()
        if not (sub_id and cs):
            return Response({"detail": "Suscripción no encontrada."}, status=404)
        try:
            if cs.provider == PaymentProvider.PAYPAL:
                res = get_paypal_client().cancel_subscription(sub_id, reason="Cancelada por el miembro")
            else:
                res = get_flow_client().cancel_subscription(sub_id, at_period_end=True)
        except (FlowError, PayPalError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(res)


def _subscription_is_active(cs: CheckoutSession) -> bool:
    """
    Verifica EN VIVO si la suscripción de una ``CheckoutSession`` está activa,
    consultando la pasarela según ``cs.provider`` (Flow ``status == 1`` / PayPal
    ``status == ACTIVE``). Ante un fallo de la pasarela devuelve ``True``
    (fallback): no se bloquea a un miembro al día por una caída puntual.
    """
    if cs.provider == PaymentProvider.PAYPAL:
        try:
            sub = get_paypal_client().get_subscription(cs.subscription_id)
            return sub.get("status") == "ACTIVE"
        except PayPalError:
            return True
    try:
        sub = get_flow_client().get_subscription(cs.subscription_id)
        return str(sub.get("status")) == "1"
    except FlowError:
        return True


def _active_subscription_id(flow, plan_id: str, customer_id: str) -> str | None:
    """
    Devuelve el ``subscriptionId`` de una suscripción **activa** (``status == 1``)
    de este cliente a este plan, o ``None`` si no tiene.

    Sirve de guard anti-duplicado: Flow permite crear varias suscripciones del
    mismo cliente al mismo plan (cada una cobra por separado), así que antes de
    crear una nueva verificamos que no exista ya una activa. Ante un error de
    Flow devolvemos ``None`` (no bloqueamos un alta legítima por un fallo de red).
    """
    try:
        resp = flow.list_subscriptions(plan_id=plan_id, limit=100)
    except FlowError:
        return None
    for sub in resp.get("data", []) or []:
        if sub.get("customerId") == customer_id and str(sub.get("status")) == "1":
            return sub.get("subscriptionId")
    return None


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
            # Guard anti-duplicado: si ya tiene una suscripción activa a este plan,
            # no iniciamos otro checkout (evita el cobro doble y da feedback claro).
            if _active_subscription_id(flow, plan.flow_plan_id, customer_id):
                return Response(
                    {"detail": "Ya tienes una suscripción activa a esta membresía."},
                    status=status.HTTP_409_CONFLICT,
                )
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
                # Guard duro anti-cobro-doble: si el cliente YA tiene una
                # suscripción activa a este plan (p. ej. pasó por el checkout dos
                # veces), reutilizamos esa en vez de crear otra (que cobraría de
                # nuevo). Tratamos el resultado como éxito.
                existing = _active_subscription_id(
                    flow, session.plan.flow_plan_id, session.flow_customer_id
                )
                if existing:
                    session.subscription_id = existing
                else:
                    sub = flow.create_subscription(
                        plan_id=session.plan.flow_plan_id,
                        customer_id=session.flow_customer_id,
                    )
                    session.subscription_id = sub.get("subscriptionId", "")
                session.status = CheckoutSession.Status.SUBSCRIBED
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
