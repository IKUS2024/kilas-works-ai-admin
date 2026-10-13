"""Incremental stable sentence boundaries, preserving every character in order."""
import re


class Phrases:
    def __init__(self):
        self.pending = ''
        self.total = 0

    def feed(self, delta, final=False):
        self.pending += delta
        self.total += len(delta)
        if self.total > 1600:
            raise ValueError('tutor_response_too_long')
        result = []
        # ASCII terminal punctuation needs following whitespace; end-of-delta is
        # not end-of-sentence. CJK terminal punctuation needs no whitespace.
        while True:
            boundary = None
            for match in re.finditer(r'[。！？]|[.!?]["\'”’)]*(?=\s)', self.pending):
                if match[0].startswith('.'):
                    word = re.search(r'([\w.]+)$', self.pending[:match.start()])
                    if word and (word[1].lower() in {'mr','mrs','ms','dr','prof','e.g','i.e','etc'} or len(word[1]) == 1):
                        continue
                boundary = match.end()
                break
            if boundary is None:
                break
            result.append(self.pending[:boundary])
            self.pending = self.pending[boundary:]
        if final and self.pending:
            result.append(self.pending)
            self.pending = ''
        return result
