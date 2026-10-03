"""Trusted checkout adapter boundary. Manual review remains the active gateway."""
from typing import Protocol


class Gateway(Protocol):
    def subscription(self, user_id: int) -> int: ...
    def capacity(self, user_id: int, pack: str) -> int: ...


class ManualTransfer:
    """Creates pending orders only; existing authorized review activates credit."""
    def subscription(self, user_id):
        from . import billing
        return billing.create_invoice(user_id, 'PLUS')

    def capacity(self, user_id, pack):
        from . import topups
        return topups.create_order(user_id, pack)


def current() -> Gateway:
    # An automated adapter must be separately configured/approved and implement
    # server-side verification. Client success URLs never activate anything here.
    return ManualTransfer()
