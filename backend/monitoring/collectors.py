"""Small, source-specific parsers. Unknown time/route/location is never imputed."""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import hashlib
import json
import math
import re
from urllib.parse import urlencode, urljoin, urlsplit
from zoneinfo import ZoneInfo

MSK = ZoneInfo('Europe/Moscow')
CLOSURES = 'https://transport.mos.ru/mostrans/closures'
CHANGES = 'https://old.mosgortrans.ru/routes/changes/'
DEPTRANS = 'https://t.me/s/DtOperativno'
EVENTS = 'https://kudago.com/public-api/v1.4/events/'
MET = 'https://api.met.no/weatherapi/locationforecast/2.0/compact?lat=55.7558&lon=37.6173'
OPEN_METEO = 'https://api.open-meteo.com/v1/forecast?' + urlencode(dict(
    latitude=55.7558, longitude=37.6173, hourly='temperature_2m,precipitation,wind_speed_10m',
    forecast_days=3, timezone='Europe/Moscow', wind_speed_unit='ms'))


def iso(value):
    return value.isoformat()


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Timestamp has no timezone')
    return parsed


def finite(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError('Expected finite numeric measurement')
    return value


def public_url(value, host):
    parsed = urlsplit(value)
    if parsed.scheme != 'https' or parsed.hostname != host or parsed.username or parsed.port:
        raise ValueError('Unexpected source URL')
    return value


def record(source, key, title, now, *, url, start=None, end=None, precision='unknown',
           location=None, routes=None, published=None, values=None, note=None):
    return dict(id=source + ':' + hashlib.sha256(str(key).encode()).hexdigest()[:20],
                source_id=source, source_url=url, fetched_at=iso(now), published_at=published,
                information_mode='operational', title=title,
                valid_start=start, valid_end=end, period_precision=precision, timezone='Europe/Moscow',
                location=location or {'name': None, 'lat': None, 'lon': None, 'status': 'unknown'},
                route_link={'status': 'explicit' if routes else 'unknown', 'route_ids': routes or [],
                            'method': 'source_explicit_tram_numbers' if routes else None},
                values=values or {}, note=note, forecast_effect='not_applied')


CITY = {'name': 'Москва · одна погодная точка', 'lat': 55.7558, 'lon': 37.6173, 'status': 'city_proxy'}


def parse_met(body, now):
    data = json.loads(body)['properties']
    meta = data['meta']
    for key, expected in [('air_temperature', 'celsius'), ('precipitation_amount', 'mm'), ('wind_speed', 'm/s')]:
        if meta['units'].get(key) != expected:
            raise ValueError('Unexpected weather units')
    updated = timestamp(meta['updated_at'])
    if not timedelta(0) <= now - updated <= timedelta(hours=24):
        raise ValueError('Weather model issue time is stale or in future')
    rows = []
    for point in data['timeseries']:
        start = timestamp(point['time'])
        hour = point['data'].get('next_1_hours')
        if hour is None or start < now - timedelta(hours=1) or start >= now + timedelta(hours=72):
            continue
        instant = point['data']['instant']['details']
        rows.append(record('weather', point['time'], 'Погода в Москве', now, url=MET,
            start=iso(start), end=iso(start + timedelta(hours=1)), precision='hour', location=CITY,
            published=iso(updated), values={'temperature_c': finite(instant['air_temperature']),
                'wind_ms': finite(instant['wind_speed']), 'precipitation_mm': finite(hour['details']['precipitation_amount']),
                'precipitation_period': 'next_hour', 'symbol': hour['summary']['symbol_code']},
            note='Модельный прогноз, не наблюдение станции. Городской фон; маршрутная связь не установлена.'))
    starts = [timestamp(r['valid_start']) for r in rows]
    if len(starts) < 24 or starts[0] > now + timedelta(hours=1) or any(b-a != timedelta(hours=1) for a,b in zip(starts,starts[1:])):
        raise ValueError('Incomplete or duplicate hourly weather grid')
    return rows, dict(window_start=rows[0]['valid_start'], window_end=rows[-1]['valid_end'],
                      complete=True, scope='Одна точка Москвы; доступный почасовой горизонт', provider_updated_at=iso(updated))


def parse_open_meteo(body, now):
    data = json.loads(body)
    if data.get('utc_offset_seconds') != 10800 or data.get('timezone') != 'Europe/Moscow':
        raise ValueError('Unexpected weather timezone')
    for key, unit in [('temperature_2m', '°C'), ('precipitation', 'mm'), ('wind_speed_10m', 'm/s')]:
        if data['hourly_units'].get(key) != unit:
            raise ValueError('Unexpected weather units')
    hourly = data['hourly']; times = hourly['time']
    if len(times) != 72 or any(len(hourly[k]) != 72 for k in ['temperature_2m','precipitation','wind_speed_10m']):
        raise ValueError('Incomplete weather grid')
    rows = []
    for i, value in enumerate(times):
        start = datetime.fromisoformat(value).replace(tzinfo=MSK)
        if start.date() != now.astimezone(MSK).date() + timedelta(days=i//24) or start.hour != i%24:
            raise ValueError('Unexpected weather dates')
        rows.append(record('weather', value, 'Погода в Москве', now, url=OPEN_METEO,
            start=iso(start), end=iso(start+timedelta(hours=1)), precision='hour', location=CITY,
            values={'temperature_c': finite(hourly['temperature_2m'][i]), 'wind_ms': finite(hourly['wind_speed_10m'][i]),
                    'precipitation_mm': finite(hourly['precipitation'][i]), 'precipitation_period': 'preceding_hour'},
            note='Модельный прогноз; осадки за предшествующий час. Связь с маршрутом неизвестна.'))
    return rows, dict(window_start=rows[0]['valid_start'], window_end=rows[-1]['valid_end'], complete=True,
                      scope='Одна точка Москвы; три календарных дня', provider_updated_at=None)


@dataclass
class Node:
    tag: str = ''
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)

    def text(self):
        return ' '.join(' '.join(c.text() if isinstance(c,Node) else c for c in self.children).split())

    def find(self, *, cls=None, tag=None):
        out = []
        for c in self.children:
            if isinstance(c, Node):
                if (cls is None or cls in c.attrs.get('class','').split()) and (tag is None or c.tag == tag):
                    out.append(c)
                out.extend(c.find(cls=cls,tag=tag))
        return out


class Document(HTMLParser):
    def __init__(self, body):
        super().__init__(convert_charrefs=True)
        self.root = Node(); self.stack = [self.root]
        self.feed(body.decode('utf-8'))

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs)); self.stack[-1].children.append(node)
        if tag not in {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs); self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]; break

    def handle_data(self, value):
        if self.stack[-1].tag not in {'script','style'}:
            self.stack[-1].children.append(value)


