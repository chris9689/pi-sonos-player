import logging
import re
import threading
import time
import urllib.parse
from typing import Optional, Dict, Any

import requests
import yt_dlp

logger = logging.getLogger(__name__)

YOUTUBE_ID_REGEX = re.compile(r'^[a-zA-Z0-9_-]{11}$')

YOUTUBE_URL_PATTERNS = [
    re.compile(r'(?:https?://)?(?:www\.|m\.|music\.)?youtube\.com/watch\?(?:.*&)?v=([a-zA-Z0-9_-]{11})'),
    re.compile(r'(?:https?://)?youtu\.be/([a-zA-Z0-9_-]{11})'),
    re.compile(r'(?:https?://)?(?:www\.|m\.)?youtube\.com/(?:shorts|embed|live)/([a-zA-Z0-9_-]{11})'),
]

# Shared HTTP session (connection pooling to YouTube/googlevideo)
http = requests.Session()

_title_cache: Dict[str, Dict[str, Any]] = {}
_stream_cache: Dict[str, Dict[str, Any]] = {}
_locks: Dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()
MAX_CACHE = 50


def extract_video_id(url: str) -> Optional[str]:
    """Extract and validate an 11-character YouTube video ID. Rejects anything else."""
    if not url or not isinstance(url, str):
        return None

    url = url.strip()
    if YOUTUBE_ID_REGEX.match(url):
        return url

    for pattern in YOUTUBE_URL_PATTERNS:
        match = pattern.search(url)
        if match:
            return match.group(1)

    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.netloc.endswith('youtube.com'):
            v = urllib.parse.parse_qs(parsed.query).get('v', [''])[0]
            if YOUTUBE_ID_REGEX.match(v):
                return v
    except Exception:
        pass

    return None


def _remember(cache: Dict[str, Any], key: str, value: Any) -> None:
    if len(cache) >= MAX_CACHE:
        cache.pop(next(iter(cache)))
    cache[key] = value


def _lock_for(video_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(video_id, threading.Lock())


def get_video_info(video_id: str) -> Dict[str, Any]:
    """
    Lightweight title lookup via YouTube oEmbed (one small HTTP request, no yt-dlp).
    Falls back to yt-dlp only if oEmbed is unavailable (e.g. embedding disabled).
    """
    if video_id in _title_cache:
        return _title_cache[video_id]

    info: Dict[str, Any] = {'id': video_id, 'title': None, 'channel': None}
    try:
        res = http.get(
            'https://www.youtube.com/oembed',
            params={'url': f'https://www.youtube.com/watch?v={video_id}', 'format': 'json'},
            timeout=5,
        )
        if res.ok:
            data = res.json()
            info['title'] = data.get('title')
            info['channel'] = data.get('author_name')
    except Exception as e:
        logger.warning(f"oEmbed lookup failed for {video_id}: {e}")

    if not info['title']:
        stream = get_audio_stream_info(video_id)
        info['title'] = stream.get('title')
        info['channel'] = stream.get('channel')

    info['title'] = info['title'] or 'YouTube Audio'
    info['channel'] = info['channel'] or 'YouTube'
    _remember(_title_cache, video_id, info)
    return info


def _stream_expiry(stream_url: str) -> float:
    """googlevideo URLs carry an 'expire' unix timestamp; refresh 5 min early."""
    try:
        expire = urllib.parse.parse_qs(urllib.parse.urlparse(stream_url).query).get('expire', [''])[0]
        return float(expire) - 300
    except (ValueError, TypeError):
        return time.time() + 3600


def _probe_size(stream_url: str, headers: Dict[str, str]) -> Optional[int]:
    try:
        res = http.get(stream_url, headers={**headers, 'Range': 'bytes=0-0'}, timeout=(5, 10))
        res.close()
        content_range = res.headers.get('Content-Range', '')
        if '/' in content_range:
            return int(content_range.rsplit('/', 1)[1])
    except Exception as e:
        logger.warning(f"Could not probe stream size: {e}")
    return None


def get_audio_stream_info(video_id: str, refresh: bool = False) -> Dict[str, Any]:
    """
    Resolve the direct audio stream URL (m4a/AAC preferred, natively supported by Sonos).
    Cached until the URL expires so Sonos range/seek requests don't re-run yt-dlp.
    """
    with _lock_for(video_id):
        cached = _stream_cache.get(video_id)
        if cached and not refresh and cached['expires'] > time.time():
            return cached

        started = time.time()
        ydl_opts = {
            'format': '140/bestaudio[ext=m4a]/bestaudio',
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'noplaylist': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f'https://www.youtube.com/watch?v={video_id}', download=False)

        if not info or not info.get('url'):
            raise RuntimeError("No direct audio stream found for this video.")

        stream_url = info['url']
        headers = dict(info.get('http_headers') or {})
        ext = info.get('ext', 'm4a')
        filesize = info.get('filesize') or _probe_size(stream_url, headers)

        result = {
            'id': video_id,
            'title': info.get('title'),
            'channel': info.get('uploader') or info.get('channel'),
            'stream_url': stream_url,
            'http_headers': headers,
            'mime_type': 'audio/mp4' if ext in ('m4a', 'mp4') else 'audio/webm',
            'filesize': filesize,
            'expires': _stream_expiry(stream_url),
        }
        _remember(_stream_cache, video_id, result)
        logger.info(f"Resolved stream for {video_id} in {time.time() - started:.1f}s")
        return result


def prefetch_stream(video_id: str) -> None:
    """Resolve the stream in the background so playback starts faster."""
    cached = _stream_cache.get(video_id)
    if cached and cached['expires'] > time.time():
        return

    def worker():
        try:
            get_audio_stream_info(video_id)
        except Exception as e:
            logger.warning(f"Prefetch failed for {video_id}: {e}")

    threading.Thread(target=worker, daemon=True).start()
