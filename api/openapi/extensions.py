"""drf-spectacular extensions (imported from ``api.apps`` ``ready``)."""

from drf_spectacular.extensions import OpenApiAuthenticationExtension


class ApiKeyAuthExtension(OpenApiAuthenticationExtension):
    target_class = "api.authentication.ApiKeyAuthentication"
    name = "ApiKeyAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "apiKey",
            "in": "header",
            "name": "X-Api-Key",
            "description": (
                "Clave en formato `fvx.<prefijo>.<secreto>`. "
                "También aceptada como `Authorization: Api-Key <clave>`."
            ),
        }
