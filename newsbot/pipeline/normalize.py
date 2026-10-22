"""Приведение данных из лент к единому виду: текст без HTML, канонические ссылки, даты в UTC."""
import re
import html
import calendar
import hashlib
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from bs4 import BeautifulSoup

# Параметры ссылок, которые не меняют саму статью (кроме них отбрасываются все utm_*)
TRACKING_PARAMS = {'yclid', 'gclid', 'fbclid', 'from', 'ref'}


def normalize_text(text: str) -> str:
    text = re.sub(r'[^\w\s]', '', text).lower()
    return re.sub(r'\s+', ' ', text).strip()

def clean_html(text: str) -> str:
    """Убирает все HTML-теги и раскодирует сущности (&quot;, &nbsp; ...) — для plain text."""
    if not text:
        return ''
    text = BeautifulSoup(text, 'html.parser').get_text(' ')
    text = html.unescape(text).replace('\xa0', ' ')
    return re.sub(r'\s+', ' ', text).strip()

def canonical_url(url: str) -> str:
    """Приводит ссылку к единому виду: без меток, якоря и завершающего слэша."""
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not (k.lower().startswith('utm_') or k.lower() in TRACKING_PARAMS)]
    path = parts.path.rstrip('/') or '/'
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ''))

def title_hash(title: str) -> str:
    """Хеш нормализованного заголовка. Описание не учитываем: редакции его часто правят."""
    return hashlib.md5(normalize_text(title).encode('utf-8')).hexdigest()

def entry_published(entry):
    """Дата публикации записи RSS в UTC или None, если даты нет."""
    parsed = entry.get('published_parsed') or entry.get('updated_parsed')
    if not parsed:
        return None
    # feedparser отдаёт struct_time в UTC
    return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)
