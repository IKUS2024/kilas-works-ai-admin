"""Offline reconstruction of the exact final fixture sequence; no provider IO.

The energy detector below is a reference for silence timing, not Gemini's VAD.
It does not establish semantic intelligibility or provider model behavior.
"""
import base64
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
import wave

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from kilas_ai import ai_call as calls

FIXTURES=Path(__file__).parent/'fixtures/ai_call_synthetic'


def pcm(name):
    with wave.open(str(FIXTURES/name),'rb') as wav:
        assert (wav.getnchannels(),wav.getsampwidth(),wav.getframerate())==(1,2,16000)
        return wav.readframes(wav.getnframes())


def reference_segments(raw,chunk_bytes):
    pending=b'';at=0;start=None;last_voice=None;segments=[]
    # 10 ms windows survive all wire chunk boundaries. This is intentionally
    # a simple energy reference, not a claim about learned speech detection.
    for offset in range(0,len(raw),chunk_bytes):
        pending+=raw[offset:offset+chunk_bytes]
        while len(pending)>=320:
            block,pending=pending[:320],pending[320:]
            values=[value[0]/32768 for value in struct.iter_unpack('<h',block)]
            voiced=math.sqrt(sum(v*v for v in values)/160)>=.005
            if voiced:
                if start is None:start=at
                last_voice=at+10
            elif start is not None and at+10-last_voice>=1200:
                segments.append((start,last_voice,at+10));start=None
            at+=10
    return segments


class WireTests(unittest.TestCase):
    def test_actual_call_sender_reconstructs_pcm_and_matches_an_independent_decoder(self):
        pieces=[bytes(64000),pcm('id-first-clear.wav'),pcm('id-followup.wav'),bytes(400000)]
        expected=b''.join(pieces)
        packets=[part[at:at+16000] for part in pieces for at in range(0,len(part),16000)]
        self.assertEqual((len(expected),len(packets)),(789946,50))
        call=calls.Call(1,'e'*32,object())
        call.transport_check=lambda **options:None  # No admission, DB, metering or provider.
        delivered=[];ack=threading.Event()
        class Socket:
            def send(self,payload):
                message=json.loads(payload)
                assert set(message)=={'realtimeInput'}
                assert set(message['realtimeInput'])=={'audio'}
                audio=message['realtimeInput']['audio']
                assert audio['mimeType']=='audio/pcm;rate=16000'
                assert set(audio)=={'mimeType','data'}
                delivered.append(base64.b64decode(audio['data'],validate=True))
                if len(delivered)==len(packets):call.closed.set()
                ack.set()
            def shutdown(self):call.closed.set();ack.set()
        call.ws=Socket();worker=threading.Thread(target=call.send,daemon=True);worker.start()
        try:
            for index,packet in enumerate(packets):
                ack.clear();call.accept(index,packet);self.assertTrue(ack.wait(1))
            worker.join(1);self.assertFalse(worker.is_alive())
            self.assertIsNone(call.code)
            reconstructed=b''.join(delivered)
            self.assertEqual(reconstructed,expected)
            self.assertEqual(call.sent_bytes,len(expected))
            self.assertEqual(reconstructed[:64000],bytes(64000))  # No WAV/RIFF header in wire PCM.
            root=os.environ.get('KILAS_AI_CALL_WIRE_FIXTURE_DIR')
            with tempfile.TemporaryDirectory() as temporary:
                folder=Path(root or temporary);folder.mkdir(parents=True,exist_ok=True)
                raw_path=folder/'ai-call-outgoing-reconstructed.pcm';raw_path.write_bytes(reconstructed)
                executable=shutil.which('ffmpeg')
                if not executable:
                    import imageio_ffmpeg
                    executable=imageio_ffmpeg.get_ffmpeg_exe()
                wav_path=folder/'ai-call-outgoing-reconstructed.wav'
                subprocess.run([executable,'-v','error','-y','-f','s16le','-ar','16000','-ac','1','-i',str(raw_path),'-c:a','pcm_s16le',str(wav_path)],check=True,capture_output=True,timeout=10)
                with wave.open(str(wav_path),'rb') as wav:
                    self.assertEqual((wav.getnchannels(),wav.getsampwidth(),wav.getframerate()),(1,2,16000))
                    self.assertEqual(wav.getnframes(),len(expected)//2)
                    self.assertEqual(wav.readframes(wav.getnframes()),expected)
                report={'synthetic_only':True,'paid_provider_calls':0,'wire_packets':len(packets),'wire_bytes':len(expected),'pcm_sha256':hashlib.sha256(expected).hexdigest(),'duration_ms':len(expected)/32,'sample_rate':16000,'channels':1,'signed_bits':16,'byte_order':'little','mime':'audio/pcm;rate=16000','ffmpeg_roundtrip_equal':True,'semantic_intelligibility_verified':False}
                if root:(folder/'wire-audit.json').write_text(json.dumps(report,indent=2)+'\n')
                print('CALL_WIRE_OFFLINE '+json.dumps(report,sort_keys=True))
        finally:
            call.closed.set();worker.join(1)

    def test_packet_sizes_alone_do_not_split_fixture_with_1200ms_energy_silence(self):
        raw=pcm('id-first-clear.wav')+bytes(64000)
        results={size:reference_segments(raw,size) for size in [320,640,3200,6400,16000]}
        expected=results[320]
        self.assertEqual(len(expected),1)
        self.assertGreater(expected[0][1]-expected[0][0],5000)
        self.assertEqual(expected[0][2]-expected[0][1],1200)
        for result in results.values():self.assertEqual(result,expected)
        print('CALL_ENERGY_REFERENCE '+json.dumps({'synthetic_only':True,'provider_vad_emulated':False,'packet_ms':[10,20,100,200,500],'segments_ms':expected}))


if __name__=='__main__':unittest.main()
