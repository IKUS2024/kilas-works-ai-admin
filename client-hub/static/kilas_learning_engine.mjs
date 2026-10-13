// Bound startup stages while keeping permission consent and paid retries explicit.
export function within(task,signal,ms=30000,{setTimer=setTimeout,clearTimer=clearTimeout}={}) {
  return new Promise((resolve,reject)=>{
    let timer,settled=false;
    const finish=(value,error)=>{if(settled)return;settled=true;clearTimer(timer);signal.removeEventListener('abort',abort);error?reject(value):resolve(value);};
    const abort=()=>finish(new DOMException('Aborted','AbortError'),true);
    if(signal.aborted){abort();return;}
    signal.addEventListener('abort',abort,{once:true});
    timer=setTimer(()=>finish(Error('Persiapan terlalu lama. Periksa izin mikrofon dan koneksi, lalu coba lagi.'),true),ms);
    try{Promise.resolve(task()).then(value=>finish(value,false),error=>finish(error,true));}catch(error){finish(error,true);}
  });
}

// Learning owns its lifecycle, queue and cancellation. No Translator state is imported.
export class SilenceGate {
  constructor(now=()=>performance.now()) { this.now=now;this.spoke=false;this.last=0; }
  sample(rms) { const t=this.now();if(rms>.015){this.spoke=true;this.last=t;}return this.spoke&&t-this.last>=3000; }
}

