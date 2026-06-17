"""Adapter "console" para tests y debugging.

No envía nada: acumula los payloads en memoria y los printea por stdout.
Ideal para tests unitarios — el test inspecciona ``adapter.sent`` para
validar lo que se intentó enviar.
"""

from .base import EmailPayload


class ConsoleAdapter:
    """Adapter de tests; acumula los emails y los imprime."""

    def __init__(self) -> None:
        self.sent: list[EmailPayload] = []

    def send(self, payload: EmailPayload) -> str:
        print(
            f"\n──── EMAIL ────\n"
            f"To: {payload.to}\n"
            f"Subject: {payload.subject}\n"
            f"Tags: {payload.tags}\n"
            f"────\n"
            f"{payload.html[:300]}...\n",
        )
        self.sent.append(payload)
        return f"console-{len(self.sent)}"