def day(value):
    return datetime.strptime(value, '%d.%m.%Y').replace(tzinfo=MSK)


def parse_closures(body, now):
    root = Document(body).root
    inputs = {n.attrs.get('id'): n.attrs.get('value') for n in root.find(tag='input')}
    expected = now.astimezone(MSK).strftime('%d.%m.%Y')
    if inputs.get('search_road_closures_dateFrom') != expected or inputs.get('search_road_closures_dateTo') != expected:
        raise ValueError('Closure page does not cover today')
    items = root.find(cls='closures_item')
    if not items:
        raise ValueError('Closure page structure changed or unconfirmed empty feed')
    details = {n.attrs.get('id'): n.text() for n in root.find(cls='closures_cont')}
    rows = []
    for item in items:
        key = item.attrs['data-id']; parts = item.find(tag='div')
        address = parts[0].text(); dates = parts[1].text()
        start = re.search(r'с\s+(\d{2}\.\d{2}\.\d{4})', dates)
        end = re.search(r'по\s+(\d{2}\.\d{2}\.\d{4})', dates)
        a = day(start[1]) if start else None; b = day(end[1])+timedelta(days=1) if end else None
        if a and b and a >= b:
            raise ValueError('Inverted closure interval')
        rows.append(record('closures', key, address, now, url=CLOSURES,
            start=iso(a) if a else None, end=iso(b) if b else None, precision='day' if a else 'unknown',
            location={'name': address, 'lat': None, 'lon': None, 'status': 'address_only'},
            values={'source_period': dates, 'restriction': details.get('item-'+key)},
            note='Срок по дням, точные часы неизвестны. Пересечение с трамвайной сетью не установлено.'))
    if len({r['id'] for r in rows}) != len(rows):
        raise ValueError('Duplicate closure identifiers')
    return rows, dict(complete=False, scope='Ограничения, показанные официальной картой на сегодня; полнота города не гарантирована',
                      window_start=iso(day(expected)), window_end=iso(day(expected)+timedelta(days=1)))


