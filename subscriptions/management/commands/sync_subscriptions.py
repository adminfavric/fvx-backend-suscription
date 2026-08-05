"""
Reconcilia el espejo local de suscripciones RECURRENTES (Flow y PayPal) con el
estado REAL en cada pasarela.

Recorre todas las ``CheckoutSession`` recurrentes con estado ``subscribed`` y
consulta cada una en su pasarela: si allá ya no está activa (cancelada, expirada,
suspendida o morosa), se marca ``failed`` localmente para que el admin deje de
mostrarla como "Activa". Corrige el desfase que se produce cuando el webhook no
llegó (o fue rechazado) al cancelarse una suscripción, y cubre a Flow, que
cancela al final del período sin notificar.

Las membresías por período (link de pago / manual / importada) no se tocan:
vencen solas por ``access_until``.

Uso (dentro del contenedor web):
    python manage.py sync_subscriptions            # aplica los cambios
    python manage.py sync_subscriptions --dry-run  # solo muestra qué cambiaría

Es idempotente: correrlo varias veces no duplica ni rompe nada. Pensado para
correr a diario vía cron.
"""

from django.core.management.base import BaseCommand

from subscriptions.models import CheckoutSession, PaymentProvider
from subscriptions.services import (
    FlowError,
    PayPalError,
    get_flow_client,
    get_paypal_client,
)


class Command(BaseCommand):
    help = (
        "Sincroniza las suscripciones recurrentes locales (Flow y PayPal) con su "
        "estado real en la pasarela: las que ya no están activas allá se marcan "
        "'failed' acá."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Solo muestra qué cambiaría, sin escribir en la base.",
        )

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        sessions = CheckoutSession.objects.filter(
            status=CheckoutSession.Status.SUBSCRIBED,
            provider__in=[PaymentProvider.FLOW, PaymentProvider.PAYPAL],
        ).exclude(subscription_id="")

        total = sessions.count()
        changed = errors = 0
        self.stdout.write(f"Revisando {total} suscripción(es) recurrentes activas localmente…")

        for cs in sessions.iterator():
            try:
                active, gateway_status = self._gateway_status(cs)
            except (FlowError, PayPalError) as exc:
                errors += 1
                self.stderr.write(f"  ⚠ {cs.subscription_id} ({cs.email}): {exc}")
                continue

            if active:
                continue  # sigue vigente en la pasarela: no se toca

            changed += 1
            prefix = "[dry-run] " if dry else ""
            self.stdout.write(
                self.style.WARNING(
                    f"  {prefix}{cs.provider} · {cs.subscription_id} · {cs.email} · "
                    f"plan={cs.plan.slug if cs.plan_id else '—'} → "
                    f"pasarela={gateway_status}: se marca 'failed' (sin acceso)."
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

    @staticmethod
    def _gateway_status(cs) -> tuple[bool, str]:
        """(activa, estado_crudo) según la pasarela de la sesión."""
        if cs.provider == PaymentProvider.PAYPAL:
            sub = get_paypal_client().get_subscription(cs.subscription_id)
            status = (sub.get("status") or "").upper()
            return status in ("ACTIVE", "APPROVED"), status
        sub = get_flow_client().get_subscription(cs.subscription_id)
        status = str(sub.get("status"))
        return status == "1", status
