"""Harmless JSON formatting only; scoped drafts remain fail-closed."""
import json
import unittest
from unittest.mock import patch
from test_knowledge_assist import AssistTests, assist


class ParserTests(unittest.TestCase):
    setUp = AssistTests.setUp
    state = AssistTests.state
    form = AssistTests.form
    respond = AssistTests.respond

    def raw(self, text):
        self.post.return_value.json.return_value['content'][0]['text'] = text

    def test_plain_whitespace_json(self):
        self.raw(' \n'+json.dumps({'draft_fields':{'short_description':'Draft'}})+'\n\t')
        response=self.client.post(self.assist_url,json=self.payload)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json,{'draft_fields':{'short_description':'Draft'},'questions':[],'warnings':[]})
        self.post.assert_called_once()

    def test_json_fence(self):
        self.raw(' \n```json\n{"draft_fields":{}}\n```\t')
        self.assertEqual(self.client.post(self.assist_url,json=self.payload).status_code,200)
        self.post.assert_called_once()

    def test_plain_fence(self):
        self.raw('```\r\n{"draft_fields":{}}\r\n```')
        self.assertEqual(self.client.post(self.assist_url,json=self.payload).status_code,200)
        self.post.assert_called_once()

    def test_each_optional_list_defaults(self):
        for key in ('questions','warnings'):
            result=assist.validate_result({'draft_fields':{},key:['Item']},'business')
            self.assertEqual(result[key],['Item'])
            self.assertEqual(result['warnings' if key=='questions' else 'questions'],[])

    def test_required_object_and_unknown_keys(self):
        for value in ({}, {'questions':[]}, [], None, 1, {'draft_fields':[]},
                      {'draft_fields':{},'extra':True}, {'draft_fields':{'package':'PRO'}}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                assist.validate_result(value,'business')

    def test_prose_multiple_documents_and_bad_fences_rejected(self):
        for text in ('Hello {"draft_fields":{}}', '{"draft_fields":{}} Thanks', '{} {}',
                     '```json\n{}\n```\n```json\n{}\n```', '```python\n{}\n```',
                     '```json\n{}', '```json\n{}\n``` after', 'before ```json\n{}\n```'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                assist.parse_model_text(text)

    def test_invalid_json_reason_and_generic_customer_error(self):
        self.raw('{bad')
        with patch('builtins.print') as log:
            response=self.client.post(self.assist_url,json=self.payload)
        self.assertEqual(response.status_code,502)
        self.assertEqual(response.json['error'],assist.ERROR)
        log.assert_called_once_with('KNOWLEDGE_ASSIST: invalid_json')
        self.post.assert_called_once()

    def test_invalid_schema_reason(self):
        self.raw('{"draft_fields":{"package":"PRO"}}')
        with patch('builtins.print') as log:
            response=self.client.post(self.assist_url,json=self.payload)
        self.assertEqual(response.status_code,502)
        log.assert_called_once_with('KNOWLEDGE_ASSIST: invalid_schema')
        self.post.assert_called_once()

    def test_invalid_content_block_reason(self):
        self.post.return_value.json.return_value['content']=[{'type':'image'}]
        with patch('builtins.print') as log:
            response=self.client.post(self.assist_url,json=self.payload)
        self.assertEqual(response.status_code,502)
        log.assert_called_once_with('KNOWLEDGE_ASSIST: invalid_content_block')
        self.post.assert_called_once()

    def test_incomplete_result_reason(self):
        self.post.return_value.json.return_value['stop_reason']='max_tokens'
        with patch('builtins.print') as log:
            response=self.client.post(self.assist_url,json=self.payload)
        self.assertEqual(response.status_code,502)
        log.assert_called_once_with('KNOWLEDGE_ASSIST: incomplete_result')
        self.post.assert_called_once()

    def test_limits_language_and_arrays_remain_strict(self):
        for value,scope in (({'draft_fields':{},'questions':None},'business'),
                            ({'draft_fields':{},'warnings':'text'},'business'),
                            ({'draft_fields':{},'questions':['q']*4},'business'),
                            ({'draft_fields':{},'warnings':['w'*401]},'business'),
                            ({'draft_fields':{'short_description':'x'*1601}},'business'),
                            ({'draft_fields':{'primary_language':'fr'}},'communication')):
            with self.subTest(value=value),self.assertRaises(ValueError):
                assist.validate_result(value,scope)

    def test_fenced_result_still_does_not_save(self):
        before=self.state()
        self.raw('```json\n{"draft_fields":{"short_description":"Draft only"}}\n```')
        self.assertEqual(self.client.post(self.assist_url,json=self.payload).status_code,200)
        self.assertEqual(self.state(),before)
        self.post.assert_called_once()


if __name__=='__main__':unittest.main()
