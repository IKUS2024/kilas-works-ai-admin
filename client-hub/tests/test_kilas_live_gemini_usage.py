"""Provider metadata evidence, no network or billing IO."""
import unittest
from kilas_ai.live_gemini_usage import UsageEvidence, VerifiedUsage, combine


def event(prompt=25,output=25,terminal=True):
    return {'usageMetadata':{'promptTokenCount':prompt,'responseTokenCount':output,'totalTokenCount':prompt+output},
            'serverContent':{'turnComplete':terminal}}


class UsageTests(unittest.TestCase):
    def test_only_terminal_complete_covered_usage_is_reconcilable(self):
        e=UsageEvidence();self.assertIsNone(e.verified(32000,48000,True))
        e.observe(event(),True)
        self.assertEqual(e.verified(32000,48000,True),VerifiedUsage(25,25))
        self.assertIsNone(e.verified(32001,48000,True))
        self.assertIsNone(e.verified(32000,48001,True))
        self.assertIsNone(e.verified(32000,48000,False))

    def test_incomplete_interrupted_or_malformed_usage_cannot_release_money(self):
        for value in ({}, {'usageMetadata':None}, event(1,1,False),
                      {**event(),'serverContent':{'turnComplete':True,'interrupted':True}},
                      {**event(),'serverContent':{'turnComplete':True,'interactionStatus':'IN_PROGRESS'}},
                      {'usageMetadata':{'promptTokenCount':True,'responseTokenCount':1,'totalTokenCount':2}},
                      {'usageMetadata':{'promptTokenCount':1,'responseTokenCount':1,'totalTokenCount':3}},
                      {'usageMetadata':{'promptTokenCount':-1,'responseTokenCount':1,'totalTokenCount':0}},
                      {**event(),'usageMetadata':{**event()['usageMetadata'],'thoughtsTokenCount':1}}):
            with self.subTest(value=value):
                e=UsageEvidence();e.observe(value,True);self.assertIsNone(e.verified(0,0,True))
        e=UsageEvidence();e.observe(event(),False);self.assertIsNone(e.verified(0,0,True))

    def test_duplicate_and_cumulative_observations_never_reduce_cost(self):
        e=UsageEvidence();e.observe(event(10,20,False),False);e.observe(event(10,20,False),False);e.observe(event(20,40),True)
        self.assertEqual(e.verified(0,0,True),VerifiedUsage(40,80))
        self.assertIsNone(combine([e.verified(0,0,True),None]))
        self.assertEqual(combine([VerifiedUsage(1,1),VerifiedUsage(1,1)]).micro_usd,49)
        self.assertEqual(VerifiedUsage(1,0).micro_usd,4)


if __name__=='__main__':unittest.main()
