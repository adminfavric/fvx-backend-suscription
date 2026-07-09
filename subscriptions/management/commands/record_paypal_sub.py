"""
Recupera una suscripción de PayPal que ya está activa en PayPal pero que no quedó
registrada en el sistema (típicamente porque el navegador no llamó al registro y
el webhook no la creó). Consulta el estado real en PayPal, mapea el plan y el
correo, y crea/actualiza la ``CheckoutSession`` para darle acceso al miembro.

Uso (dentro del contenedor web):
    python manage.py record_paypal_sub I-XXXXXXXXXXXX
    python manage.py record_paypal_sub I-XXXX --plan-slug membresia-oro --email persona@correo.com

Es idempotente: si la suscripción ya estaba registrada, la actualiza (no duplica).
"""

from django.core.management.base import BaseCommand, CommandError

from subscriptions.models import CheckoutSession, PaymentProvider, Plan
from subscriptions.services import PayPalError, get_paypal_client


class Command(BaseCommand):
    help = (
        "Registra/recupera una suscripción de PayPal ya activa (I-XXXX) que no "
        "quedó en el sistema: consulta PayPal, crea la CheckoutSession y da acceso."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "subscription_id",
            help="ID de la suscripción PayPal (formato I-XXXX), del panel de PayPal.",
        )
        parser.add_argument(
            "--plan-slug", default="",
            help="Slug del plan local, si no se puede mapear por paypal_plan_id.",
        )
        parser.add_argument(
            "--email", default="",
            help="Correo del suscriptor, si PayPal no lo entrega en la consulta.",
        )
        parser.add_argument(
            "--name", default="",
            help="Nombre del suscriptor (opcional; si no, se toma de PayPal).",
        )

    def handle(self, *args, **opts):
        sub_id = (opts["subscription_id"] or "").strip()
        if not sub_id:
            raise CommandError("Falta el ID de la suscripción.")

        # 1) Estado real en PayPal.
        try:
            sub = get_paypal_client().get_subscription(sub_id)
        except PayPalError as exc:
            raise CommandError(f"No se pudo consultar PayPal: {exc}")

        status = (sub.get("status") or "").upper()
        subscriber = sub.get("subscriber", {}) or {}
        name_obj = subscriber.get("name", {}) or {}

        # 2) Plan: por --plan-slug o mapeado por paypal_plan_id.
        if opts["plan_slug"]:
            plan = Plan.objects.filter(slug=opts["plan_slug"]).first()
            if not plan:
                raise CommandError(f"No existe un plan con slug '{opts['plan_slug']}'.")
        else:
            ppid = sub.get("plan_id")
            plan = Plan.objects.filter(paypal_plan_id=ppid).first() if ppid else None
            if not plan:
                raise CommandError(
                    f"No se pudo mapear el plan (paypal_plan_id={ppid!r}). "
                    "Reintenta agregando --plan-slug <slug-del-plan>."
                )

        # 3) Correo y nombre.
        email = opts["email"].strip() or (subscriber.get("email_address") or "").strip()
        if not email:
            raise CommandError(
                "PayPal no entregó el correo del suscriptor. Reintenta con --email <correo>."
            )
        name = (
            opts["name"].strip()
            or " ".join(x for x in [name_obj.get("given_name"), name_obj.get("surname")] if x).strip()
            or email
        )

        active = status in ("ACTIVE", "APPROVED")
        new_status = (
            CheckoutSession.Status.SUBSCRIBED if active else CheckoutSession.Status.FAILED
        )

        # 4) Crear o actualizar (idempotente por provider + subscription_id).
        cs, created = CheckoutSession.objects.get_or_create(
            provider=PaymentProvider.PAYPAL,
            subscription_id=sub_id,
            defaults={
                "plan": plan,
                "name": name,
                "email": email,
                "status": new_status,
                "origin_note": "Recuperada manualmente (record_paypal_sub).",
            },
        )
        if not created:
            cs.plan = plan
            cs.name = name
            cs.email = email
            cs.status = new_status
            cs.save(update_fields=["plan", "name", "email", "status", "modified"])

        verb = "Creada" if created else "Actualizada"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb}: {sub_id} → {email} · plan={plan.slug} · "
                f"PayPal={status} · acceso={'SÍ' if active else 'NO'}"
            )
        )
        if not active:
            self.stdout.write(
                self.style.WARNING(
                    "OJO: la suscripción NO está activa en PayPal; se registró como "
                    "'failed' y NO se dio acceso."
                )
            )
