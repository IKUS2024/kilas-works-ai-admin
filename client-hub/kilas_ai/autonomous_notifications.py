"""Durable in-app delivery; future transports consume events without changing workers."""
from typing import Protocol
from . import autonomous_store


class NotificationAdapter(Protocol):
    def publish(self, conn, job_id: int, kind: str, summary: str, key: str) -> None: ...


class InApp:
    def publish(self, conn, job_id, kind, summary, key):
        autonomous_store.event(conn, job_id, kind, summary, key)


adapter: NotificationAdapter = InApp()
