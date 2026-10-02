"""Customer Work orchestration on existing fenced jobs, conversation and event stores."""
import json
import re
import db
from flask import request, session, redirect, url_for
from . import autonomous_store as store, agent_store, automation_store, work_schedule, usage

LABELS={'CONDITION_MET':'Kondisi terpantau terpenuhi.','CREATED':'Pekerjaan tersimpan','PLANNED':'Memahami permintaan…','EXECUTING':'Sedang mengerjakan…','ACCEPTED':'Pekerjaan tersimpan','PLANNING':'Memahami permintaan…','WORKING':'Sedang mengerjakan…','SEARCHING':'Mencari sumber…','WRITING':'Menulis isi…','CREATING_FILE':'Membuat file…','VERIFYING':'Memeriksa hasil…','WAITING_INPUT':'Menunggu jawabanmu','SCHEDULED':'Terjadwal','COMPLETED':'Selesai','FAILED':'Perlu perhatian','STOP':'Dihentikan','STOPPED':'Dihentikan','WAITING_CAPABILITY':'Kemampuan belum tersedia','SUCCEEDED':'Langkah selesai','BLOCKED':'Perlu perhatian','PAUSE':'Dijeda','RESUME':'Dilanjutkan','FEEDBACK':'Instruksi diperbarui','REMINDER':'Pengingat'}


def progress(job,kind,label):
    if kind not in LABELS:raise ValueError('invalid_progress')
    with store.transaction() as conn:
        if store.locked(conn,job['id'],job['lease_token'],job['revision']):
            store.event(conn,job['id'],kind,label,unread=False)


def remind_plan(job):
    config=json.loads(job.get('checkpoint_json') or '{}').get('reminder')
    if not config:return None
    return {'objective':config['subject'],'mode':job['mode'],'stop_condition':'Reminder persisted','next_action':'Deliver reminder','steps':[{'worker':'REMINDER','action':'deliver','instruction':'Mengirim pengingat di Work','input_json':json.dumps({'subject':config['subject']}),'completion_criteria':'Durable conversation message','requires_approval':False}]}


def deliver_reminder(conn,job,step):
    config=json.loads(job['checkpoint_json'])['reminder']
    text='Pengingat: '+config['subject']
    key=f"reminder-{job['id']}-{job['cycle']}"
    event=usage._query(conn,'INSERT INTO kilas_agent_events(job_id,kind,summary,event_key,unread,created_at) VALUES (?,?,?,?,1,?) ON CONFLICT(event_key) DO NOTHING RETURNING id',(job['id'],'REMINDER',text,key,store.stamp()),one=True)
    if not event:return
    usage._query(conn,"INSERT INTO kilas_ai_agent_messages(user_id,conversation_id,role,content) VALUES (?,?,'assistant',?)",(job['user_id'],job['origin_conversation_id'],text))
    from . import work_push
    work_push.queue(conn,event[0],job['user_id'])
    checkpoint=json.loads(job['checkpoint_json']);checkpoint['reminder']['scheduled_for']=job['next_wake_at'];checkpoint['reminder']['actual_delivery_time']=store.stamp()
    job['checkpoint_json']=store.encode(checkpoint)
    usage._query(conn,'UPDATE kilas_agent_jobs SET checkpoint_json=? WHERE id=?',(store.encode(checkpoint),job['id']))


def persist_question(conn,job,step,question):
    key=f"waiting-{step['id']}-{job['revision']}"
    event=usage._query(conn,'INSERT INTO kilas_agent_events(job_id,kind,summary,event_key,unread,created_at) VALUES (?,?,?,?,1,?) ON CONFLICT(event_key) DO NOTHING RETURNING id',(job['id'],'WAITING_INPUT','Menunggu jawabanmu.',key,store.stamp()),one=True)
    if event and job.get('origin_conversation_id'):
        usage._query(conn,"INSERT INTO kilas_ai_agent_messages(user_id,conversation_id,role,content) VALUES (?,?,'assistant',?)",(job['user_id'],job['origin_conversation_id'],question[:500]))


def reply(owner,text,conversation):
    agent_store.append(owner,'assistant',text[:2400],conversation)
    return redirect(url_for('kilas_ai.agent_home',conversation=conversation),code=303)


