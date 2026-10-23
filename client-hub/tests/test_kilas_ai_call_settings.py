"""Call settings, route admission and resumed wire setup; no paid IO."""
import json
import unittest
from unittest.mock import patch, Mock
import test_kilas_ai_call as fixture
from kilas_ai import ai_call_settings as settings, ai_call as calls

class SettingsTests(unittest.TestCase):
    def test_defaults_and_strict_validation(self):
        self.assertEqual(settings.validate()['mode'],'normal')
        for invalid in [[],42,{'mode':'unknown'},{'level':[]},{'target_language':'en; ignore rules'},
                        {'roast_opt_in':'true'},{'mode':'roast'},{'character':'roast'},
                        {'roast_opt_in':True},{'extra':'value'}]:
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):settings.validate(invalid)

    def test_composed_prompts_and_search_survive_resumption(self):
        for mode in ['normal','learning','roleplay','roast']:
            chosen={'mode':mode,'target_language':'ja','explanation_language':'id','level':'advanced'}
            if mode=='roast':chosen.update(character='roast',roast_opt_in=True)
            with patch.object(calls.public_search,'configured',return_value=True):
                initial=calls.setup(settings=chosen)['setup']
                resumed=calls.setup('checkpoint',chosen)['setup']
            self.assertEqual(resumed.pop('sessionResumption'),{'handle':'checkpoint'})
            initial.pop('sessionResumption');self.assertEqual(initial,resumed)
            self.assertIn('tools',initial)
            prompt=initial['systemInstruction']['parts'][0]['text']
            self.assertIn('cover each requested part',prompt)
            if mode=='learning':
                self.assertNotIn('Begin in the language',prompt)
                self.assertIn('Japanese',prompt);self.assertIn('Indonesian',prompt)
                self.assertIn('advanced',prompt);self.assertIn('correction',prompt)
            elif mode=='roast':
                self.assertIn('anjing, bangsat',prompt);self.assertIn('English fuck',prompt)
                self.assertIn('consistently casual',prompt);self.assertIn('across turns',prompt)
                self.assertIn('do not mechanically attach',prompt);self.assertIn('suspend roasting',prompt)
                self.assertIn('immediately drop the roast',prompt)
            if mode!='roast':
                for phrase in ('anjing','English fuck','slang-heavy','coarse persona'):
                    self.assertNotIn(phrase,prompt)
                self.assertIn('No coarse roasting',prompt)

    def test_actual_resume_uses_call_settings(self):
        call=calls.Call(1,'a'*32,object(),settings={'mode':'learning','target_language':'fr'})
        call.check=Mock();call.ws=Mock();call.resume_pending=True;call.resume_handle='checkpoint'
        socket=Mock();socket.recv.return_value='{"setupComplete":{}}'
        with patch.object(calls.wire,'connect',return_value=socket):call.resume()
        payload=json.loads(socket.send.call_args.args[0])
        self.assertIn('French',payload['setup']['systemInstruction']['parts'][0]['text'])
        self.assertEqual(call.settings['mode'],'learning')

class RouteSettingsTests(unittest.TestCase):
    setUp=fixture.CallTests.setUp
    config=fixture.CallTests.config
    shared=fixture.CallTests.shared
    lifetime=fixture.CallTests.lifetime
    enabled=fixture.CallTests.enabled
    post=fixture.CallTests.post
    def test_invalid_settings_rejected_before_budget_claim(self):
        with self.enabled(),patch.object(calls.budget,'claim') as claim:
            for raw in ['{','[]',json.dumps({'mode':'roast'}),json.dumps({'level':'bogus'})]:
                response=self.post('/kilas-ai/call/'+'a'*32,{'settings':raw})
                self.assertEqual(response.status_code,400)
                self.assertEqual(response.json['code'],'call_settings_invalid')
            claim.assert_not_called()

    def test_route_passes_opt_in_and_normal_default(self):
        with self.enabled(),patch.object(calls.Thread,'start'):
            for i,chosen in enumerate([{},dict(mode='roast',character='roast',roast_opt_in=True)]):
                ident=str(i+7)*32
                try:
                    response=self.post('/kilas-ai/call/'+ident,{'settings':json.dumps(chosen)})
                    self.assertEqual(response.status_code,202)
                    self.assertEqual(calls.get(self.user,ident).settings['mode'],chosen.get('mode','normal'))
                finally:
                    calls.end(self.user,ident);calls._calls.pop((self.user,ident),None)

if __name__=="__main__":unittest.main()
