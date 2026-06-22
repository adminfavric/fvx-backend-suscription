"""
PayPal REST client (suscripciones / billing).

Wrapper fino sobre la API REST de PayPal (https://developer.paypal.com/docs/api/)
enfocado en suscripciones recurrentes: productos de catálogo, billing plans y
subscriptions. Autenticación OAuth2 ``client_credentials`` (Basic auth con
client id + secret) → ``access_token`` Bearer que se cachea hasta poco antes de
expirar.

Es el equivalente internacional de ``flow.py``: Flow cobra en CLP (tarjetas
chilenas), PayPal cobra en USD (clientes internacionales). Config desde settings
(``.env``):

    PAYPAL_CLIENT_ID, PAYPAL_SECRET, PAYPAL_SANDBOX (bool), PAYPAL_API_BASE
    (opcional), PAYPAL_WEBHOOK_ID.

Uso::

    from subscriptions.services import get_paypal_client
    pp = get_paypal_client()
    sub = pp.create_subscription(plan_id="P-...", subscriber={...}, ...)
"""

from __future__ import annotations

import time
from typing import Any

import requests
from django.conf import settings

PROD_BASE = "https://api-m.paypal.com"
SANDBOX_BASE = "https://api-m.sandbox.paypal.com"

DEFAULT_TIMEOUT = 20  # seconds
# Margen de seguridad antes de la expiración real del token (segundos).
_TOKEN_SKEW = 60


