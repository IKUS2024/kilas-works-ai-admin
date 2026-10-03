"""Explicit visual follow-up reuses only private images in the same conversation."""
import io
import os
import unittest
from unittest.mock import patch
from PIL import Image
import test_kilas_ai_unified as fixture
from kilas_ai import agent_store, agent_chat, agent_attachments


class ImageFollowupTests(unittest.TestCase):
    setUp = fixture.UnifiedTests.setUp
    client = fixture.UnifiedTests.client

    def image(self, color):
        raw = io.BytesIO()
        Image.new('RGB', (20, 20), color).save(raw, 'PNG')
        return {'filename': color+'.png', 'mime_type': 'image/png',
                'byte_size': len(raw.getvalue()), 'content': raw.getvalue()}

    def context(self, text, prepared=None):
        agent_store.append(self.owner, 'user', text, self.conversation)
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'synthetic-image-context-only'}), self.client().application.test_request_context():
            if prepared:
                from flask import request
                request.work_attachments = prepared
            return agent_chat.context(self.owner, self.conversation)[-1]['content']

    def test_followup_replays_latest_image_turn(self):
        agent_store.append(self.owner, 'user', 'first', self.conversation, attachments=[self.image('red')])
        agent_store.append(self.owner, 'user', 'second', self.conversation, attachments=[self.image('blue'), self.image('green')])
        agent_store.append(self.owner, 'assistant', 'Description', self.conversation)
        content = self.context('Di gambar tadi apa warna objeknya?')
        self.assertIsInstance(content, list)
        self.assertEqual(len(content), 3)
        self.assertEqual([r['filename'] for r in agent_attachments.latest_images(self.owner, self.conversation)], ['blue.png', 'green.png'])

    def test_owner_and_conversation_isolation(self):
        agent_store.append(self.owner, 'user', 'private', self.conversation, attachments=[self.image('red')])
        self.assertEqual(agent_attachments.latest_images(self.other, self.conversation), [])
        self.assertEqual(agent_attachments.latest_images(self.owner, agent_store.new_conversation(self.owner)), [])

    def test_unrelated_chat_does_not_replay_binary(self):
        agent_store.append(self.owner, 'user', 'photo', self.conversation, attachments=[self.image('red')])
        self.assertIsInstance(self.context('Berapa 6 kali 7?'), str)

    def test_new_upload_wins_over_previous_images(self):
        agent_store.append(self.owner, 'user', 'photo', self.conversation, attachments=[self.image('red')])
        green = self.image('green')
        content = self.context('Jelaskan gambar ini', [green])
        self.assertEqual(len(content), 2)
        import base64
        self.assertIn(base64.b64encode(green['content']).decode(), content[1]['image_url']['url'])


if __name__ == '__main__':
    unittest.main()
