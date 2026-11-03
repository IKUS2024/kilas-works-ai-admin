"""Normal New Chat/upload/send creates scoped A/B threads; local synthetic only."""
import copy
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import threading
import uuid
from unittest.mock import MagicMock, patch

from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
import test_kilas_managed_offering as fixture
from test_kilas_visual_grounding import image, image_bytes
from kilas_ai import providers, selected_provider, store, vision_experiment as experiment
import app


def main():
    out=Path(os.environ.get('KILAS_VISION_BROWSER_ARTIFACTS','/tmp/kilas-vision-experiment-browser'))
    out.mkdir(parents=True,exist_ok=True)
    case=fixture.ManagedOfferingTests();case.id=lambda:'vision-browser';case.setUp()
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    server=make_server('127.0.0.1',0,app.app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    cookie=case.client().get_cookie('session')
    now=datetime.now(timezone.utc)
    config={'owner_id':case.owner,'batch':uuid.uuid4().hex,'question':'Identify this object.',
        'starts_at':(now-timedelta(seconds=20)).isoformat().replace('+00:00','Z'),
        'expires_at':(now+timedelta(minutes=20)).isoformat().replace('+00:00','Z')}
    answer='This synthetic response verifies only the interface and transport. No real object identification or model quality is evaluated by this fixture.'
    response=MagicMock(status_code=200,headers={'x-request-id':'req_synthetic_browser'})
    response.__enter__.return_value=response
    events=[{'model':experiment.MODEL,'choices':[{'delta':{'content':answer},'finish_reason':'stop'}],
        'usage':{'prompt_tokens':100,'completion_tokens':30}}]
    records=[];report=[]
    try:
        with patch.dict(os.environ,{experiment.FLAG:json.dumps(config),'OPENAI_API_KEY':'synthetic-only'}), \
             patch.object(selected_provider.requests,'post',return_value=response) as post, \
             patch.object(providers,'_events',side_effect=lambda r,**kw:iter(events)), \
             patch.object(experiment,'_emit',side_effect=records.append),sync_playwright() as pw:
            executable='/usr/bin/chromium' if Path('/usr/bin/chromium').exists() else None
            browser=pw.chromium.launch(headless=True,args=['--no-sandbox'],**({'executable_path':executable} if executable else {}))
            for width,locale,color in ((393,'en','blue'),(393,'id','green'),(1440,'en','navy'),(1440,'id','purple')):
                ctx=browser.new_context(viewport={'width':width,'height':900},has_touch=width<900)
                ctx.add_cookies([{'name':'session','value':cookie.value,'url':origin},{'name':'kilas_language','value':locale,'url':origin}])
                ctx.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort())
                page=ctx.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(origin+'/products/start',wait_until='networkidle')
                source=image(color)
                pair=[]
                for arm in ('auto','high'):
                    expect(page.locator('[data-ai-shell]')).to_have_attribute('data-thread-id','')
                    page.locator('#ai-input').fill(config['question'])
                    page.locator('#ai-files').set_input_files({'name':'synthetic.png','mimeType':'image/png','buffer':source['content']})
                    previous_calls=post.call_count
                    page.locator('#ai-send').click()
                    expect(page.locator('#ai-send')).to_be_enabled(timeout=20000)
                    expect(page.locator('#ai-messages')).to_contain_text(answer)
                    assert post.call_count==previous_calls+1
                    payload=copy.deepcopy(post.call_args.kwargs['json'])
                    assert image_bytes(payload['messages'][-1]['content'])==[source['content']]
                    if arm=='high':assert payload['messages'][-1]['content'][1]['image_url'].pop('detail')=='high'
                    else:assert 'detail' not in payload['messages'][-1]['content'][1]['image_url']
                    pair.append(payload)
                    ident=int(page.locator('[data-ai-shell]').get_attribute('data-thread-id'))
                    rows=store.messages(case.owner,ident)
                    assert [row['role'] for row in rows]==['user','assistant']
                    assert json.loads(rows[-1]['metadata_json'])['status']=='complete'
                    page.reload(wait_until='networkidle')
                    expect(page.locator('#ai-messages')).to_contain_text(answer)
                    assert post.call_count==previous_calls+1
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    page.screenshot(path=str(out/f'{locale}-{width}-{arm}.png'),animations='disabled')
                    link=page.locator('a.ai-new').first
                    box=link.bounding_box()
                    if not box or box['x']<0 or box['x']+box['width']>width:
                        toggle=page.locator('[data-premium-menu]:visible,[data-ai-menu]:visible').first
                        toggle.click()
                    expect(link).to_be_in_viewport()
                    link.click();expect(page.locator('#ai-input')).to_have_value('')
                assert pair[0]==pair[1], 'Only detail may differ within a pair'
                assert not errors,errors
                report.append({'width':width,'locale':locale,'normal_new_chat':True,'fresh_pair':True,'only_detail_diff':True,'reload_preserved':True})
                ctx.close()
            browser.close()
            assert post.call_count==8
        requests=[record for record in records if record['event']=='request']
        assert [record['sequence'] for record in requests]==list(range(1,9))
        assert [record['arm'] for record in requests]==['auto','high']*4
        (out/'verification.json').write_text(json.dumps({'result':'PASS','cases':report,'mocked_provider_calls':8,'paid_calls':0},indent=2))
        print('PASS:4 normal-UI fresh pairs across mobile/desktop EN/ID;8 mocked calls;auto/high sequence;no direct background setup requests')
    finally:
        server.shutdown();case.doCleanups()


if __name__=='__main__':main()
