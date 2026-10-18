"""Deterministic real relay handoff race; no supplier connections."""
import unittest
from unittest.mock import patch
import test_kilas_live_translator_realtime as f
from kilas_ai import live_translator_realtime as rt

class HandoffTests(unittest.TestCase):
 setUp=f.RealtimeTests.setUp
 funded=f.RealtimeTests.funded
 on=f.RealtimeTests.on
 owner=f.RealtimeTests.owner
 session=f.RealtimeTests.session
 key=f.RealtimeTests.key
 credit=f.RealtimeTests.credit
 make=f.RealtimeTests.make
 row=f.RealtimeTests.row
 def test_watchdog_finishing_after_successful_input_handoff_cannot_cancel_translation(self):
  with self.funded(),self.on(),self.owner(),patch.object(rt.incremental,'enabled',return_value=True):
   relay=self.make();original=relay.check
   def delayed_check():
    # The watcher passed its wait while STT was open, then another thread
    # completed STT before this check. This is a valid phase transition.
    relay.close();original()
   with patch.object(relay.closed,'wait',return_value=False),patch.object(relay,'check',side_effect=delayed_check):relay.watch()
   self.assertIsNone(relay.error);self.assertFalse(relay.incremental.cancelled.is_set())
   relay.incremental.check()  # Owned PROCESSING translation is still valid.
   rt.budget.finish(relay.capability,False)
