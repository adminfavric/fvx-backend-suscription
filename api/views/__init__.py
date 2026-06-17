"""
API views package.

Add new modules for custom ViewSets or APIViews and re-export from here so
`from api.views import …` and `api.urls` stay stable.
"""

from .api_key import ApiKeyViewSet
from .menu import MenuViewSet
from .notification import NotificationViewSet
from .ui import DashboardStatsAPIView, MeUiPreferencesAPIView, UiSettingsAPIView
from .upload import UploadDeleteView, UploadView
from .user import GroupViewSet, UserViewSet

__all__ = [
    "ApiKeyViewSet",
    "DashboardStatsAPIView",
    "GroupViewSet",
    "MeUiPreferencesAPIView",
    "MenuViewSet",
    "NotificationViewSet",
    "UiSettingsAPIView",
    "UploadDeleteView",
    "UploadView",
    "UserViewSet",
]
