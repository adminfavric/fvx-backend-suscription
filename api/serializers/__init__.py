"""
API serializers package.

Template serializers live in modules here. Implementers may add modules and
re-export from this package to keep a stable `from api.serializers import …`.
"""

from .api_key import ApiKeyCreateSerializer, ApiKeySerializer
from .group import GroupSerializer
from .notification import NotificationSerializer
from .upload import UploadRequestSerializer, UploadResponseSerializer
from .user import (
    ChangePasswordSerializer,
    MeSerializer,
    role_label_for_code,
    UserCreateSerializer,
    UserDetailSerializer,
    UserSerializer,
)

__all__ = [
    "ApiKeyCreateSerializer",
    "ApiKeySerializer",
    "ChangePasswordSerializer",
    "GroupSerializer",
    "MeSerializer",
    "NotificationSerializer",
    "UploadRequestSerializer",
    "UploadResponseSerializer",
    "role_label_for_code",
    "UserCreateSerializer",
    "UserDetailSerializer",
    "UserSerializer",
]
