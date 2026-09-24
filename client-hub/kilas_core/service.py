"""One injected processing entry point, with no storage or live-action dependencies.

This service is stateless: external_message_id is correlation metadata, NOT a durable
deduplication guarantee. Adapters must define replay behavior before accepting event IDs.
The Phase 1 simulator rejects supplied event IDs (its existing schema cannot persist them).
The provider owns its IO timeout; the existing simulator provider uses 45s / one model call.
"""
from collections.abc import Callable

from .contracts import ContractError, ConversationResult, HistoryMessage, InboundMessage

ReplyProvider = Callable[[InboundMessage, tuple[HistoryMessage, ...]], tuple[str | None, str | None]]


def process_message(message: InboundMessage, *, history: tuple[HistoryMessage, ...],
                    reply_provider: ReplyProvider) -> ConversationResult:
    if not isinstance(message, InboundMessage):
        raise ContractError("invalid_message")
    if not isinstance(history, tuple) or any(not isinstance(row, HistoryMessage) for row in history):
        raise ContractError("invalid_history")
    if not callable(reply_provider):
        raise ContractError("invalid_provider")

    scope = dict(business_id=message.business_id, channel=message.channel,
                 conversation_id=message.conversation_id, external_message_id=message.external_message_id)
    try:
        output = reply_provider(message, history[-10:])
    except Exception:
        # No retries, no fallback provider, and no exception text/credentials in results.
        return ConversationResult(**scope, reply=None, error="provider_error")
    if not isinstance(output, tuple) or len(output) != 2:
        return ConversationResult(**scope, reply=None, error="invalid_provider_result")
    reply, error = output
    if error is not None:
        return ConversationResult(**scope, reply=None, error="provider_error")
    try:
        return ConversationResult(**scope, reply=reply)
    except ContractError:
        return ConversationResult(**scope, reply=None, error="invalid_provider_result")
