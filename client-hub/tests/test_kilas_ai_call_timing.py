"""Synthetic provider event ordering, no audio/provider/DB IO."""
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kilas_ai.ai_call_timing import TurnTiming


class TimingTests(unittest.TestCase):
    def test_first_audio_during_activity_is_distinguished_from_after_end(self):
        now = [1.0]
        timing = TurnTiming(clock=lambda: now[0])
        timing.activity('ACTIVITY_START')
        timing.audio(); timing.audio()
        self.assertEqual(timing.report()['first_audio_during_activity'], 1)
        timing.boundary()
        timing.activity('ACTIVITY_END')
        now[0] = 1.35
        timing.audio()
        self.assertEqual(timing.report()['recent_first_audio'], [
            {'speech_active': True, 'after_activity_end_ms': None},
            {'speech_active': False, 'after_activity_end_ms': 350}])
        self.assertEqual(timing.report()['audio_turns'], 2)

    def test_missing_activity_is_unknown_and_new_speech_clears_old_end(self):
        timing = TurnTiming(clock=lambda: 10)
        timing.audio()
        self.assertIsNone(timing.report()['recent_first_audio'][0]['after_activity_end_ms'])
        timing.activity('ACTIVITY_END'); timing.activity('ACTIVITY_START')
        timing.boundary(); timing.audio()
        self.assertIsNone(timing.report()['recent_first_audio'][-1]['after_activity_end_ms'])

    def test_report_is_bounded_copied_and_ignores_arbitrary_event_content(self):
        timing = TurnTiming()
        timing.activity('PRIVATE SENTINEL')
        for _ in range(20):
            timing.boundary(); timing.audio()
        report = timing.report()
        self.assertEqual(len(report['recent_first_audio']), 8)
        self.assertNotIn('PRIVATE', str(report))
        report['recent_first_audio'][0]['speech_active'] = True
        self.assertFalse(timing.report()['recent_first_audio'][0]['speech_active'])


if __name__ == '__main__':
    unittest.main()
