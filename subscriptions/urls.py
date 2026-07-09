"""URL routing for the subscriptions API."""

from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    AdminBroadcastView,
    AdminSubscriptionListView,
    CheckoutReturnView,
    CheckoutStartView,
    CompMembershipViewSet,
    ContentItemViewSet,
    ContentScheduleViewSet,
    EventCheckoutView,
    EventConfirmView,
    EventReturnView,
    EventViewSet,
    LeadViewSet,
    PaymentLinkConfirmView,
    PaymentLinkReturnView,
    PaymentLinkStartView,
    PaymentLinkViewSet,
    PublicEventListView,
    PublicLaunchScheduleView,
    FlowCustomersListView,
    FlowSubscriptionCancelView,
    FlowSubscriptionReactivateView,
    FlowSubscriptionsListView,
    MemberAccountView,
    MemberCancelView,
    MemberContentView,
    MemberEmailCheckView,
    MemberMediaUrlView,
    MemberPingView,
    MemberRequestCodeView,
    MemberVerifyCodeView,
    MemberZoomHeartbeatView,
    MemberZoomLeaveView,
    MemberZoomSignatureView,
    PaypalCheckoutReturnView,
    PaypalCheckoutStartView,
    PaypalSubscriptionRecordView,
    PaypalWebhookView,
    PlanViewSet,
    PublicLeadCreateView,
    PublicMembershipListView,
)

router = DefaultRouter()
router.register(r"plans", PlanViewSet, basename="plan")
router.register(r"events", EventViewSet, basename="event")
router.register(r"content-items", ContentItemViewSet, basename="content-item")
router.register(r"content-schedules", ContentScheduleViewSet, basename="content-schedule")
router.register(r"comp-memberships", CompMembershipViewSet, basename="comp-membership")
router.register(r"payment-links", PaymentLinkViewSet, basename="payment-link")
router.register(r"leads", LeadViewSet, basename="lead")

urlpatterns = [
    # Espejos de solo lectura desde Flow (admin)
    path("customers/", FlowCustomersListView.as_view(), name="flow-customers"),
    path("subscriptions/", FlowSubscriptionsListView.as_view(), name="flow-subscriptions"),
    path("subscriptions/all/", AdminSubscriptionListView.as_view(), name="subscriptions-all"),
    path("broadcast/", AdminBroadcastView.as_view(), name="admin-broadcast"),
    path("subscriptions/cancel/", FlowSubscriptionCancelView.as_view(), name="flow-subscription-cancel"),
    path("subscriptions/reactivate/", FlowSubscriptionReactivateView.as_view(), name="flow-subscription-reactivate"),
    path("public/memberships/", PublicMembershipListView.as_view(), name="public-memberships"),
    path("public/launch-schedule/", PublicLaunchScheduleView.as_view(), name="public-launch-schedule"),
    path("public/events/", PublicEventListView.as_view(), name="public-events"),
    path("public/events/checkout/", EventCheckoutView.as_view(), name="public-event-checkout"),
    path("public/events/return/", EventReturnView.as_view(), name="public-event-return"),
    path("public/events/confirm/", EventConfirmView.as_view(), name="public-event-confirm"),
    # Link de pago de Flow (autoservicio del suscriptor + generado desde el panel)
    path("public/checkout/payment-link/start/", PaymentLinkStartView.as_view(), name="payment-link-start"),
    path("public/payment-link/confirm/", PaymentLinkConfirmView.as_view(), name="payment-link-confirm"),
    path("public/payment-link/return/", PaymentLinkReturnView.as_view(), name="payment-link-return"),
    path("public/leads/", PublicLeadCreateView.as_view(), name="public-leads"),
    path("public/checkout/start/", CheckoutStartView.as_view(), name="checkout-start"),
    path("public/checkout/return/", CheckoutReturnView.as_view(), name="checkout-return"),
    # Checkout PayPal (alternativa internacional en USD)
    path("public/paypal/checkout/start/", PaypalCheckoutStartView.as_view(), name="paypal-checkout-start"),
    path("public/paypal/checkout/return/", PaypalCheckoutReturnView.as_view(), name="paypal-checkout-return"),
    path("public/paypal/subscription/record/", PaypalSubscriptionRecordView.as_view(), name="paypal-subscription-record"),
    path("public/paypal/webhook/", PaypalWebhookView.as_view(), name="paypal-webhook"),
    # Área de miembros (login sin contraseña + contenido)
    path("public/member/request-code/", MemberRequestCodeView.as_view(), name="member-request-code"),
    path("public/member/verify-code/", MemberVerifyCodeView.as_view(), name="member-verify-code"),
    path("public/member/check-email/", MemberEmailCheckView.as_view(), name="member-check-email"),
    path("public/member/ping/", MemberPingView.as_view(), name="member-ping"),
    path("public/member/content/", MemberContentView.as_view(), name="member-content"),
    path("public/member/content/<int:content_id>/media/", MemberMediaUrlView.as_view(), name="member-media-url"),
    path("public/member/content/<int:content_id>/zoom/", MemberZoomSignatureView.as_view(), name="member-zoom-signature"),
    path("public/member/content/<int:content_id>/zoom/heartbeat/", MemberZoomHeartbeatView.as_view(), name="member-zoom-heartbeat"),
    path("public/member/content/<int:content_id>/zoom/leave/", MemberZoomLeaveView.as_view(), name="member-zoom-leave"),
    path("public/member/account/", MemberAccountView.as_view(), name="member-account"),
    path("public/member/subscription/cancel/", MemberCancelView.as_view(), name="member-cancel"),
    *router.urls,
]