def handle(owner,text,key,conversation):
    from . import autonomous_routes, autonomous_runner, agent_chat, work_documents
    zone=automation_store.setting(owner)
    if re.search(r'(?i)\b(?:jam berapa sekarang|what time is it|waktu sekarang)\b',text):
        from .agent_presentation import time_label
        return reply(owner,'Sekarang '+time_label(store.stamp(),zone)+'.',conversation)
    from .agent_intents import QUESTION
    if work_schedule.CAPABILITY.search(text) or QUESTION.search(text):
        return agent_chat.ordinary(owner,conversation,key) or redirect(url_for('kilas_ai.agent_home'),code=303)
    if re.search(r'(?i)\b(?:login|log in|klik tombol|click button|browser langsung)\b',text):
        return reply(owner,'Interaksi browser langsung belum tersedia di Work.',conversation)
    if not work_schedule.REMINDER.search(text) and re.search(r'(?i)\b(?:kirim|send)\b.{0,80}\b(?:email|gmail|whatsapp)\b',text):
        return reply(owner,'Pengiriman pesan dari Work belum tersedia. Saya bisa menyiapkan isi pesan jika kamu meminta drafnya.',conversation)
    nearby=bool(re.search(r'(?i)\b(?:dekat sini|lokasi saya|near me|nearby|tempat terdekat)\b',text))
    location=getattr(request,'work_location',None)
    if nearby and not location:
        session['work_location_request']={'conversation':conversation,'text':text}
        return reply(owner,'Izinkan lokasi untuk pekerjaan ini, atau sebutkan daerah yang ingin dicari.',conversation)
    pending_location=session.get('work_location_request')
    if not nearby and pending_location and pending_location['conversation']==conversation:
        text=('Riset sumber publik untuk: '+pending_location['text']+'\nDaerah yang diberikan customer: '+text)[:1200]
        session.pop('work_location_request',None)
    if nearby:
        session.pop('work_location_request',None)
        # Coordinates are a bounded, permission-based source for this request only.
        text=('Riset sumber publik untuk: '+text+f"\nLokasi yang diberikan untuk tugas ini: {location['latitude']}, {location['longitude']}; akurasi {location['accuracy']} meter.")[:1200]
    from . import agent_intents
    if re.search(r'(?i)\b(?:pekerjaan|task|tugas)\s*#?\d+\b',text) or agent_intents.FEEDBACK.search(text):
        if autonomous_routes.chat(owner,text):return redirect(url_for('kilas_ai.agent_home',conversation=conversation),code=303)
    if session.get('autonomous_job_id') and agent_intents.CONTROL.fullmatch(text.strip()):
        if autonomous_routes.chat(owner,text):return redirect(url_for('kilas_ai.agent_home',conversation=conversation),code=303)
    active=store.list_jobs(owner,conversation_id=conversation,active_only=True)
    waiting=[j for j in active if j['last_error']=='waiting_input']
    if waiting and not re.search(r'(?i)^(?:buat(?:kan)?|bikin(?:kan)?|siapkan|susun|tulis|riset|pantau|ingatkan|stop|jeda|lanjut)\b',text):
        if len(waiting)!=1:return reply(owner,'Pekerjaan mana yang ingin kamu lanjutkan? Buka pekerjaan lalu balas dari sana.',conversation)
        try:store.feedback(owner,waiting[0]['id'],text)
        except ValueError:return reply(owner,'Batas revisi pekerjaan ini sudah tercapai. Buat pekerjaan baru untuk melanjutkan.',conversation)
        return reply(owner,'Jawabanmu tersimpan. Kilas melanjutkan pekerjaan yang sama.',conversation)
    if re.search(r'(?i)^(?:batalin|batalkan|stop|hentikan|jeda|lanjutkan|lanjut|resume)\b',text):
        candidates=[j for j in active if ('reminder' not in text.lower() or json.loads(j['checkpoint_json']).get('reminder'))]
        if len(candidates)==1:
            action='resume' if re.match(r'(?i)^(lanjut|resume)',text) else 'pause' if text.lower().startswith('jeda') else 'stop'
            store.control(owner,candidates[0]['id'],action)
            return reply(owner,{'resume':'Pekerjaan dilanjutkan.','pause':'Pekerjaan dijeda.','stop':'Pekerjaan dibatalkan.'}[action],conversation)
        return reply(owner,'Pilih pekerjaan yang ingin diubah agar instruksinya tepat.',conversation)
    pending=session.get('work_reminder_pending')
    if pending and pending['conversation']==conversation and store.now().timestamp()-pending['created']<1800:
        text=(pending['text']+' '+text)[:1200]
        session.pop('work_reminder_pending',None)
    reminder=bool(work_schedule.REMINDER.search(text))
    from .agent_workers import market_request
    if not reminder and market_request(text):
        if autonomous_routes.chat(owner,text):return redirect(url_for('kilas_ai.agent_home',conversation=conversation),code=303)
    from .agent_planner import required_connection
    if not reminder and required_connection(text):return reply(owner,'Work tidak mengakses koneksi akun. Saya bisa menyiapkan dokumen atau isi draf dari informasi yang kamu berikan.',conversation)
    scheduled=reminder or bool(re.search(r'(?i)\b(?:setiap|tiap|every|besok|tomorrow|tanggal|next monday)\b',text))
    editing=bool(re.match(r'(?i)^(?:ubah|ganti|ulang|jangan tiap hari)',text)) and bool(active)
    if scheduled or editing:
        try:
            if editing:
                targets=[j for j in active if json.loads(j['checkpoint_json']).get('reminder')]
                if len(targets)!=1:return reply(owner,'Pilih pengingat yang ingin diubah.',conversation)
                prior=targets[0]
                if 'jangan tiap hari' in text.lower():
                    return reply(owner,'Sebutkan jadwal penggantinya, atau batalkan pengingat.',conversation)
                old_subject=json.loads(prior['checkpoint_json'])['reminder']['subject']
                if re.match(r'(?i)^ulang\b',text):
                    old_schedule=json.loads(prior['schedule_json'])['schedule']
                    clock=f" jam {old_schedule.get('hour',9)}:{old_schedule.get('minute',0):02d}"
                    text='ingatkan '+text+clock+' '+old_subject
                if re.search(r'(?i)jadi jam|jadi pukul',text):
                    from .agent_presentation import time_label
                    local=usage._as_utc(prior['next_wake_at']).astimezone(work_schedule.calendar.ZoneInfo(zone))
                    text=f"ingatkan tanggal {local.day}/{local.month}/{local.year} "+re.sub(r'(?i)^.*?jadi\s+','',text)+' '+json.loads(prior['checkpoint_json'])['reminder']['subject']
            spec=work_schedule.parse(text,zone)
            subject=work_schedule.subject(text) if reminder or editing else text
            if not subject:
                session['work_reminder_pending']={'text':text,'conversation':conversation,'created':store.now().timestamp()}
                return reply(owner,'Apa yang perlu aku ingatkan?',conversation)
            if not autonomous_runner.enabled():return reply(owner,'Pekerjaan terjadwal belum tersedia sekarang.',conversation)
            mode='SCHEDULED' if spec['schedule']['kind']=='once' else 'RECURRING'
            calendar={'timezone':spec['timezone'],'schedule':spec['schedule']}
            checkpoint={'reminder':{'subject':subject}} if reminder or editing else {'source_materials':getattr(request,'work_source_materials',[])}
            if editing:
                with store.transaction() as conn:
                    usage._query(conn,'UPDATE kilas_agent_jobs SET schedule_json=?,checkpoint_json=?,next_wake_at=?,mode=?,revision=revision+1,status=\'PLANNING\',plan_json=\'{}\' WHERE id=? AND user_id=?',(store.encode(calendar),store.encode(checkpoint),store.stamp(spec['next_run_at']),mode,prior['id'],owner))
                    store.event(conn,prior['id'],'SCHEDULED','Jadwal diperbarui.')
            else:
                job=store.create(owner,text,mode=mode,wake_at=spec['next_run_at'],conversation_id=conversation,schedule=calendar,checkpoint=checkpoint)
                db.execute('UPDATE kilas_agent_jobs SET title=? WHERE id=?',(subject[:90],job))
                with store.transaction() as conn:store.event(conn,job,'SCHEDULED','Pengingat tersimpan.' if reminder else 'Pekerjaan terjadwal tersimpan.')
            from .agent_presentation import time_label
            from .work_push import configured
            return reply(owner,'Siap. '+('Aku ingatkan ' if reminder or editing else 'Pekerjaan dijadwalkan ')+time_label(spec['next_run_at'],spec['timezone'])+' untuk '+subject+'.'+(' Notifikasi perangkat belum aktif. Pengingat tetap tersimpan di Work.' if reminder and not configured() else ''),conversation)
        except (ValueError,TypeError):return reply(owner,'Tanggal atau jam belum jelas. Sebutkan waktu yang akan datang, misalnya besok jam 8.',conversation)
    pending_document=session.pop('work_document_pending',None)
    if pending_document and pending_document['conversation']==conversation and store.now().timestamp()-pending_document['created']<1800:
        text=(pending_document['text']+' tentang '+text)[:1200]
    if re.fullmatch(r'(?i)(?:tolong )?(?:buat(?:kan)?|bikin(?:kan)?|siapkan) (?:sebuah )?(?:pdf|dokumen|document|docx|xlsx|pptx)[.! ]*',text):
        session['work_document_pending']={'text':text,'conversation':conversation,'created':store.now().timestamp()}
        return reply(owner,'Dokumen ini tentang apa dan untuk siapa?',conversation)
    if autonomous_routes.chat(owner,text):return redirect(url_for('kilas_ai.agent_home',conversation=conversation),code=303)
    return agent_chat.ordinary(owner,conversation,key) or redirect(url_for('kilas_ai.agent_home'),code=303)
