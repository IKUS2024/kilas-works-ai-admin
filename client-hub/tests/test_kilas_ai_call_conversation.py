"""Conversation setup/turn contracts only; no model semantics or external IO."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kilas_ai import ai_call as calls


class ConversationTests(unittest.TestCase):
    def test_language_continuity_contract_applies_to_initial_and_resumed_sessions(self):
        for search_enabled in (False, True):
            with self.subTest(search_enabled=search_enabled), patch.object(
                    calls.public_search, 'configured', return_value=search_enabled):
                initial = calls.setup()['setup']
                resumed = calls.setup('synthetic-checkpoint')['setup']
            self.assertEqual(resumed.pop('sessionResumption'), {'handle': 'synthetic-checkpoint'})
            self.assertEqual(initial.pop('sessionResumption'), {})
            self.assertEqual(initial, resumed)
            prompt = initial['systemInstruction']['parts'][0]['text']
            self.assertIn('Match answer depth to the request', prompt)
            self.assertIn('cover each requested part without filler', prompt)
            self.assertNotIn('Keep spoken answers concise', prompt)
            self.assertIn('Switch the conversation language only when the person explicitly asks', prompt)
            self.assertNotIn('This is a new conversation', prompt)
            self.assertNotIn('translationConfig', initial['generationConfig'])
            self.assertNotIn('targetLanguageCode', json.dumps(initial))
            self.assertEqual('tools' in initial, search_enabled)
            self.assertEqual(initial['generationConfig']['maxOutputTokens'], 1024)

    def test_two_spoken_turns_do_not_generate_language_menu_commands_or_translation_setup(self):
        call = calls.Call(1, 'c'*32, object())
        call.check = Mock(); call.transport_check = Mock()
        utterances = ('Saya perlu membandingkan dua pilihan untuk pekerjaan saya.',
                      'Maksud saya istilah bahasa Spanyol itu.')
        events = [{'setupComplete': {}}]
        for utterance in utterances:
            events.extend(({'voiceActivity': {'type': 'ACTIVITY_START'}},
                           {'serverContent': {'inputTranscription': {'text': utterance}}},
                           {'voiceActivity': {'type': 'ACTIVITY_END'}},
                           {'serverContent': {'turnComplete': True}}))
        sent = []
        def receive():
            if events: return json.dumps(events.pop(0))
            call.closed.set(); return '{}'
        socket = Mock(send=lambda raw: sent.append(json.loads(raw)), recv=receive)
        with patch.object(calls.public_search, 'configured', return_value=False), \
             patch.object(calls.wire, 'connect', return_value=socket), \
             patch.object(calls.wire, 'setup', side_effect=AssertionError('Translator setup used')) as translator, \
             patch.object(calls.Thread, 'start'), patch.object(calls, 'Timer'), \
             patch.object(calls.budget, 'dispatch'), patch.object(calls.budget, 'finish'), \
             patch.object(calls.db, '_discard_cached_connection'), patch('builtins.print'):
            call.run()
        translator.assert_not_called()
        self.assertEqual(len(sent), 1)
        self.assertEqual(set(sent[0]), {'setup'})
        self.assertNotIn('translationConfig', sent[0]['setup']['generationConfig'])
        self.assertNotIn('clientContent', json.dumps(sent))
        self.assertEqual(call.turns, 2)
        self.assertEqual(call.input_transcript_chars, sum(map(len, utterances)))
        self.assertIs(call.ws, socket)

    def test_checkpoint_handoff_keeps_conversation_policy_without_transcript_replay(self):
        call = calls.Call(1, 'd'*32, object())
        call.check = Mock()
        call.ws = Mock()
        call.resume_pending = True; call.resume_handle = 'synthetic-checkpoint'
        call.go_away = True; call.renewing.set()
        sent = []
        socket = Mock(send=lambda raw: sent.append(json.loads(raw)), recv=lambda: '{"setupComplete":{}}')
        with patch.object(calls.public_search, 'configured', return_value=True), \
             patch.object(calls.wire, 'connect', return_value=socket), \
             patch.object(calls.wire, 'setup', side_effect=AssertionError('Translator setup used')) as translator:
            expected = calls.setup('synthetic-checkpoint')
            call.resume()
        translator.assert_not_called()
        self.assertEqual(sent, [expected])
        self.assertNotIn('translationConfig', sent[0]['setup']['generationConfig'])
        self.assertNotIn('clientContent', json.dumps(sent))
        self.assertFalse(call.renewing.is_set())
        self.assertIsNone(call.resume_handle)


if __name__ == '__main__': unittest.main()
