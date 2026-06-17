"""
Reactiva ``User.is_active`` sin entrar al admin.

Útil si se desactivó el único usuario administrador desde la API o la tabla Users.

Ejemplo::

    python manage.py fvx_reactivate_user admin
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

User = get_user_model()


class Command(BaseCommand):
    help = "Pone is_active=True en el User para el nombre de usuario indicado."

    def add_arguments(self, parser):
        parser.add_argument("username", type=str, help="Nombre de usuario (USERNAME_FIELD).")

    def handle(self, *args, **options):
        username = (options["username"] or "").strip()
        if not username:
            raise CommandError("Indique un nombre de usuario.")

        try:
            user = User._default_manager.get_by_natural_key(username)
        except User.DoesNotExist as exc:
            raise CommandError(f"No existe el usuario «{username}».") from exc

        if user.is_active:
            self.stdout.write(self.style.SUCCESS(f"«{username}» ya estaba activo."))
            return

        user.is_active = True
        user.save(update_fields=["is_active"])
        self.stdout.write(self.style.SUCCESS(f"«{username}» reactivado."))
