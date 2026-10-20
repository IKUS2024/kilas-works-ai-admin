"""Real private image artifact at three viewport sizes; synthetic bytes, no providers."""
import io,json,os,threading
from pathlib import Path
from PIL import Image
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
import test_kilas_selected_artifacts as fixture
from kilas_ai import agent_store,autonomous_store,work_artifacts,usage
import db


def main():
    case=fixture.SelectedArtifactTests();case.id=lambda:'image-layout';case.setUp()
    origin_message=agent_store.append(case.owner,'user','Buat poster sintetis 9:16',case.conversation)
    ident=autonomous_store.create(case.owner,'Buat poster sintetis 9:16',conversation_id=case.conversation)
    job=dict(autonomous_store.get(case.owner,ident))
    raw=io.BytesIO();Image.new('RGB',(864,1536),'#c7d8ea').save(raw,format='PNG')
    with autonomous_store.transaction() as conn:
        sid=usage._query(conn,"INSERT INTO kilas_agent_steps(job_id,sequence,worker,action,instruction,input_json,idempotency_key,status) VALUES (?,1,'IMAGE','generate','Synthetic','{}','image-layout','SUCCEEDED') RETURNING id",(ident,),one=True)[0]
        artifact=work_artifacts.persist(conn,job,{'id':sid},{'filename':'poster-sintetis.png','mime_type':'image/png','content':raw.getvalue()})
        usage._query(conn,"UPDATE kilas_agent_jobs SET status='COMPLETED' WHERE id=?",(ident,))
    app=case.client().application
    server=make_server('127.0.0.1',0,app,threaded=True);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();origin=f'http://127.0.0.1:{server.server_port}'
    output=Path(os.environ.get('KILAS_IMAGE_QA_DIR','/workspace/shared/kilas-answer-presentation-20261020'));output.mkdir(parents=True,exist_ok=True);report=[]
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox','--disable-background-networking'])
            for width in (390,820,1440):
                context=browser.new_context(viewport={'width':width,'height':900});cookie=case.client().get_cookie('session');context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}])
                context.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort())
                page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(origin+f'/kilas-ai/agent?conversation={case.conversation}',wait_until='networkidle')
                preview=page.locator('.work-image-preview img').first;expect(preview).to_be_visible();preview.scroll_into_view_if_needed()
                metrics=preview.evaluate('e=>({natural:[e.naturalWidth,e.naturalHeight],width:e.width,height:e.height,fit:getComputedStyle(e).objectFit,alt:e.alt})')
                assert metrics['natural']==[864,1536] and metrics['fit']=='contain' and metrics['alt']
                assert abs(metrics['width']/metrics['height']-864/1536)<.01
                assert not page.evaluate('document.documentElement.scrollWidth>innerWidth') and not errors
                url=preview.get_attribute('src');response=context.request.get(origin+url)
                assert response.status==200 and response.body()==raw.getvalue()
                assert case.client(case.other).get(url).status_code==404
                page.screenshot(path=str(output/f'image-agent-{width}.png'));report.append({'width':width,'natural_dimensions':metrics['natural'],'rendered':[metrics['width'],metrics['height']],'original_bytes_preserved':True,'foreign_owner_denied':True});context.close()
            browser.close()
        (output/'images.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
    finally:server.shutdown();thread.join(3);case.doCleanups()

if __name__=='__main__':main()
