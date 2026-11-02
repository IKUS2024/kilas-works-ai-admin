"""Offering policy contract; no provider calls, keys or production data."""
import os
import unittest
from unittest.mock import patch
from kilas_ai import chat_offering as offering


class OfferingPolicyTests(unittest.TestCase):
    def setUp(self):
        p=patch.dict(os.environ,{offering.MANAGED_FLAG:'',offering.CHAT_FREE_FLAG:'',offering.IMAGE_FREE_FLAG:''})
        p.start();self.addCleanup(p.stop)
        p=patch.object(offering.db,'query_one',side_effect=lambda sql,args:{'id':args[0]} if args[0] in (1,2) else None)
        self.query=p.start();self.addCleanup(p.stop)

    def test_disabled_by_default_without_role_or_wallet_changes(self):
        self.assertFalse(offering.managed())
        self.assertFalse(offering.sponsored(1,('CHAT',)))
        self.assertFalse(offering.image_free(1))
        self.query.assert_not_called()

    def test_text_and_image_sponsorship_are_independent(self):
        with patch.dict(os.environ,{offering.CHAT_FREE_FLAG:'true'}):
            self.assertTrue(offering.sponsored(1,('CHAT','WEB_SEARCH','PDF'),origin=offering._InteractiveOrigin(1,'thread',1,'policy',True,True)))
            self.assertTrue(offering.text_free(2))
            self.assertFalse(offering.sponsored(1,('IMAGE_GENERATION',)))
        with patch.dict(os.environ,{offering.IMAGE_FREE_FLAG:'true'}):
            self.assertTrue(offering.sponsored(2,('IMAGE_GENERATION','IMAGE_EDIT'),origin=offering._InteractiveOrigin(2,'thread',1,'policy',True,True)))
            self.assertFalse(offering.sponsored(1,('CHAT',)))

    def test_only_existing_authenticated_account_identifiers(self):
        with patch.dict(os.environ,{offering.CHAT_FREE_FLAG:'true',offering.IMAGE_FREE_FLAG:'true'}):
            for invalid in (None,0,-1,True,'1',999):
                with self.subTest(invalid=invalid):
                    self.assertFalse(offering.text_free(invalid))
                    self.assertFalse(offering.image_free(invalid))

    def test_no_audio_video_execution_or_empty_operation_grant(self):
        with patch.dict(os.environ,{offering.CHAT_FREE_FLAG:'true',offering.IMAGE_FREE_FLAG:'true'}):
            for operations in ((),('TRANSCRIPTION',),('VOICEOVER',),('VIDEO_GENERATION',),('CODE_EXECUTION',),('CHAT','VOICEOVER')):
                self.assertFalse(offering.sponsored(1,operations))

    def test_reversible_configuration_without_invented_trial_end(self):
        with patch.dict(os.environ,{offering.CHAT_FREE_FLAG:'on'}):
            self.assertTrue(offering.text_free(1))
        self.assertFalse(offering.text_free(1))
        self.assertEqual(offering.CHAT_MODEL,'gpt-6-luna')
        self.assertEqual(offering.IMAGE_MODEL,'gpt-image-2.5-sunburst')


if __name__=='__main__':unittest.main()
