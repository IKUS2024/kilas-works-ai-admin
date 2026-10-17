"""Bounded, content-free provider event timing; not a microphone/VAD verdict."""
from time import monotonic


class TurnTiming:
    def __init__(self, clock=monotonic):
        self.clock = clock
        self.active = False
        self.last_end = None
        self.has_audio = False
        self.starts = 0
        self.ends = 0
        self.audio_turns = 0
        self.overlap = 0
        self.samples = []

    def activity(self, kind):
        if kind == 'ACTIVITY_START':
            self.active = True
            self.last_end = None
            self.starts += 1
        elif kind == 'ACTIVITY_END':
            self.active = False
            self.last_end = self.clock()
            self.ends += 1

    def audio(self):
        if self.has_audio:
            return
        self.has_audio = True
        self.audio_turns += 1
        self.overlap += int(self.active)
        self.samples.append({'speech_active': self.active,
                             'after_activity_end_ms': None if self.last_end is None else
                             min(120000, max(0, round((self.clock()-self.last_end)*1000)))})
        del self.samples[:-8]

    def boundary(self):
        self.has_audio = False

    def report(self):
        return {'activity_starts': self.starts, 'activity_ends': self.ends,
                'audio_turns': self.audio_turns, 'first_audio_during_activity': self.overlap,
                'recent_first_audio': [dict(item) for item in self.samples]}
