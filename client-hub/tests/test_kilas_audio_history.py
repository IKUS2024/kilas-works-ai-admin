"""Private four-item Recent pages; disposable records and no provider requests."""
import unittest
from unittest.mock import patch
import test_kilas_audio as audio
from test_kilas_audio import f,store,provider


class AudioHistoryTests(unittest.TestCase):
    setUp=audio.AudioTests.setUp

    def seed(self,count,owner=None):
        owner=owner or self.user;ids=[]
        for _ in range(count):
            self.number=getattr(self,'number',0)+1
            key='history-fixture-'+str(self.number)
            f.db.execute("INSERT INTO kilas_audio_jobs(user_id,operation_key,fingerprint,mode,title,source_language,target_language,voice_name,estimated_seconds,reserved_seconds,status,actual_ms,original_script,created_at,updated_at) VALUES (?,?,?,'voiceover',?,'id','en','QA voice',2,0,'COMPLETED',1600,?,'2026-10-15T00:00:00+00:00','2026-10-15T00:00:00+00:00')",(owner,key,'synthetic',f'History {self.number}','Original script' if self.number%2 else None))
            ids.append(f.db.query_one('SELECT id FROM kilas_audio_jobs WHERE user_id=? AND operation_key=?',(owner,key))['id'])
        return ids

    def test_zero_four_five_nine_and_identical_timestamp_order(self):
        self.seed(5,self.other)
        for amount,pages in ((0,0),(4,1),(5,2),(9,3)):
            with self.subTest(amount=amount):
                current=store.history_page(self.user)['history_total']
                self.seed(amount-current)
                data=store.history_page(self.user)
                self.assertEqual(data['history_total'],amount)
                self.assertEqual(data['history_page_count'],pages)
                self.assertEqual(len(data['history']),min(4,amount))
                ids=[row['id'] for row in data['history']]
                self.assertEqual(ids,sorted(ids,reverse=True))
                body=self.client.get('/kilas-translator/history').json
                self.assertEqual(body['html'].count('data-audio-history="'),min(4,amount))
                self.assertEqual('aria-label="Halaman riwayat"' in body['html'],amount>4)
                if amount==9:
                    for number in (1,2,3):self.assertIn(f'data-audio-history-page="{number}"',body['html'])

    def test_snapshot_pages_preserve_every_record_and_bound_page_numbers(self):
        ids=self.seed(9);first=store.history_page(self.user)
        self.seed(1)  # A new result while browsing cannot shift the older snapshot.
        found=[]
        for page,length in ((1,4),(2,4),(3,1)):
            data=store.history_page(self.user,page,through=first['history_anchor'])
            self.assertEqual(data['history_total'],9)
            self.assertEqual(len(data['history']),length)
            found.extend(row['id'] for row in data['history'])
        self.assertEqual(found,list(reversed(ids)))
        self.assertEqual(store.history_page(self.user,-5)['history_page'],1)
        self.assertEqual(store.history_page(self.user,10**30)['history_page'],3)
        self.assertEqual(len(store.history_page(self.user)['history']),4)

    def test_fragment_is_private_read_only_and_keeps_item_actions(self):
        own=self.seed(5);foreign=self.seed(1,self.other)[0]
        with patch.object(provider,'request',side_effect=AssertionError('No provider IO')),patch.object(store,'balance',side_effect=AssertionError('No billing path')):
            response=self.client.get(f'/kilas-translator/history?selected={own[-1]}')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.headers['Cache-Control'],'private, no-store')
        html=response.json['html']
        self.assertNotIn('data-audio-history="'+str(foreign)+'"',html)
        self.assertIn('aria-current=page',html)
        self.assertIn('data-audio-edit=',html)
        self.assertIn('data-audio-reconstruct=',html)
        self.assertIn('aria-current="page" disabled',html)
        self.assertNotIn('id="audio-script"',html)
        self.assertNotIn('<script',html)
        self.assertNotEqual(f.app.app.test_client().get('/kilas-translator/history').status_code,200)
        self.assertEqual(store.history_page(self.user)['history_total'],5)

    def test_invalid_parameters_and_full_page_use_the_same_four_item_partial(self):
        self.seed(9)
        for query in ('page=abc','through=-1','through=9223372036854775808','selected=abc'):
            self.assertEqual(self.client.get('/kilas-translator/history?'+query).status_code,400)
        response=self.client.get('/kilas-translator?mode=voiceover&page=999999')
        self.assertEqual(response.status_code,200)
        self.assertIn('data-page="3" data-pages="3"',response.text)
        self.assertEqual(response.text.count('data-audio-history="'),1)
        self.assertIn('kilas_audio_history.js',response.text)


if __name__=='__main__':unittest.main()
