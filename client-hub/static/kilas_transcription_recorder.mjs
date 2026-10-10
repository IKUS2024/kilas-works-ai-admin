// Injectable browser microphone lifecycle. No capture runs merely by importing this module.
export class VoiceRecorder {
  constructor({mediaDevices,Recorder,onBlob,onState,setTimer=setInterval,clearTimer=clearInterval,now=Date.now}) {
    Object.assign(this,{mediaDevices,Recorder,onBlob,onState,setTimer,clearTimer,now});
    this.version=0;this.stream=null;this.recorder=null;this.timer=null;
  }
  cleanup() {this.stream?.getTracks().forEach(t=>t.stop());this.stream=null;if(this.timer!==null)this.clearTimer(this.timer);this.timer=null;}
  cancel() {++this.version;if(this.recorder?.state==='recording')this.recorder.stop();this.cleanup();this.recorder=null;}
  stop() {if(this.recorder?.state==='recording')this.recorder.stop();else {this.cancel();this.onState('cancelled');}}
  async start({userGesture,consent,enabled}) {
    if(!userGesture||!consent||!enabled)throw Error('Setujui pemrosesan audio dan mulai rekaman melalui tombol.');
    this.cancel();const ticket=this.version;
    try {
      const stream=await this.mediaDevices.getUserMedia({audio:true});
      if(ticket!==this.version){stream.getTracks().forEach(t=>t.stop());return;}
      this.stream=stream;
      const mime=['audio/webm;codecs=opus','audio/mp4','audio/ogg;codecs=opus'].find(t=>this.Recorder.isTypeSupported(t));
      const recorder=new this.Recorder(stream,mime?{mimeType:mime}:undefined),chunks=[];this.recorder=recorder;
      recorder.addEventListener('dataavailable',event=>{if(event.data.size)chunks.push(event.data);});
      recorder.addEventListener('error',()=>{this.cancel();this.onState('error');});
      recorder.addEventListener('stop',()=>{if(ticket!==this.version)return;this.cleanup();const blob=new Blob(chunks,{type:recorder.mimeType||mime||'audio/webm'});this.onBlob(blob);this.onState('ready');});
      recorder.start();const start=this.now();this.onState('recording');
      this.timer=this.setTimer(()=>{if(this.now()-start>=179000)this.stop();},250);
    } catch(error) {if(ticket===this.version){this.cancel();this.onState('error');}throw error;}
  }
}
