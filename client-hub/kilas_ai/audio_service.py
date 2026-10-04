"""One logical provider submission; polling resumes persisted Dubbing jobs only."""
import math
from datetime import timedelta
from . import audio_store as store, audio_provider as provider, audio_media as media, usage


def estimate(script):
    # UI estimate only; pessimistic headroom reservation caps releasable paid output.
    words=len(script.split());chars=len(script)
    expected=max(1,math.ceil(max(words/2.3,chars/13)))
    ceiling=math.ceil(max(words/0.8,chars/4)+10)
    return expected,min(media.duration_limit(),ceiling)


def submit(user,ident):
    if not store.start(user,ident):return
    job=store.get(user,ident);payload=store.payload(user,ident)
    try:
        if job['mode']=='translate':
            ident_provider=provider.dub(bytes(payload['source_content']),job['source_language'],job['target_language'],ident)
            store.submitted(user,ident,ident_provider)
        else:
            raw,request_id=provider.speech(payload['script'],job['voice_id'],job['target_language'])
            store.finish(user,ident,raw,media.mp3_duration(raw),request_id)
    except (provider.ProviderError,media.MediaError,store.AudioError) as error:
        store.fail(user,ident,getattr(error,'code','invalid_audio'))
    except Exception:
        store.fail(user,ident,'processing_failed')


def refresh(user,ident):
    job=store.get(user,ident)
    if not job or job['status'] not in ('QUEUED','PROCESSING'):return job
    age=usage._now()-usage._as_utc(job['created_at'])
    # Never retry a paid POST whose worker died or whose response was ambiguous.
    if not job['provider_id']:
        if age>timedelta(minutes=3):store.fail(user,ident,'submission_interrupted')
        return store.get(user,ident)
    if age>timedelta(hours=2):
        store.fail(user,ident,'provider_timeout');return store.get(user,ident)
    if job['mode']=='translate' and store.poll_claim(user,ident):
        try:
            metadata=provider.dub_status(job['provider_id'])
            status=metadata['status']
            if status=='dubbed':
                raw,ms=media.ensure_mp3(provider.dub_result(job['provider_id'],job['target_language']))
                detected=metadata.get('source_language')
                if job['source_language']=='auto' and detected in provider.LANGUAGES:
                    store.detected_source(user,ident,detected)
                store.finish(user,ident,raw,ms)
            elif status=='failed':store.fail(user,ident,'provider_failed')
        except provider.ProviderError:
            pass  # Read-only transient poll failures never trigger another paid submission.
        except (media.MediaError,store.AudioError) as error:
            store.fail(user,ident,getattr(error,'code','invalid_audio'))
        finally:store.poll_release(user,ident)
    return store.get(user,ident)