def parse_changes(body, now):
    root = Document(body).root
    items = root.find(cls='transport-item-ds')
    if not items:
        raise ValueError('Service-change page structure changed or unconfirmed empty feed')
    rows = []
    for item in items:
        links = [a for a in item.find(tag='a') if a.attrs.get('href','').startswith('/routes/changes/')]
        if not links:
            raise ValueError('Service-change article link missing')
        link = links[0]; url = public_url(urljoin(CHANGES, link.attrs['href']), 'old.mosgortrans.ru')
        published = item.find(cls='date-pub-ds'); match = re.search(r'\d{2}\.\d{2}\.\d{4}',published[0].text()) if published else None
        pub = iso(day(match[0])) if match else None
        # Only a transport-specific label can link a number to a tram. Bus 7 is not tram 7.
        tram = [n.text() for n in item.find(cls='tram-ds')]
        routes = sorted(set(re.findall(r'(?<!\w)\d+[а-яА-Я]?(?!\w)', ' '.join(tram))))
        dates = item.find(cls='route-line'); labels = item.find(cls='route-list')
        rows.append(record('changes', url, link.text(), now, url=url, routes=routes, published=pub,
            values={'announced_period_text': dates[0].text() if dates else None,
                    'transport_labels': labels[0].text() if labels else None},
            note='Анонс оператора. Границы действия и место не нормализованы: дата в списке не заменяет текст объявления.'))
    return rows


def parse_events(data, now):
    rows = []
    if not isinstance(data.get('results'), list) or not isinstance(data.get('count'),int):
        raise ValueError('Unexpected event API schema')
    for event in data['results']:
        source = public_url(event['site_url'], 'kudago.com'); place = event.get('place') or {}
        coords = place.get('coords') or {}; lat=coords.get('lat'); lon=coords.get('lon')
        if lat is not None and not -90 <= finite(lat) <= 90 or lon is not None and not -180 <= finite(lon) <= 180:
            raise ValueError('Invalid event coordinates')
        for period in event['dates']:
            start,end = period.get('start'),period.get('end')
            # API uses year 1/9999 as open-ended sentinels, not actual event dates.
            a = datetime.fromtimestamp(start, timezone.utc) if start is not None and 0 < start < 4102444800 else None
            b = datetime.fromtimestamp(end, timezone.utc) if end is not None and 0 < end < 4102444800 else None
            if a and b and a > b:
                raise ValueError('Inverted event interval')
            if (b and b < now) or (a and a >= now+timedelta(days=14)):
                continue
            rows.append(record('events', f"{event['id']}:{start}:{end}", event['title'], now, url=source,
                start=iso(a) if a else None, end=iso(b) if b else None, precision='provider_schedule' if a and b else 'open_schedule',
                published=iso(datetime.fromtimestamp(event['publication_date'],timezone.utc)),
                location={'name': place.get('title'), 'address': place.get('address'), 'lat': lat, 'lon': lon,
                          'status': 'coordinates' if lat is not None and lon is not None else 'address_only' if place else 'unknown'},
                note='По данным KudaGo. Период выставки не означает круглосуточную работу; посещаемость и маршрутная связь неизвестны.'))
    return rows


