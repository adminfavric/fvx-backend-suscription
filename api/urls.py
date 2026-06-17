"""URL routing for the generic template API."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    ApiKeyViewSet,
    DashboardStatsAPIView,
    GroupViewSet,
    MenuViewSet,
    MeUiPreferencesAPIView,
    NotificationViewSet,
    UiSettingsAPIView,
    UploadDeleteView,
    UploadView,
    UserViewSet,
)

router = DefaultRouter()
router.register(r"menus", MenuViewSet, basename="menu")
router.register(r"groups", GroupViewSet, basename="group")
router.register(r"notifications", NotificationViewSet, basename="notification")
router.register(r"users", UserViewSet, basename="user")
router.register(r"api-keys", ApiKeyViewSet, basename="api-key")

urlpatterns = [
    path("settings/ui/", UiSettingsAPIView.as_view(), name="settings-ui"),
    path("me/ui-preferences/", MeUiPreferencesAPIView.as_view(), name="me-ui-preferences"),
    path("stats/", DashboardStatsAPIView.as_view(), name="dashboard-stats"),
    path("uploads/", UploadView.as_view(), name="upload"),
    path("uploads/object/", UploadDeleteView.as_view(), name="upload-delete"),
    path("", include(router.urls)),
]