export class LearningCall {
  constructor({api,capture,player,onState,onSettings=()=>{},save=()=>{},wait=(signal)=>new Promise((resolve,reject)=>{
    const end=()=>{clearTimeout(timer);reject(new DOMException('Aborted','AbortError'));};
    const timer=setTimeout(()=>{signal.removeEventListener('abort',end);resolve();},650);
    signal.addEventListener('abort',end,{once:true});if(signal.aborted)end();
  }),id=()=>crypto.randomUUID().replaceAll('-',''),startupMs=30000}) {
    Object.assign(this,{api,capture,player,onState,onSettings,save,wait,id,startupMs});this.version=0;this.session=null;this.turn=null;this.next=0;this.muted=false;this.busy=false;this.active=false;this.control=null;this.startKey=null;this.phase='ended';this.settings=null;
  }
  state(value,message='') { this.phase=value;this.onState(value,message); }
  persist() { this.save(this.session||this.startKey?{session:this.session,turn:this.turn,next:this.next,startKey:this.startKey,settings:this.settings}:null); }
  settingsFrom(values) { this.settings=values?Object.fromEntries(['target','native','level','voice'].map(name=>[name,values[name]])):null;this.onSettings(this.settings); }
  fresh() { this.control?.abort();this.control=new AbortController();return {ticket:++this.version,signal:this.control.signal}; }
  valid(ticket) { return this.active&&ticket===this.version; }
  async start(settings) {
    if(this.active)return;
    this.active=true;this.settingsFrom(settings);this.startKey=this.id();const {ticket,signal}=this.fresh();this.state('preparing');let dispatched=false;
    try {
      // Permission and playback unlock happen in the Start gesture, before paid requests.
      await within(()=>this.capture.permission(signal),signal,this.startupMs);if(!this.valid(ticket))return;
      await within(()=>this.player.unlock(signal),signal,this.startupMs);if(!this.valid(ticket))return;
      this.persist();dispatched=true;
      const state=await this.api.start({...settings,start_key:this.startKey},signal);
      if(!this.valid(ticket))return;
      this.session=state.session_id;this.persist();await this.receive(state,ticket,signal);
    } catch(error) {
      if(!this.valid(ticket))return;
      if(dispatched)this.pause(error.message);
      else {
        this.active=false;this.control.abort();++this.version;this.capture.cancel();this.player.stop();this.startKey=null;this.save(null);
        this.state('ended',error.name==='NotAllowedError'?'Izin mikrofon ditolak. Izinkan mikrofon di pengaturan browser, lalu Mulai belajar.':error.message);
      }
    }
  }
  async restore(saved) {
    if(this.active)return;
    this.active=true;this.session=saved?.session||null;this.turn=saved?.turn||null;this.next=saved?.next||0;this.startKey=saved?.startKey||null;
    this.settingsFrom(saved?.settings);
    this.state('paused','Sesi sebelumnya ditemukan. Tekan Lanjutkan untuk mengaktifkan mikrofon dan audio.');
  }
  async resume() {
    if(!this.active||this.phase!=='paused')return;
    const {ticket,signal}=this.fresh();this.busy=true;this.state('preparing');
    try {
      await within(()=>this.capture.permission(signal),signal,this.startupMs);if(!this.valid(ticket))return;await within(()=>this.player.unlock(signal),signal,this.startupMs);if(!this.valid(ticket))return;
      let state;
      try{state=this.session?await this.api.status(this.session,this.turn,signal):await this.api.current(signal);}
      catch(error){
        if(error.code!=='not_found'||!this.session||!this.turn)throw error;
        // An upload never admitted by the server must not be re-POSTed. Skip
        // already-heard previous clips, then listen for a deliberately new turn.
        state=await this.api.status(this.session,null,signal);this.turn=state.turn;this.next=state.clips?.length||0;
      }
      if(!this.valid(ticket))return;
      if(!state.session_id||state.ended){this.end();return;}
      this.session=state.session_id;if(state.target)this.settingsFrom(state);
      if(state.status==='FAILED'||state.status==='CANCELLED'){this.turn=state.turn;this.next=state.clips?.length||0;this.busy=false;this.input=false;this.persist();await this.listen(ticket);return;}
      await this.receive(state,ticket,signal);
    } catch(error) {if(this.valid(ticket))this.pause(error.message);}
  }
  async receive(initial,ticket,signal) {
    this.capture.cancel();this.busy=true;if(initial.target)this.settingsFrom(initial);
    if(initial.turn!==this.turn){this.turn=initial.turn;this.next=0;}
    this.persist();let state=initial;
    while(this.valid(ticket)) {
      if(state.ended){this.end();return;}
      const clips=state.clips||[];let played=false;
      let prefetched;
      while(clips.some(c=>c.index===this.next)&&this.valid(ticket)) {
        this.state('speaking');
        const raw=await (prefetched||this.api.clip(this.session,this.turn,this.next,signal));prefetched=null;
        if(!this.valid(ticket))return;
        if(clips.some(c=>c.index===this.next+1)) {
          const upcoming=this.next+1;
          prefetched=this.api.clip(this.session,this.turn,upcoming,signal).then(value=>this.player.prepare?this.player.prepare(value,signal):value);
          // An interrupted current clip must not leave an unhandled preload rejection.
          prefetched.catch(()=>{});
        }
        await this.player.play(raw,signal,()=>this.api.milestone?.('playback_start',this.next));played=true;
        if(!this.valid(ticket))return;
        ++this.next;this.persist();
      }
      if(state.status==='FAILED'||state.status==='CANCELLED') {
        this.busy=false;this.input=false;this.persist();
        this.pause('Jawaban belum lengkap. Tidak ada pengulangan otomatis. Periksa koneksi atau saldo, lalu Lanjutkan untuk ucapan baru.');return;
      }
      if(state.status==='COMPLETED'||!state.turn) {
        if(clips.some(c=>c.index>=this.next))throw Error('Urutan audio belum lengkap. Tekan Lanjutkan untuk memeriksa kembali.');
        this.busy=false;await this.listen(ticket);return;
      }
      // A temporarily empty queue is NOT a finished tutor response.
      this.state('preparing');if(!played)await this.wait(signal);
      state=await this.api.status(this.session,this.turn,signal);
    }
  }
  async listen(ticket=this.version) {
    if(!this.valid(ticket)||this.busy)return;
    if(this.muted){this.state('muted');return;}
    this.state('listening');
    try {await within(()=>this.capture.start(state=>this.submit(state),message=>this.pause(message)),this.control.signal,this.startupMs);}
    catch(error){if(this.valid(ticket))this.pause(error.message);}
    // RealtimeMic owns late grants. An old listen must never cancel a newer call.
    if(this.valid(ticket)&&this.muted)this.capture.cancel();
  }
  beginInput(turn) {
    if(!this.active||this.muted)return;
    this.turn=turn;this.next=0;this.input=true;this.busy=true;this.persist();
  }
  async submit(state) {
    if(!this.active||this.muted)return;
    this.capture.cancel();this.busy=true;this.input=false;
    const {ticket,signal}=this.fresh();this.state('preparing');
    try {if(this.valid(ticket))await this.receive(state,ticket,signal);}
    catch(error){if(this.valid(ticket))this.pause('Proses terputus. Lanjutkan hanya memeriksa status, tanpa mengirim ulang audio. '+error.message);}
  }
  mute() {
    if(!this.active||this.phase==='paused')return this.muted;
    this.muted=!this.muted;
    if(this.muted){this.capture.cancel();if(this.input){this.input=false;this.busy=false;this.recoverInput=true;}if(!this.busy)this.state('muted');}
    else if(this.recoverInput){this.recoverInput=false;this.pause();void this.resume();}
    else if(!this.busy)void this.listen();
    return this.muted;
  }
  pause(message='Sesi dijeda. Tekan Lanjutkan saat siap.') {
    if(!this.active)return;
    this.control?.abort();++this.version;this.capture.cancel();this.player.stop();this.state('paused',message);
  }
  end() {
    const session=this.session,startKey=this.startKey;
    this.active=false;const endedVersion=++this.version;this.control?.abort();this.capture.cancel();this.player.stop();
    this.session=null;this.turn=null;this.next=0;this.busy=false;this.muted=false;this.input=false;this.recoverInput=false;this.startKey=null;this.save(null);this.state('ended');
    // Separate best-effort control request survives cancellation of data requests.
    return this.api.end(session,startKey).catch(()=>{if(!this.active&&this.version===endedVersion)this.state('ended','Mikrofon dan audio berhenti. Konfirmasi akhir sesi server belum diterima; periksa sesi sebelum mulai lagi.');});
  }
}