def parse_deptrans(body, now):
    messages=Document(body).root.find(cls='tgme_widget_message')
    if not messages:
        raise ValueError('Public Deptrans feed missing or login page')
    rows=[]; publication_times=[]
    for message in messages:
        post=message.attrs.get('data-post','')
        if not re.fullmatch(r'DtOperativno/\d+',post):
            continue
        times=message.find(tag='time'); texts=message.find(cls='tgme_widget_message_text')
        if not times: raise ValueError('Deptrans publication timestamp missing')
        published=timestamp(times[-1].attrs['datetime']); publication_times.append(published)
        if published>now+timedelta(minutes=5): raise ValueError('Deptrans publication is in future')
        if not texts: continue  # Media-only post cannot provide a verified restriction.
        # Reply previews have the same text class. The last text is this post, not its quoted parent.
        text=texts[-1].text()
        if not re.search(r'движени|перекры|трамва|поезд|интервал|загружен|скорость',text,re.I): continue
        routes=[]
        for found in re.finditer(r'трамва(?:и|й|ев|я|ях|ям|ями)\s*(?:№\s*)?((?:[ТТтт]?\d+[а-яА-Я]?(?:\s*[,и]\s*|\s+и\s+)?)+)',text,re.I):
            routes+=re.findall(r'[Тт]?\d+[а-яА-Я]?',found[1])
        related=[public_url(a.attrs['href'],'t.me') for a in message.find(cls='tgme_widget_message_reply')
                 if re.fullmatch(r'https://t.me/DtOperativno/\d+',a.attrs.get('href',''))]
        kind='reopening' if re.search(r'движение (?:[^.]{0,100})?(?:открыто|восстановлено)',text,re.I) else 'announcement'
        start=end=None; precision='unknown'
        ranges=re.findall(r'с\s*(\d{1,2}):(\d{2})\s*до\s*(\d{1,2}):(\d{2})',text,re.I)
        relative=re.findall(r'\b(завтра|сегодня)\b',text,re.I)
        if len(ranges)==1 and relative and len(set(w.lower() for w in relative))==1:
            day_at=published.astimezone(MSK).replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=relative[0].lower()=='завтра')
            h1,m1,h2,m2=map(int,ranges[0])
            if h1<24 and h2<24 and m1<60 and m2<60 and (h1,m1)<(h2,m2):
                start=iso(day_at.replace(hour=h1,minute=m1));end=iso(day_at.replace(hour=h2,minute=m2));precision='announced_window'
        score=re.search(r'загруженность дорог (?:составляет|—|–|-|:)\s*(\d{1,2})\s*балл',text,re.I)
        speed=re.search(r'[Сс]редняя скорость[^.]{0,60}?(\d{1,3})\s*км/ч',text)
        traffic={}
        if score and 0<=int(score[1])<=10: traffic['road_load_score']=int(score[1])
        if speed and 0<=int(speed[1])<=150: traffic['average_speed_kmh']=int(speed[1])
        rows.append(record('changes',post,text[:240],now,url='https://t.me/'+post,
            start=start,end=end,precision=precision,routes=sorted(set(routes)),published=iso(published),
            location={'name':'Москва · место уточняется в объявлении','lat':None,'lon':None,'status':'city_only'},
            values={'notice_kind':kind,'related_source_urls':related,'period_text':text[:1600], 'traffic_bulletin':traffic},
            note='Официальное объявление; цитата предыдущего сообщения исключена. Восстановление может касаться только части улиц. Неуказанные сроки и маршрутная связь остаются неизвестными.'))
    if not publication_times: raise ValueError('Deptrans feed contains no dated official posts')
    rows.sort(key=lambda r:r['published_at'],reverse=True)
    return rows, dict(complete=False,scope='Последние публичные сообщения Дептранса; не полный реестр инцидентов',
                      latest_publication=iso(max(publication_times)),pages=1)


def collect(source_id, fetch, now, weather_provider='met'):
    if source_id == 'weather':
        body = fetch(MET if weather_provider == 'met' else OPEN_METEO)
        return (parse_met if weather_provider == 'met' else parse_open_meteo)(body, now)
    if source_id == 'closures':
        return parse_closures(fetch(CLOSURES), now)
    if source_id == 'changes':
        return parse_deptrans(fetch(DEPTRANS),now)
    if source_id == 'events':
        params = dict(location='msk',actual_since=int(now.timestamp()),actual_until=int((now+timedelta(days=14)).timestamp()),
                      page_size=100,fields='id,title,dates,place,site_url,publication_date',expand='place',order_by='-publication_date')
        rows=[]; fetched=0; count=None; event_ids=set()
        for page in range(1,21):
            data = json.loads(fetch(EVENTS+'?'+urlencode({**params, 'page':page})))
            if count is None: count=data['count']
            if count != data['count']: raise ValueError('Event feed changed during pagination; retry next cycle')
            for event in data['results']:
                if event['id'] in event_ids:
                    raise ValueError('Duplicate event across pages; retry next cycle')
                event_ids.add(event['id'])
            rows.extend(parse_events(data,now)); fetched+=len(data['results'])
            if not data.get('next'): break
        # Do not follow arbitrary next URLs supplied by external content.
        complete = not data.get('next') and fetched == count
        return list({r['id']:r for r in rows}.values()), dict(complete=complete,
            pages=page, provider_count=count, fetched_count=fetched,
            window_start=iso(now), window_end=iso(now+timedelta(days=14)),
            scope='Афиша Москвы на 14 дней; полнота всех городских событий не установлена')
    raise ValueError('Unknown collector')
