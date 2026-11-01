"""Synthetic Gunicorn fixture for audit concurrency regression, never production."""
import json,os,time
from pathlib import Path
from unittest.mock import patch
import test_kilas_chat_models as fixture
from kilas_ai import providers,store
case=fixture.RouteTests();case.id=lambda:'threaded-chat-http';case.setUp()
out=Path(os.environ['KILAS_CHAT_HTTP_FIXTURE']);out.mkdir(parents=True,exist_ok=True)
def answer(mode,messages,**kwargs):
    yield {'type':'provider','provider':'openai','model':messages.selected_model}
    yield {'type':'delta','text':'Synthetic start. '}
    (out/'entered').write_text('1')
    time.sleep(1.5)
    yield {'type':'delta','text':'Complete.'}
    yield {'type':'usage','input_tokens':40,'output_tokens':15}
    yield {'type':'finish','reason':'stop'}
patch.object(providers,'stream',side_effect=answer).start()
client=case.client();other_client=case.client(case.other)
(out/'ready.json').write_text(json.dumps({'cookie':client.get_cookie('session').value,'thread':case.thread,
    'other_cookie':other_client.get_cookie('session').value,'other_thread':store.create_thread(case.other)}))
application=client.application
