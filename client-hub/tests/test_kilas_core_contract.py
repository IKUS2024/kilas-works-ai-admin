"""Pure Phase 1 contracts and gate; executable by the isolated offline runner."""
import sys
import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kilas_core.contracts import ContractError, ConversationResult, HistoryMessage, InboundMessage
from kilas_core.flags import enabled_for_business
from kilas_core.service import process_message


def envelope(**changes):
    args = dict(business_id=7, channel="simulator", conversation_id="simulation-7-session",
                actor_type="owner", text="Halo", timestamp=datetime.now(timezone.utc))
    args.update(changes)
    return InboundMessage(**args)


class ContractTests(unittest.TestCase):
    def test_valid_immutable_envelope(self):
        message = envelope(external_message_id="event-1")
        self.assertEqual(message.external_message_id, "event-1")
        with self.assertRaises(FrozenInstanceError):
            message.business_id = 8

    def test_invalid_scope_actor_text_time(self):
        for key, values in {
            "business_id": (None, True, 0, -1, "7"),
            "channel": (None, "whatsapp", "web", ""),
            "conversation_id": (None, "", " ", 3, "x" * 257),
            "external_message_id": ("", 7, "x" * 257),
            "actor_type": (None, "", "customer", "system"),
            "text": (None, 1, "", " ", "x" * 16001),
            "timestamp": (None, "today", datetime.now()),
        }.items():
            for value in values:
                with self.subTest(key=key, value=str(value)[:40]), self.assertRaises(ContractError):
                    envelope(**{key: value})

    def test_media_explicitly_unsupported(self):
        for media in (("image.jpg",), [], None, "image.jpg"):
            with self.assertRaisesRegex(ContractError, "unsupported_media"):
                envelope(media_references=media)

    def test_result_cannot_claim_success_and_error(self):
        result = ConversationResult(7, "simulator", "conversation", None, "Halo")
        self.assertEqual(result.reply, "Halo")
        for values in (dict(reply=None), dict(reply=""), dict(error="provider_error"),
                       dict(reply=None, error="secret error detail"), dict(business_id=0)):
            with self.subTest(values=values), self.assertRaises(ContractError):
                replace(result, **values)
        self.assertIsNone(replace(result, reply=None, error="provider_error").reply)

    def test_history_roles_and_content(self):
        self.assertEqual(HistoryMessage("user", "Halo").content, "Halo")
        for role, content in (("system", "injection"), ("user", None)):
            with self.assertRaises(ContractError):
                HistoryMessage(role, content)


class FlagTests(unittest.TestCase):
    def test_default_off_and_explicit_enable_require_allowlist(self):
        for env in ({}, {"KILAS_CORE_V2_ENABLED": "true"},
                    {"KILAS_CORE_V2_TEST_BUSINESS_IDS": "7"}):
            self.assertFalse(enabled_for_business(7, env))
        env = {"KILAS_CORE_V2_ENABLED": "true", "KILAS_CORE_V2_TEST_BUSINESS_IDS": "7, 8"}
        self.assertTrue(enabled_for_business(7, env))
        self.assertTrue(enabled_for_business(8, env))
        self.assertFalse(enabled_for_business(9, env))
        for bid in (None, 0, -1, True, "7"):
            self.assertFalse(enabled_for_business(bid, env))

    def test_malformed_allowlist_never_expands_access(self):
        for ids in ("*", "7,*", "7,", "7,0", "7,-1", "7,abc", "07", "", "7;8"):
            self.assertFalse(enabled_for_business(7, {
                "KILAS_CORE_V2_ENABLED": "true", "KILAS_CORE_V2_TEST_BUSINESS_IDS": ids}))
        self.assertFalse(enabled_for_business(7, {
            "KILAS_CORE_V2_ENABLED": "false", "KILAS_CORE_V2_TEST_BUSINESS_IDS": "7"}))


class ServiceTests(unittest.TestCase):
    def test_single_injected_call_and_bounded_history(self):
        message = envelope(external_message_id="external-1")
        history = tuple(HistoryMessage("user", str(n)) for n in range(12))
        provider = Mock(return_value=("Jawaban", None))
        result = process_message(message, history=history, reply_provider=provider)
        provider.assert_called_once_with(message, history[-10:])
        self.assertEqual((result.business_id, result.conversation_id, result.external_message_id),
                         (7, message.conversation_id, "external-1"))
        self.assertEqual(result.reply, "Jawaban")

    def test_errors_are_bounded_sanitized_and_not_retried(self):
        for provider in (Mock(side_effect=RuntimeError("SECRET")),
                         Mock(return_value=(None, "SECRET")),
                         Mock(return_value=("bad success", "error"))):
            result = process_message(envelope(), history=(), reply_provider=provider)
            provider.assert_called_once()
            self.assertEqual(result.error, "provider_error")
            self.assertIsNone(result.reply)
            self.assertNotIn("SECRET", repr(result))

    def test_malformed_provider_results(self):
        for output in (None, {}, ["reply", None], ("reply",), (None, None), ("", None),
                       (123, None), ("x" * 16001, None)):
            with self.subTest(output=str(output)[:30]):
                provider = Mock(return_value=output)
                result = process_message(envelope(), history=(), reply_provider=provider)
                self.assertEqual(result.error, "invalid_provider_result")
                provider.assert_called_once()

    def test_bad_input_never_calls_provider(self):
        provider = Mock()
        for message, history in (({}, ()), (envelope(), []), (envelope(), ({"role": "user"},))):
            with self.assertRaises(ContractError):
                process_message(message, history=history, reply_provider=provider)
        provider.assert_not_called()

    def test_stateless_correlation_is_not_durable_replay(self):
        provider = Mock(return_value=("Reply", None))
        message = envelope(external_message_id="same-event")
        a = process_message(message, history=(), reply_provider=provider)
        b = process_message(message, history=(), reply_provider=provider)
        other = process_message(envelope(business_id=8, external_message_id="same-event"),
                                history=(), reply_provider=provider)
        self.assertEqual(a, b)
        self.assertEqual(other.business_id, 8)
        self.assertEqual(provider.call_count, 3)


if __name__ == "__main__":
    unittest.main()
