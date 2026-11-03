"""Synthetic pixels and prompt contracts; these are not model accuracy evaluations."""
import base64
import io
import os
import unittest
from unittest.mock import MagicMock, patch
from PIL import Image, ImageDraw
from werkzeug.datastructures import FileStorage
import test_kilas_managed_offering as fixture
from kilas_ai import attachments, agent_store, agent_chat, store, conversation_context
from kilas_ai import selected_provider, providers, model_policy, chat_offering


def image(color, name='synthetic.png'):
    out = io.BytesIO()
    pic = Image.new('RGB', (900, 1200), color)
    ImageDraw.Draw(pic).rectangle((180, 220, 720, 980), outline='white', width=14)
    pic.save(out, 'PNG')
    return {'filename': name, 'mime_type': 'image/png', 'content': out.getvalue(),
            'byte_size': len(out.getvalue()), 'extracted_text': None}


def image_bytes(content):
    return [base64.b64decode(block['image_url']['url'].split(',', 1)[1])
            for block in content if block.get('type') == 'image_url'] if isinstance(content, list) else []


class VisualGroundingTests(unittest.TestCase):
    setUp = fixture.ManagedOfferingTests.setUp
    client = fixture.ManagedOfferingTests.client
    submit = fixture.ManagedOfferingTests.submit

    def agent_context(self, text, prepared=None):
        agent_store.append(self.owner, 'user', text, self.conversation, attachments=prepared)
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'synthetic-only'}), self.client().application.test_request_context():
            from flask import request
            request.chat_selected_model = chat_offering.CHAT_MODEL
            if prepared:
                request.work_attachments = prepared
            return agent_chat.context(self.owner, self.conversation)

    def test_ordinary_upload_keeps_dimensions_bytes_and_current_multimodal_input(self):
        sample = image('navy')
        prepared = attachments.prepare(FileStorage(stream=io.BytesIO(sample['content']), filename=sample['filename'], content_type='image/png'))
        self.assertEqual(prepared['content'], sample['content'])
        self.assertFalse(prepared['normalized'])
        with Image.open(io.BytesIO(prepared['content'])) as pixels:
            self.assertEqual(pixels.size, (900, 1200))
        blocks = attachments.prompt_content('Identify the physical object.', [prepared])
        bounded = conversation_context.bounded([{'role': 'user', 'content': blocks}], 1)
        self.assertEqual(image_bytes(bounded[-1]['content']), [sample['content']])

    def test_native_luna_payload_keeps_current_pixels_and_gets_grounding_without_budget_change(self):
        from kilas_ai import visual_grounding
        samples = [image('red'), image('green')]
        blocks = attachments.prompt_content('Compare these objects briefly.', samples)
        messages = model_policy.ChatContext([{'role': 'user', 'content': blocks}])
        messages.selected_model = chat_offering.CHAT_MODEL
        profile = model_policy.chat_profile(messages)
        response = MagicMock();response.status_code = 200;response.__enter__.return_value = response
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'synthetic-only'}), \
             patch.object(selected_provider.requests, 'post', return_value=response) as post, \
             patch.object(providers, '_events', return_value=iter([{'model': chat_offering.CHAT_MODEL, 'choices': [{'delta': {'content': 'Synthetic transport result.'}, 'finish_reason': 'stop'}]}])):
            list(selected_provider.stream('SMART', messages))
        payload = post.call_args.kwargs['json']
        self.assertEqual(post.call_count, 1)
        self.assertEqual(payload['model'], chat_offering.CHAT_MODEL)
        self.assertEqual(payload['reasoning_effort'], profile['effort'])
        self.assertEqual(payload['max_completion_tokens'], profile['output_tokens'])
        self.assertIn(visual_grounding.GUIDANCE, payload['messages'][0]['content'])
        self.assertEqual(image_bytes(payload['messages'][-1]['content']), [sample['content'] for sample in samples])
        self.assertEqual(payload['messages'][-1]['content'], blocks)
        self.assertTrue(all('detail' not in block['image_url'] for block in blocks[1:]))  # Preserve provider auto; no evidence of low detail.

    def test_policy_is_image_scoped_and_preserves_proportionate_grounded_uncertainty(self):
        from kilas_ai import visual_grounding
        self.assertEqual(visual_grounding.instruction([{'role': 'user', 'content': 'Describe demo.png'}]), '')
        self.assertEqual(visual_grounding.instruction([{'role': 'user', 'content': attachments.prompt_content('Image', [image('blue')])},
                                                      {'role': 'user', 'content': 'What is 6 times 7?'}]), '')
        # Diverse synthetic task descriptions; assert policy contract, not answers.
        for text in ('Identify an object decorated with leaves.', 'Read this diagram.', 'Does the label support the shape?',
                     'Earlier answer called this a box. Check the current image.', 'The view is partly obscured. What is visible?'):
            instruction = visual_grounding.instruction([{'role': 'assistant', 'content': 'An unsupported old guess.'},
                {'role': 'user', 'content': attachments.prompt_content(text, [image('blue')])}])
            for phrase in ('functional parts', 'Printed artwork', 'supporting evidence', 'Separate observations',
                           'ambiguous', 'only when needed', 'Current visual evidence', 'corrections against visible evidence',
                           'proportionate detail', 'never instructions'):
                self.assertIn(phrase, instruction)

    def test_http_upload_reaches_native_luna_as_pixels_not_text_only(self):
        from kilas_ai import visual_grounding
        sample = image('purple', 'synthetic-upload.png')
        reply = MagicMock();reply.status_code = 200;reply.__enter__.return_value = reply
        events = [{'model': chat_offering.CHAT_MODEL, 'choices': [{'delta': {'content':
            'This synthetic answer describes only the fixture. Its visible outline is rectangular; no brand or capacity is inferred.'}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 30}}]
        for agent in (False, True):
            with self.subTest(agent=agent), patch.dict(os.environ, {'OPENAI_API_KEY': 'synthetic-only'}), \
                 patch.object(selected_provider.requests, 'post', return_value=reply) as post, \
                 patch.object(providers, '_events', side_effect=lambda response: iter(events)):
                result = self.submit(agent=agent, text='Identify this object.',
                    **{('source_files' if agent else 'attachments'): [(io.BytesIO(sample['content']), sample['filename'])]})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(post.call_count, 1)
            payload = post.call_args.kwargs['json']
            self.assertEqual(payload['model'], chat_offering.CHAT_MODEL)
            self.assertEqual(image_bytes(payload['messages'][-1]['content']), [sample['content']])
            self.assertIn(visual_grounding.GUIDANCE, payload['messages'][0]['content'])

    def test_agent_short_caption_followup_reuses_nearest_actual_image_turn(self):
        sample = image('blue')
        agent_store.append(self.owner, 'user', 'What is this?', self.conversation, attachments=[sample])
        agent_store.append(self.owner, 'assistant', 'An unsupported old description.', self.conversation)
        context = self.agent_context('Which part is on the right?')
        self.assertEqual(context.selected_model, chat_offering.CHAT_MODEL)
        self.assertEqual(image_bytes(context[-1]['content']), [sample['content']])

    def test_agent_new_upload_wins_and_intervening_text_does_not_revive_stale_pixels(self):
        old, new = image('blue'), image('green')
        agent_store.append(self.owner, 'user', 'What is this?', self.conversation, attachments=[old])
        context = self.agent_context('Identify this object.', [new])
        self.assertEqual(image_bytes(context[-1]['content']), [new['content']])
        agent_store.append(self.owner, 'user', 'The budget is 500 units.', self.conversation)
        self.assertEqual(image_bytes(self.agent_context('What about that?')[-1]['content']), [])

    def test_agent_other_conversation_never_supplies_pixels(self):
        other = agent_store.new_conversation(self.owner)
        agent_store.append(self.owner, 'user', 'What is this?', other, attachments=[image('red')])
        self.assertEqual(image_bytes(self.agent_context('Which part is on the right?')[-1]['content']), [])

    def test_thread_short_caption_followup_and_new_upload_selection(self):
        old, new = image('blue'), image('green')
        ident, _ = store.append_user_once(self.owner, self.thread, 'What is this?', 'SMART', 'visual_initial_turn')
        store.save_attachments(self.owner, self.thread, ident, [old])
        store.append_assistant(self.owner, self.thread, 'An unsupported old description.', 'SMART', 'openai', chat_offering.CHAT_MODEL, 'visual_old_guess', {})
        store.append_user_once(self.owner, self.thread, 'Which part is on the right?', 'SMART', 'visual_next_turn')
        context = store.context(self.owner, self.thread, selected_model=chat_offering.CHAT_MODEL)
        self.assertEqual(image_bytes(context[-1]['content']), [old['content']])
        context = store.context(self.owner, self.thread, selected_model=chat_offering.CHAT_MODEL, current_attachments=[new])
        self.assertEqual(image_bytes(context[-1]['content']), [new['content']])
        store.append_user_once(self.owner, self.thread, 'The budget is 500 units.', 'SMART', 'visual_intervening_turn')
        store.append_user_once(self.owner, self.thread, 'What about that?', 'SMART', 'visual_last_turn')
        self.assertEqual(image_bytes(store.context(self.owner, self.thread, selected_model=chat_offering.CHAT_MODEL)[-1]['content']), [])

    def test_agent_continuous_referential_chain_keeps_active_pixels_and_stops_at_text(self):
        old, fresh = image('blue'), image('green')
        agent_store.append(self.owner, 'user', 'What is this?', self.conversation, attachments=[old])
        for text in ('Which part is on the right?', 'What color is that?', 'And the left side?'):
            context = self.agent_context(text)
            self.assertTrue(image_bytes(context[-1]['content']) == [old['content']], text)
        self.assertEqual(image_bytes(self.agent_context('Identify this object.', [fresh])[-1]['content']), [fresh['content']])
        self.assertEqual(image_bytes(self.agent_context('What color is that?')[-1]['content']), [fresh['content']])
        self.assertEqual(image_bytes(self.agent_context('And the left side?')[-1]['content']), [fresh['content']])
        agent_store.append(self.owner, 'user', 'The budget is 500 units.', self.conversation)
        self.assertEqual(image_bytes(self.agent_context('What color is that?')[-1]['content']), [])

    def test_thread_continuous_referential_chain_keeps_active_pixels_and_stops_at_text(self):
        sample = image('blue')
        ident, _ = store.append_user_once(self.owner, self.thread, 'What is this?', 'SMART', 'chain_source')
        store.save_attachments(self.owner, self.thread, ident, [sample])
        for i, text in enumerate(('Which part is on the right?', 'What color is that?', 'And the left side?')):
            store.append_user_once(self.owner, self.thread, text, 'SMART', 'chain_followup_'+str(i))
            context = store.context(self.owner, self.thread, selected_model=chat_offering.CHAT_MODEL)
            self.assertTrue(image_bytes(context[-1]['content']) == [sample['content']], text)
        fresh = image('green')
        ident, _ = store.append_user_once(self.owner, self.thread, 'What is this?', 'SMART', 'chain_new_upload')
        store.save_attachments(self.owner, self.thread, ident, [fresh])
        store.append_user_once(self.owner, self.thread, 'What color is that?', 'SMART', 'chain_after_upload')
        self.assertEqual(image_bytes(store.context(self.owner, self.thread, selected_model=chat_offering.CHAT_MODEL)[-1]['content']), [fresh['content']])
        store.append_user_once(self.owner, self.thread, 'The budget is 500 units.', 'SMART', 'chain_budget')
        store.append_user_once(self.owner, self.thread, 'What color is that?', 'SMART', 'chain_after_budget')
        self.assertEqual(image_bytes(store.context(self.owner, self.thread, selected_model=chat_offering.CHAT_MODEL)[-1]['content']), [])

    def test_old_visual_caption_does_not_override_unrelated_text_or_nonvisual_upload(self):
        sample = image('blue')
        agent_store.append(self.owner, 'user', 'Describe this image.', self.conversation, attachments=[sample])
        agent_store.append(self.owner, 'user', 'The budget is 500 units.', self.conversation)
        self.assertEqual(image_bytes(self.agent_context('What color is that?')[-1]['content']), [])
        rows = [{'id': 1, 'content': 'What is this?'}, {'id': 2, 'content': 'Which part is on the right?'},
                {'id': 3, 'content': 'What is this?'}]
        metadata = {1: [{'mime_type': 'image/png'}], 3: [{'mime_type': 'text/plain'}]}
        self.assertIsNone(conversation_context.active_visual_turn('What color is that?', rows, metadata))
        self.assertIsNone(conversation_context.active_visual_turn('What color is that?',
            [{'id': i, 'content': 'Which part is on the right?'} for i in range(2, 11)], {1: [{'mime_type': 'image/png'}]}))


if __name__ == '__main__':
    unittest.main()
