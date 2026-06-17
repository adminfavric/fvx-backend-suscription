from rest_framework.throttling import SimpleRateThrottle


class SocialAuthThrottle(SimpleRateThrottle):
    """Límite de intentos en ``/api/auth/social/*`` (por IP)."""

    scope = "social"

    def get_cache_key(self, request, view):
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }
