"""Explicit BTC/Gold contracts; no broker aliases, collectors or runtime grants."""
from datetime import timedelta
from . import bridge

INSTRUMENTS = {
    'BTC': dict(symbol='BTCUSD', provider='TRUSTED_BTC_V1', coverage='BTC_EDITORIAL_ONLY',
                news_provider='TRUSTED_NEWS_V1'),
    'GOLD': dict(symbol='GOLD', provider='TRUSTED_GOLD_V1', coverage='GOLD_MACRO_CALENDAR',
                 news_provider='TRUSTED_GOLD_NEWS_V1'),
}
NEWS_FIELDS = ('id','provider','as_of','valid_until','verified','event_risk','sentiment',
               'articles','coverage','risk_review')
CALENDAR_FIELDS = ('provider','as_of','valid_until','coverage_start_at','coverage_end_at',
                   'verified','event_risk','events')
BLACKOUT_SECONDS = 900

def contract(instrument):
    bridge.require(type(instrument) is str and instrument in INSTRUMENTS, 'INSTRUMENT_UNSUPPORTED')
    return INSTRUMENTS[instrument]

def validate_news(news, instrument, ident, now):
    config = contract(instrument)
    bridge.exact(news, NEWS_FIELDS + (('calendar',) if instrument == 'GOLD' else ()))
    bridge.secret(news['id'],32)
    bridge.require(news['id']==ident and news['provider']==config['news_provider']
                   and news['verified'] is True, 'NEWS_UNVERIFIED')
    start,end=bridge.date(news['as_of']),bridge.date(news['valid_until'])
    bridge.require(start<=now<end and (now-start).total_seconds()<=300
                   and 0<(end-start).total_seconds()<=300, 'NEWS_STALE')
    bridge.require(news['event_risk'] in ('LOW','HIGH','UNKNOWN')
                   and type(news['sentiment']) is int and -1<=news['sentiment']<=1, 'NEWS_INVALID')
    bridge.require(news['coverage']==config['coverage']
                   and news['risk_review'] in ('UNREVIEWED','SERVER_REVIEWED'), 'NEWS_COVERAGE_INVALID')
    bridge.require(type(news['articles']) is list and len(news['articles'])<=3, 'NEWS_INVALID')
    for article in news['articles']:
        bridge.exact(article,('id','published_at','title'));bridge.secret(article['id'],32)
        bridge.require(type(article['title']) is str and 1<=len(article['title'])<=240
                       and 0<=(now-bridge.date(article['published_at'])).total_seconds()<=3600, 'NEWS_INVALID')
    if instrument == 'GOLD':
        calendar=bridge.exact(news['calendar'],CALENDAR_FIELDS)
        bridge.require(calendar['provider']=='TRUSTED_GOLD_CALENDAR_V1'
                       and type(calendar['verified']) is bool
                       and calendar['event_risk'] in ('LOW','HIGH','UNKNOWN'), 'CALENDAR_INVALID')
        start,end=bridge.date(calendar['as_of']),bridge.date(calendar['valid_until'])
        bridge.require(start<=now<end and (now-start).total_seconds()<=300
                       and 0<(end-start).total_seconds()<=300, 'CALENDAR_STALE')
        first,last=bridge.date(calendar['coverage_start_at']),bridge.date(calendar['coverage_end_at'])
        bridge.require(first<=last and (last-first).total_seconds()<=86400, 'CALENDAR_COVERAGE_INVALID')
        bridge.require(type(calendar['events']) is list and len(calendar['events'])<=12, 'CALENDAR_INVALID')
        ids=set()
        for event in calendar['events']:
            bridge.exact(event,('id','at','currency','impact','title'));bridge.secret(event['id'],32)
            bridge.require(event['id'] not in ids and first<=bridge.date(event['at'])<=last
                           and event['currency']=='USD' and event['impact'] in ('LOW','MEDIUM','HIGH','UNKNOWN')
                           and type(event['title']) is str and 1<=len(event['title'])<=160, 'CALENDAR_INVALID')
            ids.add(event['id'])
    return news

def news_gate(news, instrument, now):
    # Empty or known high-risk input blocks before paid inference. Editorial
    # headlines alone cannot establish Gold macro/calendar coverage.
    if not news['articles'] or news['event_risk']=='HIGH':
        return 'NEWS_RISK_BLOCKED'
    if instrument == 'GOLD':
        if news['risk_review']!='SERVER_REVIEWED' or news['event_risk']!='LOW':
            return 'GOLD_NEWS_UNREVIEWED'
        cal=news['calendar'];window=timedelta(seconds=BLACKOUT_SECONDS)
        if cal['verified'] is not True or cal['event_risk']!='LOW':
            return 'CALENDAR_UNVERIFIED'
        if not bridge.date(cal['coverage_start_at'])<=now-window or not now+window<=bridge.date(cal['coverage_end_at']):
            return 'CALENDAR_COVERAGE_INSUFFICIENT'
        if any(event['impact'] in ('HIGH','UNKNOWN')
               and abs((bridge.date(event['at'])-now).total_seconds())<=BLACKOUT_SECONDS for event in cal['events']):
            return 'CALENDAR_EVENT_BLOCKED'
    return 'READY'

def placeholder_news(instrument, now):
    """Structural ingest validation only; never retained, collected or sent."""
    config=contract(instrument)
    record=dict(id='0'*32,provider=config['news_provider'],as_of=bridge.stamp(now),
        valid_until=bridge.stamp(now+timedelta(seconds=1)),verified=True,event_risk='UNKNOWN',
        sentiment=0,coverage=config['coverage'],risk_review='UNREVIEWED',
        articles=[dict(id='0'*32,published_at=bridge.stamp(now),title='Validation placeholder; never retained or sent')])
    if instrument=='GOLD':
        record['calendar']=dict(provider='TRUSTED_GOLD_CALENDAR_V1',as_of=bridge.stamp(now),
            valid_until=bridge.stamp(now+timedelta(seconds=1)),coverage_start_at=bridge.stamp(now),
            coverage_end_at=bridge.stamp(now),verified=False,event_risk='UNKNOWN',events=[])
    return record
