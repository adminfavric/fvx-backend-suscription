"""
Flow.cl REST client.

Thin wrapper over the Flow API (https://developers.flow.cl/en/api) focused on
subscription plans. Authentication is ``apiKey`` + an ``s`` signature that is the
HMAC-SHA256 of the request parameters: keys sorted alphabetically, concatenated
as ``key + value`` with no separators, signed with the secret key.

Config comes from settings (read from ``.env``):
    FLOW_API_KEY, FLOW_SECRET_KEY, FLOW_SANDBOX (bool), FLOW_API_BASE (optional).

Usage::

    from subscriptions.services import get_flow_client
    flow = get_flow_client()
    flow.create_plan(planId="escuela-de-alkymistas", name="...", amount=30000, interval=3)
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

import requests
from django.conf import settings

PROD_BASE = "https://www.flow.cl/api"
SANDBOX_BASE = "https://sandbox.flow.cl/api"

DEFAULT_TIMEOUT = 20  # seconds


class FlowError(Exception):
    """Raised when Flow returns a non-2xx response or the client is misconfigured."""

    def __init__(self, message: str, *, status: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.payload = payload


class FlowClient:
    def __init__(self, api_key: str, secret_key: str, *, base_url: str = PROD_BASE, timeout: int = DEFAULT_TIMEOUT):
        if not api_key or not secret_key:
            raise FlowError("Flow credentials missing: set FLOW_API_KEY and FLOW_SECRET_KEY in .env")
        self.api_key = api_key
        self.secret_key = secret_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # ── signing ────────────────────────────────────────────────────────────
    def _sign(self, params: dict[str, Any]) -> str:
        """HMAC-SHA256 over alphabetically-sorted ``key+value`` concatenation."""
        to_sign = "".join(f"{k}{params[k]}" for k in sorted(params))
        return hmac.new(self.secret_key.encode(), to_sign.encode(), hashlib.sha256).hexdigest()

    def _prepare(self, params: dict[str, Any]) -> dict[str, str]:
        """Drop ``None``s, stringify, inject apiKey, append the signature ``s``."""
        clean = {"apiKey": self.api_key}
        for k, v in params.items():
            if v is None:
                continue
            clean[k] = str(v).lower() if isinstance(v, bool) else str(v)
        clean["s"] = self._sign(clean)
        return clean

    # ── transport ──────────────────────────────────────────────────────────
    def _request(self, method: str, path: str, params: dict[str, Any]) -> dict[str, Any]:
        prepared = self._prepare(params)
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            if method == "GET":
                resp = requests.get(url, params=prepared, timeout=self.timeout)
            else:
                resp = requests.post(url, data=prepared, timeout=self.timeout)
        except requests.RequestException as exc:
            raise FlowError(f"Flow request failed: {exc}") from exc

        try:
            data = resp.json()
        except ValueError:
            data = {"raw": resp.text}

        if resp.status_code >= 400:
            message = data.get("message") if isinstance(data, dict) else None
            raise FlowError(
                message or f"Flow returned HTTP {resp.status_code}",
                status=resp.status_code,
                payload=data,
            )
        return data

    def _get(self, path: str, **params: Any) -> dict[str, Any]:
        return self._request("GET", path, params)

    def _post(self, path: str, **params: Any) -> dict[str, Any]:
        return self._request("POST", path, params)

    # ── plans ────────────────────────────────────────────────────────────────
    def create_plan(self, **params: Any) -> dict[str, Any]:
        """POST /plans/create. Required: planId, name, amount, interval."""
        return self._post("plans/create", **params)

    def get_plan(self, plan_id: str) -> dict[str, Any]:
        return self._get("plans/get", planId=plan_id)

    def list_plans(self, *, start: int = 0, limit: int = 100, filter: str | None = None, status: int | None = None) -> dict[str, Any]:
        return self._get("plans/list", start=start, limit=limit, filter=filter, status=status)

    def edit_plan(self, plan_id: str, **params: Any) -> dict[str, Any]:
        """POST /plans/edit. If the plan has subscribers, only trial_period_days is editable."""
        # ``params`` puede ya traer ``planId`` (lo arma ``_flow_params``); forzamos
        # un único valor para no chocar con el ``planId`` posicional (evita
        # "got multiple values for keyword argument 'planId'").
        params["planId"] = plan_id
        return self._post("plans/edit", **params)

    def delete_plan(self, plan_id: str) -> dict[str, Any]:
        return self._post("plans/delete", planId=plan_id)

    # ── payments (pago único / one-time) ─────────────────────────────────────
    def create_payment(self, **params: Any) -> dict[str, Any]:
        """POST /payment/create. Requeridos: commerceOrder, subject, amount, email,
        urlConfirmation, urlReturn. Devuelve {token, url, flowOrder}; se redirige
        al cliente a ``url`` + ``?token=`` + ``token``."""
        return self._post("payment/create", **params)

    def get_payment_status(self, token: str) -> dict[str, Any]:
        """GET /payment/getStatus. status: 1 pendiente · 2 pagada · 3 rechazada · 4 anulada."""
        return self._get("payment/getStatus", token=token)

    # ── customers ────────────────────────────────────────────────────────────
    def create_customer(self, *, name: str, email: str, external_id: str) -> dict[str, Any]:
        """POST /customer/create. Returns the customer incl. customerId."""
        return self._post("customer/create", name=name, email=email, externalId=external_id)

    def list_customers(
        self, *, start: int = 0, limit: int = 100, filter: str | None = None, status: int | None = None
    ) -> dict[str, Any]:
        """GET /customer/list. Respuesta ``{total, hasMore, data:[Customer]}``."""
        return self._get("customer/list", start=start, limit=limit, filter=filter, status=status)

    def get_customer(self, customer_id: str) -> dict[str, Any]:
        """GET /customer/get. Incluye creditCardType / last4CardDigits."""
        return self._get("customer/get", customerId=customer_id)

    def register_customer_card(self, *, customer_id: str, url_return: str) -> dict[str, Any]:
        """POST /customer/register. Returns {url, token} to send the customer to
        register a credit card. Redirect URL = ``url`` + ``?token=`` + ``token``."""
        return self._post("customer/register", customerId=customer_id, url_return=url_return)

    def get_register_status(self, token: str) -> dict[str, Any]:
        """GET /customer/getRegisterStatus. status 1 = card registered OK."""
        return self._get("customer/getRegisterStatus", token=token)

    # ── subscriptions ────────────────────────────────────────────────────────
    def create_subscription(self, *, plan_id: str, customer_id: str, **opts: Any) -> dict[str, Any]:
        """POST /subscription/create. The customer must have a registered card."""
        return self._post("subscription/create", planId=plan_id, customerId=customer_id, **opts)

    def list_subscriptions(
        self, *, plan_id: str, start: int = 0, limit: int = 100, filter: str | None = None, status: int | None = None
    ) -> dict[str, Any]:
        """GET /subscription/list. Flow EXIGE ``planId`` (las suscripciones se
        listan por plan). Respuesta ``{total, hasMore, data:[Subscription]}``."""
        return self._get(
            "subscription/list", planId=plan_id, start=start, limit=limit, filter=filter, status=status
        )

    def get_subscription(self, subscription_id: str) -> dict[str, Any]:
        """GET /subscription/get."""
        return self._get("subscription/get", subscriptionId=subscription_id)

    def cancel_subscription(self, subscription_id: str, *, at_period_end: bool = True) -> dict[str, Any]:
        """POST /subscription/cancel. ``at_period_end`` posterga el corte al fin del período."""
        return self._post(
            "subscription/cancel", subscriptionId=subscription_id, at_period_end=at_period_end
        )


def get_flow_client() -> FlowClient:
    """Build a client from Django settings / .env."""
    base = getattr(settings, "FLOW_API_BASE", "") or (
        SANDBOX_BASE if getattr(settings, "FLOW_SANDBOX", True) else PROD_BASE
    )
    return FlowClient(
        api_key=getattr(settings, "FLOW_API_KEY", ""),
        secret_key=getattr(settings, "FLOW_SECRET_KEY", ""),
        base_url=base,
    )
