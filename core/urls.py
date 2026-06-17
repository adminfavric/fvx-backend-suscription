"""URL configuration for FVX template backend."""

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework_simplejwt.views import TokenVerifyView

from api.jwt import FvxTokenObtainPairView, FvxTokenRefreshView, LogoutView
from api.social.views import (
    AppleSocialAuthView,
    GoogleSocialAuthView,
    MicrosoftSocialAuthView,
)
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)

urlpatterns = [
    # Admin
    path("admin/", admin.site.urls),
    # API Documentation
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    # JWT Authentication
    path("api/auth/token/", FvxTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", FvxTokenRefreshView.as_view(), name="token_refresh"),
    path("api/auth/token/verify/", TokenVerifyView.as_view(), name="token_verify"),
    path("api/auth/logout/", LogoutView.as_view(), name="auth_logout"),
    path("api/auth/social/google/", GoogleSocialAuthView.as_view(), name="social_google"),
    path("api/auth/social/apple/", AppleSocialAuthView.as_view(), name="social_apple"),
    path("api/auth/social/microsoft/", MicrosoftSocialAuthView.as_view(), name="social_microsoft"),
    # API v1
    path("api/v1/", include("api.urls")),
    # Notifications (webhook SNS de eventos SES)
    path("api/v1/", include("notifications.urls")),
    # Subscriptions (planes / suscripciones Flow)
    path("api/v1/", include("subscriptions.urls")),
    # Internationalization
    path("i18n/", include("django.conf.urls.i18n")),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

# Admin site customization
admin.site.site_header = "FVX Suscription Admin API"
admin.site.site_title = "FVX Suscription Admin"
admin.site.index_title = "Administration"
