"""Prospective provider-usage evidence; no IO, invoices or historical refunds."""
from dataclasses import dataclass


@dataclass(frozen=True)
class VerifiedUsage:
    input_tokens: int
    output_tokens: int
    streams: int = 1

    @property
    def micro_usd(self):
        # gemini-3.5-live-translate-preview: $3.50/M input, $21/M output.
        return (self.input_tokens*7+self.output_tokens*42+1)//2


def combine(values):
    if not values or any(type(value) is not VerifiedUsage for value in values):
        return None
    return VerifiedUsage(sum(v.input_tokens for v in values),
                         sum(v.output_tokens for v in values), len(values))


class UsageEvidence:
    def __init__(self):
        self.input_tokens = self.output_tokens = self.events = 0
        self.invalid = self.terminal = False

    def observe(self, value, input_ended):
        metadata = value.get('usageMetadata')
        if metadata is None:
            return
        self.events += 1
        prompt, output, total = (metadata.get(k) for k in
                                ('promptTokenCount','responseTokenCount','totalTokenCount')) if isinstance(metadata, dict) else (None,None,None)
        if (self.events>256 or any(type(n) is not int or not 0<=n<=10**7 for n in (prompt,output,total))
                or total != prompt+output
                or any(metadata.get(k,0) != 0 for k in ('cachedContentTokenCount','thoughtsTokenCount','toolUsePromptTokenCount'))):
            self.invalid = True
            return
        # SUM, never delta/MAX: cumulative/repeated observations may overstate
        # cost but cannot silently erase a previous response's usage.
        self.input_tokens += prompt
        self.output_tokens += output
        content = value.get('serverContent', {})
        self.terminal = bool(input_ended and isinstance(content,dict)
                             and content.get('turnComplete') is True
                             and content.get('interrupted') is not True
                             and content.get('interactionStatus') != 'IN_PROGRESS')

    def verified(self, sent_bytes, output_bytes, confirmed):
        if (self.invalid or not self.events or not self.terminal or not confirmed
                or self.input_tokens < (sent_bytes*25+31999)//32000
                or self.output_tokens < (output_bytes*25+47999)//48000):
            return None
        return VerifiedUsage(self.input_tokens,self.output_tokens)
