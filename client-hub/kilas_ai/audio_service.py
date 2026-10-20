"""One logical provider submission; polling resumes persisted Dubbing jobs only."""
import math
from datetime import timedelta
from . import audio_store as store, audio_provider as provider, audio_media as media, usage
from . import audio_transcription_provider as stt, audio_transcription_budget as budget, free_test


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
        with store.locked(user) as conn:
            sponsored=free_test.sponsored_audio(conn,user,ident)
        if sponsored:stt.require_subscription_credit()
        if job['mode']=='translate':
            ident_provider=provider.dub(bytes(payload['source_content']),job['source_language'],job['target_language'],ident)
            store.submitted(user,ident,ident_provider,retain_video=bytes(payload['source_content'])[4:8]==b'ftyp')
        else:
            from . import audio_personal_voice as personal
            transient=store.is_session_output(user,ident)
            if transient:
                from . import live_translator_output as temporary
                entry=temporary.job(user,ident)
                if not entry:raise store.AudioError('Hasil sementara sesi tidak tersedia.','session_output_expired',409)
                payload={'script':entry['text']}
            options={'personal':True} if job['voice_name']=='Suara Saya' or personal.owns(user,job['voice_id']) else {}
            if job['alternate_of'] is not None:options['alternate_stability']=job['delivery_stability']
            if transient:options={'translator':True}
            raw,request_id=provider.speech(payload['script'],job['voice_id'],job['target_language'],**options)
            store.finish(user,ident,raw,media.mp3_duration(raw),request_id)
            if transient:temporary.update(user,ident,raw=raw)
    except (provider.ProviderError,media.MediaError,store.AudioError,budget.BudgetError) as error:
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
            v2=job['provider_id'].startswith('proj_')
            metadata=provider.dub_status(job['provider_id'],job['target_language']) if v2 else provider.dub_status(job['provider_id'])
            status=metadata['status']
            if status in ('dubbed','completed'):
                output=provider.dub_result(job['provider_id'],job['target_language'],metadata.get('outputs')) if v2 else provider.dub_result(job['provider_id'],job['target_language'])
                source=store.payload(user,ident)['source_content']
                if source and bytes(source)[4:8]==b'ftyp':
                    raw=media.mux_video(bytes(source),output);ms=job['source_ms']
                else:raw,ms=media.ensure_mp3(output)
                detected=metadata.get('source_language')
                from .translator_languages import STT,DUBBING
                if job['source_language']=='auto' and detected in STT|DUBBING:
                    store.detected_source(user,ident,detected)
                store.finish(user,ident,raw,ms)
            elif status=='failed':store.fail(user,ident,'provider_failed')
        except provider.ProviderError as error:
            if error.code=='voice_preservation_unavailable':store.fail(user,ident,error.code)
            # Read-only transient poll failures never trigger another paid submission.
        except (media.MediaError,store.AudioError) as error:
            store.fail(user,ident,getattr(error,'code','invalid_audio'))
        finally:store.poll_release(user,ident)
    return store.get(user,ident)
