"""URL routing for the subscriptions API."""

from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    CheckoutReturnView,
    CheckoutStartView,
    ContentItemViewSet,
    ContentScheduleViewSet,
    EventCheckoutView,
    EventConfirmView,
    EventReturnView,
    EventViewSet,
    LeadViewSet,
    PublicEventListView,
    FlowCustomersListView,
    FlowSubscriptionCancelView,
    FlowSubscriptionReactivateView,
    FlowSubscriptionsListView,
    MemberAccountView,
    MemberCancelView,
    MemberContentView,
    MemberRequestCodeView,
    MemberVerifyCodeView,
    PlanViewSet,
    PublicLeadCreateView,
    PublicMembershipListView,
)

router = DefaultRouter()
router.register(r"plans", PlanViewSet, basename="plan")
router.register(r"events", EventViewSet, basename="event")
router.register(r"content-items", ContentItemViewSet, basename="content-item")
router.register(r"content-schedules", ContentScheduleViewSet, basename="content-schedule")
router.register(r"leads", LeadViewSet, basename="lead")

urlpatterns = [
    # Espejos de solo lectura desde Flow (admin)
    path("customers/", FlowCustomersListView.as_view(), name="flow-customers"),
    path("subscriptions/", FlowSubscriptionsListView.as_view(), name="flow-subscriptions"),
    path("subscriptions/cancel/", FlowSubscriptionCancelView.as_view(), name="flow-subscription-cancel"),
    path("subscriptions/reactivate/", FlowSubscriptionReactivateView.as_view(), name="flow-subscription-reactivate"),
    path("public/memberships/", PublicMembershipListView.as_view(), name="public-memberships"),
    path("public/events/", PublicEventListView.as_view(), name="public-events"),
    path("public/events/checkout/", EventCheckoutView.as_view(), name="public-event-checkout"),
    path("public/events/return/", EventReturnView.as_view(), name="public-event-return"),
    path("public/events/confirm/", EventConfirmView.as_view(), name="public-event-confirm"),
    path("public/leads/", PublicLeadCreateView.as_view(), name="public-leads"),
    path("public/checkout/start/", CheckoutStartView.as_view(), name="checkout-start"),
    path("public/checkout/return/", CheckoutReturnView.as_view(), name="checkout-return"),
    # Área de miembros (login sin contraseña + contenido)
    path("public/member/request-code/", MemberRequestCodeView.as_view(), name="member-request-code"),
    path("public/member/verify-code/", MemberVerifyCodeView.as_view(), name="member-verify-code"),
    path("public/member/content/", MemberContentView.as_view(), name="member-content"),
    path("public/member/account/", MemberAccountView.as_view(), name="member-account"),
    path("public/member/subscription/cancel/", MemberCancelView.as_view(), name="member-cancel"),
    *router.urls,
]
