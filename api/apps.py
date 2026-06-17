from django.apps import AppConfig


class ApiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "api"
    verbose_name = "API"

    def ready(self):
        import api.openapi  # noqa: F401 — spectacular OpenApiAuthenticationExtension
        import api.signals  # noqa: F401
        import api.auditing  # noqa: F401 — auditlog.register para modelos críticos
