import unittest, base64, io, json, os
from unittest.mock import patch, MagicMock
from PIL import Image
import context_engine as context

class ContextTests(unittest.TestCase):
    def test_recent_relevant_deterministic_and_unmodified(self):
        history=[{'role':'user' if i%2==0 else 'assistant','content':f'topic{i} details {i}'} for i in range(20)]
        history[1]['content']='pesanan khusus anggrek disetujui owner'
        original=json.dumps(history)
        compact=context.compact_history(history,'anggrek')
        self.assertEqual(compact,[history[1]]+history[-8:])
        self.assertEqual(original,json.dumps(history))
        self.assertEqual(compact,context.compact_history(history,'anggrek'))

    def test_bounded_old_relevance_and_dedup(self):
        history=[{'role':'user','content':f'anggrek {i}'} for i in range(20)]
        history[-2]=dict(history[-1])
        selected=context.compact_history(history,'anggrek')
        self.assertLessEqual(len(selected),12)
        self.assertEqual(len({m['content'] for m in selected}),len(selected))
        self.assertEqual(selected[-1],history[-1])

    def test_vision_size_orientation_and_original_unchanged(self):
        image=Image.new('RGB',(3000,4000),'white');exif=image.getexif();exif[274]=6
        raw=io.BytesIO();image.save(raw,format='JPEG',exif=exif)
        encoded=base64.b64encode(raw.getvalue()).decode();before=encoded
        result,mime=context.prepare_vision_image(encoded,'image/jpeg')
        im=Image.open(io.BytesIO(base64.b64decode(result)))
        self.assertEqual(im.size,(2048,1536));self.assertEqual(mime,'image/png');self.assertEqual(encoded,before)

    def test_small_receipt_not_upscaled(self):
        image=Image.new('L',(500,900),'white');raw=io.BytesIO();image.save(raw,format='PNG')
        encoded,mime=context.prepare_vision_image(base64.b64encode(raw.getvalue()).decode(),'image/png')
        self.assertEqual(Image.open(io.BytesIO(base64.b64decode(encoded))).size,(500,900))

    def test_large_photo_stays_below_provider_byte_limit(self):
        import random
        image=Image.frombytes('RGB',(2048,2048),random.Random(1).randbytes(2048*2048*3))
        raw=io.BytesIO();image.save(raw,format='PNG')
        self.assertGreater(len(raw.getvalue()),5_000_000)
        encoded,mime=context.prepare_vision_image(base64.b64encode(raw.getvalue()).decode(),'image/png')
        self.assertEqual(mime,'image/jpeg')
        self.assertLess(len(base64.b64decode(encoded)),4_500_000)
        self.assertEqual(Image.open(io.BytesIO(base64.b64decode(encoded))).size,(2048,2048))

    def test_invalid_image_fails_before_provider(self):
        with self.assertRaises(Exception): context.prepare_vision_image('not-an-image','image/jpeg')

    def test_compact_payload_in_all_three_paths(self):
        import inspect, _test_bootstrap
        import app
        for fn in (app.call_claude,app.call_claude_owner,app.call_tenant_owner_ai):
            source=inspect.getsource(fn)
            self.assertIn('_ctx.compact_history',source)
            self.assertNotIn('"messages": history',source)
            self.assertIn('_ctx.prepare_vision_image',source)
        self.assertEqual(app.MODEL_FAST,'claude-haiku-4-5-20251001')
        self.assertEqual(app.MODEL_PRIMARY,'claude-sonnet-4-6')
        self.assertEqual(list(app.PRICING_CONFIG['ai_admin']),['current'])
        self.assertEqual(app.PRICING_CONFIG['ai_admin']['current']['harga'],499000)

    def test_repeatable_prompt_size_fixture(self):
        import _test_bootstrap, app, catalog_service
        catalog_service.seed_catalog_if_needed()
        history=[{'role':'user' if i%2==0 else 'assistant','content':f'Catatan percakapan {i}: '+('Pembahasan topik lama yang berbeda dan tidak diperlukan untuk menjawab pertanyaan terbaru. '*4)} for i in range(20)]
        history[2]['content']='File logo disediakan dalam format SVG. Pemilik telah menyetujui penggunaan warna oranye untuk identitas usaha.'
        query='File logo perlu disiapkan dalam format apa?'
        history.append({'role':'user','content':query})
        blocks=app.build_focused_customer_prompt('628999990001',query)
        compact=context.compact_history(history,query)
        def size(messages):
            return len(json.dumps({'model':app.MODEL_FAST,'max_tokens':400,'system':blocks,'messages':messages},ensure_ascii=False))
        self.assertEqual(len(compact),9)
        self.assertTrue(any('SVG' in m['content'] for m in compact))
        self.assertLess(size(compact),size(history)*.8)
        print('PROMPT_SIZE_FIXTURE',json.dumps(dict(before_chars=size(history),after_chars=size(compact),reduction_percent=round(100*(1-size(compact)/size(history)),2))))

    def test_normal_customer_one_call_compact_history_and_usage_failure(self):
        import _test_bootstrap, app
        number='628999999100'
        original=[{'role':'user' if i%2==0 else 'assistant','content':f'Percakapan topik{i}'} for i in range(20)]
        app.conversations[number]=list(original)
        response=MagicMock();response.json.return_value={'content':[{'text':'Jawaban singkat'}],'usage':{'input_tokens':10,'output_tokens':3}}
        with patch.object(app.requests,'post',return_value=response) as calls,patch('ai_usage._insert',side_effect=RuntimeError('failure')):
            result=app.call_claude(number,'Butuh ide kampanye untuk usaha yang baru berjalan')
        self.assertEqual(calls.call_count,1)
        payload=calls.call_args.kwargs['json'];self.assertLessEqual(len(payload['messages']),12)
        self.assertEqual(payload['model'],app.MODEL_FAST)
        self.assertLessEqual(payload['max_tokens'],400)
        self.assertIn('Jawaban singkat',result)
        self.assertEqual(len(original),20)

if __name__=='__main__': unittest.main()
