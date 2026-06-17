from django.conf import settings
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import UiSettings
from ..shell.ui_preferences import merge_ui_preferences, validate_ui_preferences_patch


class UiSettingsAPIView(APIView):
    """
    Ajustes de UI para el front (tema, título, logo). Contrato alineado con
    ``UiSettingsResponse`` en Angular. Lee desde el modelo singleton ``UiSettings``.
    """

    permission_classes = [AllowAny]
    authentication_classes = []  # tema usable en pantalla de login sin JWT

    def get(self, request):
        ui = UiSettings.load()
        return Response(
            {
                "theme_key": ui.theme_key or None,
                "app_title": ui.app_title or None,
                "logo_url": ui.logo_url or None,
                "theme_overrides": ui.theme_overrides or {},
                "social": {
                    "google": bool(settings.SOCIAL_AUTH_GOOGLE_ENABLED),
                    "apple": bool(settings.SOCIAL_AUTH_APPLE_ENABLED),
                    "microsoft": bool(settings.SOCIAL_AUTH_MICROSOFT_ENABLED),
                    "google_client_id": settings.GOOGLE_OAUTH_CLIENT_ID or None,
                    "apple_client_id": settings.APPLE_CLIENT_ID or None,
                    "microsoft_client_id": settings.MICROSOFT_OAUTH_CLIENT_ID or None,
                    # MSAL (browser) necesita la authority con el tenant.
                    "microsoft_tenant_id": settings.MICROSOFT_OAUTH_TENANT_ID or "common",
                },
            }
        )


class MeUiPreferencesAPIView(APIView):
    """
    Preferencias de shell del usuario autenticado (tema, ancho de página,
    idioma UI, panel de apariencia colapsable). Persistidas en
    ``User.ui_preferences`` (JSONField directo sobre el custom user; antes
    vivía en un ``Profile`` separado, fusionado en el refactor de
    estabilización del template).

    ``GET`` → objeto guardado (puede estar vacío).
    ``PATCH`` → fusión superficial con validación allow-list de claves.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        prefs = request.user.ui_preferences
        return Response(prefs if isinstance(prefs, dict) else {})

    def patch(self, request):
        user = request.user
        body = request.data if isinstance(request.data, dict) else {}
        validated = validate_ui_preferences_patch(body)
        merged = merge_ui_preferences(user.ui_preferences, validated)
        user.ui_preferences = merged
        user.save(update_fields=["ui_preferences", "modified"])
        return Response(merged)


@extend_schema(
    summary="KPIs del dashboard",
    description="Métricas agregadas para `app-stat-card` en el front. Extienda `api/shell/dashboard_stats.py`.",
    tags=["stats"],
)
class DashboardStatsAPIView(APIView):
    """
    ``GET /api/v1/stats/`` — JSON con ``items`` (tarjetas) y ``generated_at`` (ISO 8601).
    Requiere JWT. La fuente de datos vive en `api.shell.dashboard_stats.get_dashboard_stats`.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.core.cache import cache

        from ..shell.dashboard_stats import get_dashboard_stats

        # KPIs agregados: caros de recomputar y casi idénticos por ventana.
        # TTL corto (60s) sin invalidación explícita — la frescura de ~1 min es
        # aceptable para métricas de dashboard.
        cached = cache.get("fvx:dashboard_stats")
        if cached is not None:
            return Response(cached)

        data = {
            "items": get_dashboard_stats(),
            "generated_at": timezone.now().isoformat(),
        }
        cache.set("fvx:dashboard_stats", data, 60)
        return Response(data)
