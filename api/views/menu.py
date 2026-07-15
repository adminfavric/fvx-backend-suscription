import hashlib

from django.core.cache import cache
from django.db.models import Prefetch
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ..models import Menu, MenuItem
from ..roles import user_can_see_menu_item, user_menu_role_score
from ..shell.menu_cache import MENU_CACHE_TTL, menu_cache_version


class MenuViewSet(viewsets.GenericViewSet):
    """Resolve a ``Menu`` and return its tree (sections → items) for the current user."""

    permission_classes = [IsAuthenticated]
    queryset = Menu.objects.filter(is_active=True)

    def _resolve_menu(self, request):
        """
        Explicit ``menu_uuid`` wins. Otherwise the single ``is_default`` menu;
        last resort, the first menu alphabetically.
        """
        menu_uuid = request.query_params.get("menu_uuid")
        qs = self.get_queryset()
        if menu_uuid:
            return qs.filter(uuid=menu_uuid).first()

        default = qs.filter(is_default=True).first()
        if default:
            return default
        return qs.order_by("name").first()

    @action(detail=False, methods=["get"], url_path="tree")
    def tree(self, request):
        # Cache por (versión global, menú pedido, rol efectivo). La salida es
        # idéntica para usuarios con el mismo role-score sobre el mismo menú;
        # se invalida al editar cualquier Menu/Section/Item (signals → versión).
        menu_param = request.query_params.get("menu_uuid") or "__default__"
        role_score = user_menu_role_score(request.user)
        # Permisos por persona: si el usuario tiene páginas explícitas, su árbol es
        # propio → firma en la clave de caché (los que no tienen, comparten "0").
        overrides = getattr(request.user, "menu_slugs", None) or []
        override_sig = (
            hashlib.md5(",".join(sorted(overrides)).encode()).hexdigest()[:8]
            if overrides else "0"
        )
        cache_key = f"fvx:menu_tree:{menu_cache_version()}:{menu_param}:{role_score}:{override_sig}"
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)

        menu = self._resolve_menu(request)
        if not menu:
            empty = {"menu": None, "sections": []}
            cache.set(cache_key, empty, MENU_CACHE_TTL)
            return Response(empty)

        sections_out = []
        sections = (
            menu.sections.filter(is_active=True)
            .order_by("order", "id")
            .prefetch_related(
                Prefetch(
                    "items",
                    queryset=MenuItem.objects.filter(is_active=True).order_by("order", "id"),
                )
            )
        )
        for sec in sections:
            items_out = []
            for it in sec.items.all():
                if not user_can_see_menu_item(request.user, it.allowed_roles, it.slug):
                    continue
                items_out.append(
                    {
                        "id": it.id,
                        "uuid": it.uuid,
                        "name": it.name,
                        "slug": it.slug,
                        "route": it.route,
                        "icon": it.icon or "",
                        "order": it.order,
                        "allowed_roles": it.allowed_roles or [],
                    }
                )
            if items_out:
                sections_out.append(
                    {
                        "id": sec.id,
                        "uuid": sec.uuid,
                        "name": sec.name,
                        "slug": sec.slug,
                        "order": sec.order,
                        "items": items_out,
                    }
                )

        menu_payload = {
            "id": menu.id,
            "uuid": menu.uuid,
            "name": menu.name,
            "slug": menu.slug,
            "is_default": menu.is_default,
        }
        payload = {"menu": menu_payload, "sections": sections_out}
        cache.set(cache_key, payload, MENU_CACHE_TTL)
        return Response(payload)

    @action(detail=False, methods=["get"], url_path="pages")
    def pages(self, request):
        """Lista TODAS las páginas del menú (slug + nombre + sección), sin filtrar
        por el rol de quien pregunta. La usa el formulario de Usuarios para elegir
        qué páginas ve cada persona."""
        items = (
            MenuItem.objects.filter(is_active=True)
            .select_related("section")
            .order_by("section__order", "order", "name")
            .values("slug", "name", "section__name")
        )
        return Response([
            {"slug": it["slug"], "name": it["name"], "section": it["section__name"] or ""}
            for it in items
        ])
