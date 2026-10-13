"""One synthetic server-only supplier attempt; OS alarm precedes every import/connect."""
import signal
signal.signal(signal.SIGALRM, signal.SIG_DFL)
signal.setitimer(signal.ITIMER_REAL, 9.5)
import base64,json,math,os,struct,time
import websocket

MODEL='scribe_v2_realtime'
def emit(**value):
    print(json.dumps(value,separators=(',',':')),flush=True)

def pcm():
    # Deterministic tone, no person/voice/paid synthesis. Exactly5 seconds.
    return b''.join(struct.pack('<h',int(1200*math.sin(2*math.pi*440*i/16000))) for i in range(80000))

def run():
    ws=None
    try:
        ws=websocket.create_connection('wss://api.elevenlabs.io/v1/speech-to-text/realtime?model_id=scribe_v2_realtime&audio_format=pcm_16000&commit_strategy=manual&include_timestamps=false&include_language_detection=false&enable_logging=true&no_verbatim=false',
            header={'xi-api-key':os.environ['ELEVENLABS_API_KEY'].strip()},timeout=2,redirect_limit=0,enable_multithread=True)
        value=json.loads(ws.recv());config=value.get('config',{})
        accepted=value.get('message_type')=='session_started' and config.get('model_id')==MODEL and config.get('audio_format')=='pcm_16000' and type(config.get('sample_rate')) is int and config['sample_rate']==16000
        emit(accepted=accepted)
        if not accepted:emit(result='config_invalid');return
        raw=pcm()
        for i in range(5):
            ws.send(json.dumps({'message_type':'input_audio_chunk','audio_base_64':base64.b64encode(raw[i*32000:(i+1)*32000]).decode(),'sample_rate':16000,'commit':i==4}))
            emit(sent_pcm_ms=(i+1)*1000)
            if i<4:time.sleep(.8)
        while True:
            raw=ws.recv()
            if not isinstance(raw,str) or len(raw)>65536:emit(result='response_invalid');return
            value=json.loads(raw);kind=value.get('message_type')
            if kind=='committed_transcript':
                if not isinstance(value.get('text'),str):emit(result='response_invalid');return
                emit(result='committed',stable_characters=len(value['text']));return
            if kind not in ('partial_transcript','warning','committed_transcript_with_timestamps'):
                emit(result='provider_rejected' if isinstance(value.get('error'),str) or kind in ('rate_limited','quota_exceeded','insufficient_credits','resource_exhausted','session_time_limit_exceeded','input_error','chunk_size_exceeded','insufficient_audio_activity','unaccepted_terms','queue_overflow','transcriber_error') or isinstance(kind,str) and 'error' in kind else 'response_invalid');return
    except Exception as error:
        status=getattr(error,'status_code',None)
        emit(result='provider_http_'+str(status) if type(status) is int and status in (400,401,402,403,404,429) else 'connection_unknown')
    finally:
        if ws:
            try:ws.shutdown()
            except Exception:pass
if __name__=='__main__':run()
