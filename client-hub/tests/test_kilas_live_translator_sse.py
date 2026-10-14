"""Actual Requests/urllib3 SSE buffering over a local pipe; no network or paid IO."""
import json
import os
import sys
import unittest
from pathlib import Path
from threading import Event,Thread
from unittest.mock import patch
import requests
from urllib3.response import HTTPResponse

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from kilas_ai import providers,model_policy


class SSETests(unittest.TestCase):
    def frames(self,value):return ('data: '+json.dumps(value,ensure_ascii=False)+'\n\n').encode()

    def streamed(self,chunk_size,encoding='utf-8'):
        # The provider has sent one complete frame, but not enough bytes to fill
        # the default Requests chunk. Hold the rest of the same request open.
        fragment='Repeated words. '
        first=self.frames({'choices':[{'delta':{'content':fragment},'finish_reason':None}]})
        last='Repeated words. 最后一句 كاملة.'
        tail=self.frames({'choices':[{'delta':{'content':last},'finish_reason':None}]})
        tail+=self.frames({'choices':[{'delta':{},'finish_reason':'stop'}]})
        tail+=self.frames({'usage':{'prompt_tokens':8,'completion_tokens':17}})+b'data: [DONE]\n\n'
        self.assertLess(len(first),512)
        read_fd,write_fd=os.pipe();body=os.fdopen(read_fd,'rb',buffering=0)
        response=requests.Response();response.status_code=200;response.encoding=encoding
        response.raw=HTTPResponse(body=body,preload_content=False)
        received=Event();events=[];errors=[]
        def consume():
            try:
                options={} if chunk_size is None else {'event_chunk_size':chunk_size}
                for event in providers._openai(model_policy.LUNA,'synthetic-only',[{'role':'user','content':'Synthetic source'}],'FAST',**options):
                    events.append(event)
                    if event['type']=='delta':received.set()
            except BaseException as error:errors.append(error)
        worker=Thread(target=consume,daemon=True)
        try:
            with patch.object(providers.requests,'post',return_value=response) as request:
                worker.start();os.write(write_fd,first)
                early=received.wait(.2)
                os.write(write_fd,tail);os.close(write_fd);write_fd=None
                worker.join(2);self.assertFalse(worker.is_alive());self.assertEqual(errors,[])
                request.assert_called_once()
                self.assertEqual(''.join(event['text'] for event in events if event['type']=='delta'),fragment+last)
                self.assertEqual([event for event in events if event['type']=='finish'],[{'type':'finish','reason':'stop'}])
                self.assertEqual([event for event in events if event['type']=='usage'],[{'type':'usage','input_tokens':8,'output_tokens':17,'cached_input_tokens':0}])
                self.assertTrue(response.raw.closed)
            return early
        finally:
            if write_fd is not None:os.close(write_fd)
            worker.join(2);response.close()

    def test_default_shared_chat_buffer_keeps_existing_512_byte_behavior(self):
        self.assertFalse(self.streamed(None))

    def test_translator_opt_in_receives_complete_sse_frame_before_delayed_tail(self):
        self.assertTrue(self.streamed(1))

    def test_translator_one_byte_utf8_boundaries_override_requests_no_charset_text_default(self):
        # Each Chinese/Arabic code point spans multiple one-byte reads. Requests
        # otherwise guesses Latin-1 for text/event-stream without a charset.
        self.assertTrue(self.streamed(1,'ISO-8859-1'))


if __name__=='__main__':unittest.main()