class PayPalError(Exception):
    """Se lanza cuando PayPal devuelve un error o el cliente está mal configurado."""

    def __init__(self, message: str, *, status: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.payload = payload


class PayPalClient:
    def __init__(
        self,
        client_id: str,
        secret: str,
        *,
        base_url: str = PROD_BASE,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        if not client_id or not secret:
            raise PayPalError(
                "PayPal credentials missing: set PAYPAL_CLIENT_ID and PAYPAL_SECRET in .env"
            )
        self.client_id = client_id
        self.secret = secret
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._token: str | None = None
        self._token_exp: float = 0.0

    # ── auth ─────────────────────────────────────────────────────────────────
    def _access_token(self) -> str:
        """OAuth2 client-credentials token, cacheado hasta poco antes de expirar."""
        if self._token and time.monotonic() < self._token_exp:
            return self._token
        url = f"{self.base_url}/v1/oauth2/token"
        try:
            resp = requests.post(
                url,
                auth=(self.client_id, self.secret),
                data={"grant_type": "client_credentials"},
                headers={"Accept": "application/json"},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise PayPalError(f"PayPal auth request failed: {exc}") from exc
        if resp.status_code >= 400:
            raise PayPalError(
                "PayPal authentication failed (check PAYPAL_CLIENT_ID / PAYPAL_SECRET)",
                status=resp.status_code,
                payload=_safe_json(resp),
            )
        data = resp.json()
        self._token = data["access_token"]
        self._token_exp = time.monotonic() + max(int(data.get("expires_in", 3600)) - _TOKEN_SKEW, 0)
        return self._token

    # ── transport ────────────────────────────────────────────────────────────
    def _request(
        self, method: str, path: str, *, json: dict | None = None, params: dict | None = None
    ) -> dict[str, Any]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        headers = {
            "Authorization": f"Bearer {self._access_token()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            resp = requests.request(
                method, url, json=json, params=params, headers=headers, timeout=self.timeout
            )
        except requests.RequestException as exc:
            raise PayPalError(f"PayPal request failed: {exc}") from exc

        data = _safe_json(resp)
        if resp.status_code >= 400:
            message = None
            if isinstance(data, dict):
                message = data.get("message") or data.get("error_description")
            raise PayPalError(
                message or f"PayPal returned HTTP {resp.status_code}",
                status=resp.status_code,
                payload=data,
            )
        return data if isinstance(data, dict) else {"raw": data}

    # ── products (catálogo) ───────────────────────────────────────────────────
    def create_product(self, **body: Any) -> dict[str, Any]:
        """POST /v1/catalogs/products. Requeridos: name, type (SERVICE)."""
        return self._request("POST", "v1/catalogs/products", json=body)

    # ── billing plans ─────────────────────────────────────────────────────────
    def create_plan(self, **body: Any) -> dict[str, Any]:
        """POST /v1/billing/plans. Requeridos: product_id, name, billing_cycles,
        payment_preferences. Devuelve el plan con su ``id`` (P-…)."""
        return self._request("POST", "v1/billing/plans", json=body)

    def get_plan(self, plan_id: str) -> dict[str, Any]:
        return self._request("GET", f"v1/billing/plans/{plan_id}")

    def update_plan_pricing(self, plan_id: str, *, pricing_schemes: list[dict]) -> dict[str, Any]:
        """POST /v1/billing/plans/{id}/update-pricing-schemes (204, sin body)."""
        return self._request(
            "POST",
            f"v1/billing/plans/{plan_id}/update-pricing-schemes",
            json={"pricing_schemes": pricing_schemes},
        )

    def activate_plan(self, plan_id: str) -> dict[str, Any]:
        return self._request("POST", f"v1/billing/plans/{plan_id}/activate")

    def deactivate_plan(self, plan_id: str) -> dict[str, Any]:
        return self._request("POST", f"v1/billing/plans/{plan_id}/deactivate")

    # ── subscriptions ─────────────────────────────────────────────────────────
    def create_subscription(self, **body: Any) -> dict[str, Any]:
        """POST /v1/billing/subscriptions. Requeridos: plan_id. Devuelve la
        suscripción con ``id`` (I-…) y los ``links`` (rel=approve = URL a la que
        redirigir al cliente para aprobar el pago)."""
        return self._request("POST", "v1/billing/subscriptions", json=body)

    def get_subscription(self, subscription_id: str) -> dict[str, Any]:
        """GET /v1/billing/subscriptions/{id}. status: APPROVAL_PENDING, APPROVED,
        ACTIVE, SUSPENDED, CANCELLED, EXPIRED."""
        return self._request("GET", f"v1/billing/subscriptions/{subscription_id}")

    def cancel_subscription(self, subscription_id: str, *, reason: str = "Cancelled by user") -> dict[str, Any]:
        """POST /v1/billing/subscriptions/{id}/cancel (204, sin body)."""
        return self._request(
            "POST",
            f"v1/billing/subscriptions/{subscription_id}/cancel",
            json={"reason": reason},
        )

    # ── webhooks ──────────────────────────────────────────────────────────────
    def verify_webhook(self, *, headers: dict, body: str, webhook_id: str) -> bool:
        """POST /v1/notifications/verify-webhook-signature → verification_status."""
        payload = {
            "auth_algo": headers.get("PAYPAL-AUTH-ALGO"),
            "cert_url": headers.get("PAYPAL-CERT-URL"),
            "transmission_id": headers.get("PAYPAL-TRANSMISSION-ID"),
            "transmission_sig": headers.get("PAYPAL-TRANSMISSION-SIG"),
            "transmission_time": headers.get("PAYPAL-TRANSMISSION-TIME"),
            "webhook_id": webhook_id,
            "webhook_event": _json_loads(body),
        }
        res = self._request("POST", "v1/notifications/verify-webhook-signature", json=payload)
        return res.get("verification_status") == "SUCCESS"

    @staticmethod
    def approval_url(subscription: dict) -> str | None:
        """Extrae el link rel=approve de la respuesta de create_subscription."""
        for link in subscription.get("links", []) or []:
            if link.get("rel") == "approve":
                return link.get("href")
        return None


def _safe_json(resp: requests.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return {"raw": resp.text}


def _json_loads(body: str) -> Any:
    import json

    try:
        return json.loads(body)
    except (ValueError, TypeError):
        return {}


def get_paypal_client() -> PayPalClient:
    """Construye un cliente desde Django settings / ``.env``."""
    base = getattr(settings, "PAYPAL_API_BASE", "") or (
        SANDBOX_BASE if getattr(settings, "PAYPAL_SANDBOX", True) else PROD_BASE
    )
    return PayPalClient(
        client_id=getattr(settings, "PAYPAL_CLIENT_ID", ""),
        secret=getattr(settings, "PAYPAL_SECRET", ""),
        base_url=base,
    )
