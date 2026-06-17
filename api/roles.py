"""Effective role resolution.

After the custom user refactor, the user's role is simply ``user.role``
(a CharField on the User model itself, no Profile indirection). Helpers
here keep their names for callers (serializers, menu visibility) so the
external contract is unchanged.
"""

from .choices import ROLE_PRECEDENCE, ROLE_VIEWER


def get_effective_role_for_user(user) -> str:
    """Returns the user's effective role code (e.g. ``"ADMIN"``)."""
    return getattr(user, "role", ROLE_VIEWER) or ROLE_VIEWER


def user_menu_role_score(user) -> int:
    """Numeric privilege for menu visibility. Staff is above every role."""
    if getattr(user, "is_staff", False):
        return max(ROLE_PRECEDENCE.values()) + 1
    role = get_effective_role_for_user(user)
    return ROLE_PRECEDENCE.get(role, 0)


def user_can_see_menu_item(user, allowed_roles: list | None) -> bool:
    """
    ``allowed_roles`` is a list of role codes (e.g. ``["VIEWER", "ADMIN"]``).

    Rules:
      · **Staff** sees ALL items (even those without roles assigned).
      · **Non-staff + no allowed_roles defined** (empty list / ``None``) →
        does NOT see. This forces admins to declare explicitly who can access
        each item; previously empty meant "everyone" which let items slip
        into production without conscious gating.
      · **Non-staff + roles defined** → only if ``user.role`` is in the list.
    """
    if getattr(user, "is_staff", False):
        return True
    roles = allowed_roles or []
    if not roles:
        return False
    return get_effective_role_for_user(user) in roles
