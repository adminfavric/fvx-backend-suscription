"""Signals for the generic template API.

After the custom-user refactor the User model itself carries the fields that
used to live in Profile — no auto-create signal is needed. This module now
registers cache invalidation for the dynamic menu: any change to Menu /
MenuSection / MenuItem bumps the menu-tree cache version (see
``api.shell.menu_cache``). Register project-specific signals here too.
"""

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Menu, MenuItem, MenuSection
from .shell.menu_cache import bump_menu_cache_version


@receiver(post_save, sender=Menu)
@receiver(post_save, sender=MenuSection)
@receiver(post_save, sender=MenuItem)
@receiver(post_delete, sender=Menu)
@receiver(post_delete, sender=MenuSection)
@receiver(post_delete, sender=MenuItem)
def _invalidate_menu_cache(sender, **kwargs):
    bump_menu_cache_version()
