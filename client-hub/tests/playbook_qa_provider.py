"""Synthetic model transport for browser QA only. Never imported by production."""
import json


def reply(prompt, messages, **kwargs):
    text = messages[-1]['content']
    examples = {
        'Mau kirim 20 kg baju dari Guangzhou ke Tangerang':
            {'item':'baju','weight':'20 kg','origin':'Guangzhou','destination':'Tangerang'},
        'Volumenya 0.2 m3': {'volume_cbm':'0.2 m³'},
        'Koreksi asalnya Shanghai': {'origin':'Shanghai'},
        'Mau potong rambut besok jam 14.00':
            {'service':'potong rambut','preferred_date':'besok','preferred_time':'14.00'},
    }
    fields = examples.get(text,{})
    data = dict(intent='REQUEST' if fields else 'UNRELATED', fields=fields,
                evidence={key:text for key in fields}, corrections=['origin'] if text.startswith('Koreksi') else [], ambiguous=[])
    return json.dumps(data,ensure_ascii=False),'end_turn',None
