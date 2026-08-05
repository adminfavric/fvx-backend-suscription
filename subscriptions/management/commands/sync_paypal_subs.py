"""
Reconcilia el espejo local de suscripciones PayPal con el estado REAL en PayPal.

Recorre todas las ``CheckoutSession`` de PayPal con estado ``subscribed`` y
consulta cada una en la API de PayPal: si allá ya no está activa (CANCELLED,
EXPIRED, SUSPENDED), se marca ``failed`` localmente para que el admin deje de
mostrarla como "Activa". Corrige el desfase que se produce cuando el webhook no
llegó (o fue rechazado) al cancelarse una suscripción.

Uso (dentro del contenedor web):
    python manage.py sync_paypal_subs            # aplica los cambios
    python manage.py sync_paypal_subs --dry-run  # solo muestra qué cambiaría

Es idempotente: correrlo varias veces no duplica ni rompe nada.
"""

from django.core.management.base import BaseCommand

from subscriptions.models import CheckoutSession, PaymentProvider
from subscriptions.services import PayPalError, get_paypal_client


class Command(BaseCommand):
    help = (
        "Sincroniza las suscripciones PayPal locales con su estado real en PayPal: "
        "las canceladas/expiradas/suspendidas allá se marcan 'failed' acá."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Solo muestra qué cambiaría, sin escribir en la base.",
        )

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        pp = get_paypal_client()
        sessions = CheckoutSession.objects.filter(
            provider=PaymentProvider.PAYPAL,
            status=CheckoutSession.Status.SUBSCRIBED,
        ).exclude(subscription_id="")

        total = sessions.count()
        changed = errors = 0
        self.stdout.write(f"Revisando {total} suscripción(es) PayPal activas localmente…")

        for cs in sessions.iterator():
            try:
                sub = pp.get_subscription(cs.subscription_id)
            except PayPalError as exc:
                errors += 1
                self.stderr.write(f"  ⚠ {cs.subscription_id} ({cs.email}): {exc}")
                continue

            status = (sub.get("status") or "").upper()
            if status in ("ACTIVE", "APPROVED"):
                continue  # sigue vigente en PayPal: no se toca

            changed += 1
            prefix = "[dry-run] " if dry else ""
            self.stdout.write(
                self.style.WARNING(
                    f"  {prefix}{cs.subscription_id} · {cs.email} · plan="
                    f"{cs.plan.slug if cs.plan_id else '—'} → PayPal={status}: "
                    "se marca 'failed' (sin acceso)."
                )
            )
            if not dry:
                cs.status = CheckoutSession.Status.FAILED
                cs.save(update_fields=["status", "modified"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Listo: {total} revisadas · {changed} "
                f"{'por corregir' if dry else 'corregidas'} · {errors} con error."
            )
        )
