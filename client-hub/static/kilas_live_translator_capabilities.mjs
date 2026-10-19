// Capabilities are selected BEFORE speech/provider admission; never retry paid
// speech through another transport. No UA sniffing or browser permission bypass.
const MIMES=['audio/webm;codecs=opus','audio/mp4','audio/ogg;codecs=opus'];
export function captureMode(context,scope=globalThis,mediaDevices=scope.navigator?.mediaDevices){
 if(typeof mediaDevices?.getUserMedia!=='function')return null;
 if(typeof context?.audioWorklet?.addModule==='function'&&typeof scope.AudioWorkletNode==='function')return 'realtime-v1';
 const Recorder=scope.MediaRecorder;if(typeof Recorder!=='function')return null;
 try{if(typeof Recorder.isTypeSupported!=='function'||MIMES.some(type=>Recorder.isTypeSupported(type)))return 'batch';}catch{}
 return null;
}
export function compatibleRecorder(Recorder){
 if(typeof Recorder?.isTypeSupported==='function')return Recorder;
 return class extends Recorder {static isTypeSupported(){return false;}};
}
// Supported platforms may retain communication routing after a microphone turn.
// Declare the real capture/playback phase; keep unity gain and OS volume intact.
export class TranslatorAudioRoute {
 constructor(navigator=globalThis.navigator){this.navigator=navigator;this.original=null;this.changed=false;}
 set(type){
  try{const session=this.navigator?.audioSession;if(!session||typeof session.type!=='string')return;
   if(!this.changed){this.original=session.type;this.changed=true;}session.type=type;
  }catch{} // Optional API: absence/rejection cannot disable working WebAudio.
 }
 capture(){this.set('play-and-record');}
 playback(){this.set('playback');}
 restore(){if(!this.changed)return;try{this.navigator.audioSession.type=this.original;}catch{}this.changed=false;this.original=null;}
}
