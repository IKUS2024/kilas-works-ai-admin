"""Approved bounded sources/arming, no provider calls."""
import os
import unittest
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
from kilas_ai import live_gemini_validation_once as validation


class ValidationTests(unittest.TestCase):
    def test_default_off_never_launches(self):
        with patch.dict(os.environ,{},clear=True),patch.object(validation.subprocess,'Popen') as child:
            self.assertFalse(validation.launch());validation.run();child.assert_not_called()

    def test_exact_service_arm_and_short_expiry_required(self):
        values={validation.ARM:validation.RUN,'RENDER_SERVICE_ID':'srv-da7ti2psrm7s73dh9i2g',
                'KILAS_TRANSLATOR_VALIDATION_EXPIRES_AT':(datetime.now(timezone.utc)+timedelta(minutes=20)).isoformat(),
                'KILAS_LIVE_GEMINI_QA_OWNER_ID':'9','KILAS_LIVE_GEMINI_QA_OWNER_EMAIL':'synthetic@example.test'}
        with patch.dict(os.environ,values,clear=True):
            self.assertIsNotNone(validation.config())
            with patch.dict(os.environ,{validation.ARM:'other'}):self.assertIsNone(validation.config())
            with patch.dict(os.environ,{'KILAS_TRANSLATOR_VALIDATION_EXPIRES_AT':(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()}):self.assertIsNone(validation.config())
        for language in ('id','en'):
            raw=validation.fixture(language);self.assertEqual(len(raw),320000);self.assertTrue(any(raw));self.assertFalse(any(raw[-16000:]))


if __name__=='__main__':unittest.main()
