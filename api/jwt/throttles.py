"""Throttles para los endpoints de obtención y refresh de JWT.

Protegen contra credential stuffing y brute force sobre ``/api/auth/token/``
y ``/api/auth/token/refresh/``. Dos vectores:

- **Por IP** (``LoginIPRateThrottle``): frena botnets simples que hammerizan
  desde una sola dirección. Razonable: 10 req/min — sobra para un usuario
  normal (1–2 intentos) y bloquea scripts automatizados.
- **Por username** (``LoginUsernameRateThrottle``): frena ataques dirigidos
  contra una cuenta específica aunque el atacante rote IPs. 5 req/min por
  username. El cache key es el username; si está vacío en el body, cae al
  IP-based throttle para no abrir bypass.

El rate efectivo es la combinación AND de ambos: si tu IP o tu username
están throttled, se devuelve 429. La respuesta incluye el header
``Retry-After`` que el cliente debe respetar.
"""

import hashlib

from rest_framework.throttling import SimpleRateThrottle


class LoginIPRateThrottle(SimpleRateThrottle):
    """Throttle por IP para POST a ``/api/auth/token/``."""

    scope = "login_ip"

    def get_cache_key(self, request, view):
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }


class LoginUsernameRateThrottle(SimpleRateThrottle):
    """Throttle por username para POST a ``/api/auth/token/``.

    Si el body no trae username (request malformado, intento de bypass)
    no aplicamos este throttle — el IP-based ya cubre ese caso.
    """

    scope = "login_user"

    def get_cache_key(self, request, view):
        username = (request.data.get("username") or "").strip().lower()
        if not username:
            return None  # sin username → no aplica este throttle
        # Hash para no llenar el cache con keys gigantes ni leakear usernames.
        digest = hashlib.sha256(username.encode("utf-8")).hexdigest()[:32]
        return self.cache_format % {
            "scope": self.scope,
            "ident": digest,
        }


class TokenRefreshRateThrottle(SimpleRateThrottle):
    """Throttle por IP para POST a ``/api/auth/token/refresh/``.

    Menos estricto que el de login (el refresh es automático y frecuente)
    pero suficiente para frenar abusos.
    """

    scope = "token_refresh"

    def get_cache_key(self, request, view):
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }
