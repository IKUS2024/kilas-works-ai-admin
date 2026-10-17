"""Exact selected Chat author for existing deterministic document renderers."""
from . import chat_models,model_policy,providers


class Author:
    def __init__(self,model,prompt,style,attachments=()):
        chat_models.spec(model)
        self.model=model;self.metadata={};self.used={'selected_model':model};self.dispatched=False
        from .attachments import prompt_content
        self.messages=chat_models.bind(model_policy.ChatContext([{'role':'user','content':prompt_content(prompt,attachments) if attachments else prompt}]),model)
        chat_models.validate_messages(model,self.messages)
        self.style=style;self.profile=model_policy.chat_profile(self.messages)

    def write(self):
        pieces=[];size=0;finish=None
        try:
            for event in providers.stream('FAST',self.messages,system=self.style):
                if event['type']=='provider':self.dispatched=True
                elif event['type']=='model_metadata':self.metadata.update(event)
                elif event['type']=='usage':self.used.update({k:event[k] for k in ('input_tokens','output_tokens','cached_input_tokens','cache_write_input_tokens') if k in event})
                elif event['type']=='delta':
                    size+=len(event['text'])
                    if size>24000:raise providers.ProviderError('document_too_long')
                    pieces.append(event['text'])
                elif event['type']=='finish':finish=event['reason']
            if finish!='stop' or not pieces:raise providers.ProviderError('incomplete_document')
            return ''.join(pieces)
        finally:
            if self.dispatched and not self.used.get('input_tokens') and not self.used.get('output_tokens'):self.used['billing_unknown']=True

    def provenance(self):
        return {'requested_model':self.model,'returned_model':self.metadata.get('returned_model') or 'unreported',
                'provider':chat_models.spec(self.model)['provider']}
