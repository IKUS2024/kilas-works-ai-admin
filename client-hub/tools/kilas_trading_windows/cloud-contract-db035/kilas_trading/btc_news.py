"""Disabled fixed public RSS collector; editorial coverage never proves LOW risk."""
import hashlib
import html
import os
import re
import time
from datetime import timezone, timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from xml.etree import ElementTree
import requests
from . import bridge

URL='https://www.coindesk.com/arc/outboundfeeds/rss/'
COVERAGE='BTC_EDITORIAL_ONLY'
MAX_BYTES=262144

class Text(HTMLParser):
    def __init__(self):super().__init__();self.parts=[]
    def handle_data(self,value):self.parts.append(value)

def parse(raw,checked_at):
    bridge.require(type(raw) is bytes and 0<len(raw)<=MAX_BYTES,'NEWS_SIZE_REJECTED')
    bridge.require(b'<!DOCTYPE' not in raw.upper() and b'<!ENTITY' not in raw.upper(),'NEWS_XML_REJECTED')
    try:
        text=raw.decode('utf-8-sig')
        bridge.require('\x00' not in text and '<!DOCTYPE' not in text.upper() and '<!ENTITY' not in text.upper(),'NEWS_XML_REJECTED')
        root=ElementTree.fromstring(text)
        bridge.require(root.tag=='rss','NEWS_FORMAT_REJECTED')
        bridge.require(len(root.findall('./channel'))==1,'NEWS_FORMAT_REJECTED')
        items=root.findall('./channel/item');bridge.require(len(items)<=100,'NEWS_ITEMS_REJECTED')
        articles=[]
        for item in items:
            title=item.findtext('title','');parser=Text();parser.feed(title)
            title=' '.join(html.unescape(''.join(parser.parts)).split())
            if not re.search(r'\b(?:bitcoin|btc)\b',title,re.I):continue
            published=parsedate_to_datetime(item.findtext('pubDate',''))
            if published.tzinfo is None:continue
            published=published.astimezone(timezone.utc)
            if not 0<=(checked_at-published).total_seconds()<=3600:continue
            title=title[:240]
            if not title:continue
            ident=hashlib.sha256((bridge.stamp(published)+'\n'+title).encode()).hexdigest()[:32]
            if any(a['id']==ident for a in articles):continue
            articles.append(dict(id=ident,published_at=bridge.stamp(published),title=title))
        articles.sort(key=lambda a:a['published_at'],reverse=True);articles=articles[:3]
        return dict(provider='TRUSTED_NEWS_V1',as_of=bridge.stamp(checked_at),valid_until=bridge.stamp(checked_at+timedelta(seconds=300)),verified=True,event_risk='UNKNOWN',sentiment=0,coverage=COVERAGE,risk_review='UNREVIEWED',articles=articles)
    except bridge.Rejected:raise
    except Exception:raise bridge.Rejected('NEWS_PARSE_REJECTED') from None

def collect():
    bridge.require(os.environ.get('KILAS_TRADING_BTC_NEWS_ENABLED')=='true','NEWS_COLLECTOR_DISABLED',404)
    try:
        with requests.get(URL,headers={'Accept':'application/rss+xml, application/xml','User-Agent':'KilasTradingCatalog/1'},timeout=(5,10),allow_redirects=False,stream=True) as response:
            bridge.require(response.status_code==200,'NEWS_HTTP_UNAVAILABLE')
            body=bytearray();started=time.monotonic()
            for chunk in response.iter_content(4096):
                body.extend(chunk)
                bridge.require(len(body)<=MAX_BYTES and time.monotonic()-started<=15,'NEWS_RESPONSE_BOUND')
        return parse(bytes(body),bridge.now())
    except bridge.Rejected:raise
    except Exception:raise bridge.Rejected('NEWS_TRANSPORT_UNAVAILABLE') from None
