"""Registro de extensiones drf-spectacular (cargado desde ``api.apps`` ``ready``)."""

from .extensions import ApiKeyAuthExtension  # noqa: F401

__all__ = ["ApiKeyAuthExtension"]
