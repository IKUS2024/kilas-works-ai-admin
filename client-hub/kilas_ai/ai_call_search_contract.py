"""Call-only handling of ignored built-in tool attempts after the one-call cap.

OpenAI's max_tool_calls caps processed calls, not attempted calls. Never infer
that an arbitrary unfinished/failed tool is ignorable. This narrowly admits an
explicitly completed response/final answer whose citations all belong to the
one completed search. Later attempts beyond the echoed cap must either be
incomplete without sources or match the observed searching envelope with only
redundant completed-search sources. No pending response is completed here.
"""
from . import tools


def completed_response(data):
    """Return a filtered copy only for a fully proven one-call-cap envelope."""
    if (not isinstance(data, dict) or data.get('status') != 'completed'
            or data.get('error') is not None or data.get('incomplete_details') is not None
            or type(data.get('max_tool_calls')) is not int or data['max_tool_calls'] != 1):
        return data
    output = data.get('output')
    if not isinstance(output, list) or not output or any(not isinstance(i, dict) for i in output):
        return data
    ids = [i.get('id') for i in output]
    if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        return data
    searches = [(n, i) for n, i in enumerate(output) if i.get('type') == 'web_search_call']
    completed = [(n, i) for n, i in searches if i.get('status') == 'completed']
    ignored = [(n, i) for n, i in searches if i.get('status') != 'completed']
    if len(completed) != 1 or not ignored:
        return data
    done_at, done = completed[0]
    action = done.get('action')
    if not isinstance(action, dict) or action.get('type') != 'search':
        return data
    sources = action.get('sources')
    if not isinstance(sources, list) or not sources:
        return data
    urls = set()
    for source in sources:
        url = tools._source_url(source.get('url')) if isinstance(source, dict) and source.get('type') == 'url' else None
        if not url:
            return data
        urls.add(url)
    messages = [(n, i) for n, i in enumerate(output) if i.get('type') == 'message']
    if len(messages) != 1:
        return data
    final_at, final = messages[0]
    if (final.get('status') != 'completed' or final.get('role') != 'assistant'
            or final.get('phase') not in (None, 'final_answer')):
        return data
    content = final.get('content')
    if not isinstance(content, list) or not content:
        return data
    cited = 0
    for block in content:
        if (not isinstance(block, dict) or block.get('type') != 'output_text'
                or not isinstance(block.get('text'), str) or not block['text'].strip()
                or not isinstance(block.get('annotations'), list)):
            return data
        for annotation in block['annotations']:
            if (not isinstance(annotation, dict) or annotation.get('type') != 'url_citation'
                    or tools._source_url(annotation.get('url')) not in urls):
                return data
            cited += 1
    if not cited:
        return data
    action_fields = {'search': {'type', 'query', 'queries', 'sources'},
                     'open_page': {'type', 'url'}, 'find_in_page': {'type', 'url', 'pattern'}}
    for at, item in ignored:
        if (not done_at < at < final_at or item.get('status') not in ('incomplete', 'searching')
                or set(item) - {'id', 'type', 'status', 'action'}
                or not isinstance(item.get('action'), dict)):
            return data
        kind = item['action'].get('type')
        if not isinstance(kind, str) or kind not in action_fields or set(item['action']) - action_fields[kind]:
            return data
        if item['status'] == 'incomplete':
            if item['action'].get('sources'):
                return data
        else:
            # Captured cap=1 response: a completed final answer can follow a
            # redundant "searching" attempt. Admit only that observed shape,
            # never sources supplied exclusively by the unfinished attempt.
            later_sources = item['action'].get('sources')
            if (len(ignored) != 1 or kind != 'search' or not isinstance(later_sources, list)
                    or not later_sources):
                return data
            for source in later_sources:
                url = tools._source_url(source.get('url')) if isinstance(source, dict) and source.get('type') == 'url' else None
                if not url or url not in urls:
                    return data
    for item in output:
        if item.get('type') not in ('web_search_call', 'message', 'reasoning'):
            return data
        if item.get('type') == 'reasoning' and item.get('status') not in (None, 'completed'):
            return data
    # Preserve final text, actual completed-search sources and all usage. The
    # ordinary adapter still validates completion/citations/URLs/dated FX data.
    ignored_ids = {item['id'] for _, item in ignored}
    return {**data, 'output': [item for item in output if item['id'] not in ignored_ids]}


def envelope_summary(data):
    """Bounded observer metadata for Call/QA; never text, URLs, IDs or headers."""
    statuses = {'completed', 'failed', 'in_progress', 'searching', 'incomplete', 'queued', 'cancelled'}
    types = {'web_search_call', 'message', 'reasoning'}
    if not isinstance(data, dict):
        return {'shape': 'not_object'}
    status = data.get('status')
    result = {'status': status if isinstance(status, str) and status in statuses else 'missing' if status is None else 'other',
              'items': {}, 'error_present': data.get('error') is not None,
              'incomplete_details_present': data.get('incomplete_details') is not None}
    maximum = data.get('max_tool_calls')
    if type(maximum) is int and 0 <= maximum <= 100:
        result['max_tool_calls'] = maximum
    output = data.get('output')
    if not isinstance(output, list):
        result['shape'] = 'output_not_list'
        return result
    result['ordered_items'] = []
    for item in output[:128]:
        kind = item.get('type') if isinstance(item, dict) else None
        state = item.get('status') if isinstance(item, dict) else None
        key = (kind if isinstance(kind, str) and kind in types else 'other')+':'+(
            state if isinstance(state, str) and state in statuses else 'missing' if state is None else 'other')
        result['items'][key] = result['items'].get(key, 0)+1
        result['ordered_items'].append(key)
    return result
