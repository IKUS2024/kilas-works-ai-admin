import test from 'node:test';
import assert from 'node:assert/strict';
import {safeTrackSettings,envelopeCorrelation} from '../static/kilas_ai_call_audio_check.mjs';

test('Local settings summary allowlists processing values and excludes device identity',()=>{
 const result=safeTrackSettings({getSettings:()=>({echoCancellation:true,noiseSuppression:false,autoGainControl:true,sampleRate:48000,channelCount:1,latency:.01,deviceId:'private',groupId:'private',label:'private'}),getCapabilities:()=>({echoCancellation:[true,false,'remote-only','all','unexpected-private']})});
 assert.deepEqual(result,{echoCancellation:true,noiseSuppression:false,autoGainControl:true,channelCount:1,sampleRate:48000,latency:.01,echoCancellationModes:[true,false,'remote-only','all']});
 assert.ok(!JSON.stringify(result).includes('private'));
 assert.deepEqual(safeTrackSettings({}),{echoCancellation:null,noiseSuppression:null,autoGainControl:null,channelCount:null,sampleRate:null,latency:null,echoCancellationModes:[]});
});
test('Local envelope correlation detects a known delayed synthetic echo without retaining PCM',()=>{
 const levels=[.02,.08,0,.04,.08,.02,.04,0,.08,.04,.02,.08,0,.02,.08,.04,.02,0,.04,.08,.02,.04,.08,0,.04,.02,.08,.04,0,.08];
 const reference=levels.map((rms,index)=>({start:index*.2,end:(index+1)*.2,rms}));
 const mic=reference.map(item=>({at:(item.start+item.end)/2+.4,rms:item.rms*.2+.001}));
 const result=envelopeCorrelation(mic,reference);assert.equal(result.coefficient,1);assert.equal(result.lagMs,400);assert.equal(result.pairs,30);
 assert.equal(envelopeCorrelation([],reference),null);
 assert.equal(envelopeCorrelation(mic.map(item=>({...item,rms:.001})),reference),null);
});
