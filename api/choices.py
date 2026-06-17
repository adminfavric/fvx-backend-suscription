"""Centralized choice tuples (codes in English; labels translated via gettext)."""

from django.utils.translation import gettext_lazy as _

ROLE_ADMIN = "ADMIN"
ROLE_EDITOR = "EDITOR"
ROLE_VIEWER = "VIEWER"

# User.role
ROLE_CHOICES = [
    (ROLE_ADMIN, _("Admin")),
    (ROLE_EDITOR, _("Editor")),
    (ROLE_VIEWER, _("Viewer")),
]

# Higher value = more privilege.
ROLE_PRECEDENCE = {
    ROLE_VIEWER: 0,
    ROLE_EDITOR: 1,
    ROLE_ADMIN: 2,
}
