"""Immutable text-only envelopes. Adapters must resolve authorization before construction."""
from dataclasses import dataclass
from datetime import datetime


class ContractError(ValueError):
    """A stable error code, safe to return without echoing caller input."""


def _identifier(value, code):
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ContractError(code)


def _scope(business_id, channel, conversation_id, external_message_id):
    if type(business_id) is not int or business_id <= 0:
        raise ContractError("invalid_business_id")
    # Provider authentication and readiness are enforced by the channel adapter.
    if channel not in ("simulator", "web", "whatsapp"):
        raise ContractError("unsupported_channel")
    _identifier(conversation_id, "invalid_conversation_id")
    if external_message_id is not None:
        _identifier(external_message_id, "invalid_external_message_id")


@dataclass(frozen=True)
class InboundMessage:
    business_id: int
    channel: str
    conversation_id: str
    actor_type: str
    text: str
    timestamp: datetime
    external_message_id: str | None = None
    media_references: tuple[str, ...] = ()

    def __post_init__(self):
        _scope(self.business_id, self.channel, self.conversation_id, self.external_message_id)
        if self.actor_type != ("owner" if self.channel == "simulator" else "visitor"):
            raise ContractError("invalid_actor_type")
        if not isinstance(self.text, str) or not self.text.strip():
            raise ContractError("empty_message")
        if len(self.text) > 16000:
            raise ContractError("message_too_long")
        if (not isinstance(self.timestamp, datetime) or self.timestamp.tzinfo is None
                or self.timestamp.utcoffset() is None):
            raise ContractError("invalid_timestamp")
        if self.media_references != ():
            raise ContractError("unsupported_media")


@dataclass(frozen=True)
class HistoryMessage:
    role: str
    content: str

    def __post_init__(self):
        if self.role not in ("user", "assistant") or not isinstance(self.content, str):
            raise ContractError("invalid_history")


@dataclass(frozen=True)
class ConversationResult:
    business_id: int
    channel: str
    conversation_id: str
    external_message_id: str | None
    reply: str | None
    error: str | None = None

    def __post_init__(self):
        _scope(self.business_id, self.channel, self.conversation_id, self.external_message_id)
        if self.error is not None:
            if self.error not in ("provider_error", "invalid_provider_result") or self.reply is not None:
                raise ContractError("invalid_result")
        elif not isinstance(self.reply, str) or not self.reply.strip() or len(self.reply) > 16000:
            raise ContractError("invalid_result")
