# Synthetic discussion fixtures

Generated offline with eSpeak NG 1.52 and FFmpeg. No recorded or cloned person,
external TTS provider, private conversation or credentials were used.
The manifest contains the exact synthetic phrases, hashes and answer checks.

Mono signed PCM16 little endian, 16 kHz. The first Indonesian question is quiet:
every 200 ms frame stays below the former capture gate of 0.015 RMS. Two Indonesian
and two English questions include follow-ups requiring the previous turn's facts.

These fixtures test capture preservation and a bounded real-provider smoke. They
cannot establish physical Android microphone, room echo, speaker or headset quality.
