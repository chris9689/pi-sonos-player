import re
import urllib.parse
from typing import Optional, Dict, Any, Tuple
import yt_dlp

# Regex pattern matching YouTube video IDs
YOUTUBE_ID_REGEX = re.compile(r'^[a-zA-Z0-9_-]{11}$')

# Patterns matching supported YouTube URLs
YOUTUBE_URL_PATTERNS = [
    re.compile(r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/watch\?v=([a-zA-Z0-9_-]{11})'),
    re.compile(r'(?:https?:\/\/)?(?:www\.)?youtu\.be\/([a-zA-Z0-9_-]{11})'),
    re.compile(r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/shorts\/([a-zA-Z0-9_-]{11})'),
    re.compile(r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/embed\/([a-zA-Z0-9_-]{11})'),
    re.compile(r'(?:https?:\/\/)?(?:music\.)?youtube\.com\/watch\?v=([a-zA-Z0-9_-]{11})'),
]


def extract_video_id(url: str) -> Optional[str]:
    """
    Safely extract and validate an 11-character YouTube video ID.
    Rejects any invalid or malicious input.
    """
    if not url or not isinstance(url, str):
        return None

    url = url.strip()

    # Direct video ID passed
    if YOUTUBE_ID_REGEX.match(url):
        return url

    for pattern in YOUTUBE_URL_PATTERNS:
        match = pattern.search(url)
        if match:
            return match.group(1)

    # Parse query parameters as fallback
    try:
        parsed = urllib.parse.urlparse(url)
        if 'youtube.com' in parsed.netloc:
            qs = urllib.parse.parse_qs(parsed.query)
            if 'v' in qs and qs['v'] and YOUTUBE_ID_REGEX.match(qs['v'][0]):
                return qs['v'][0]
    except Exception:
        pass

    return None


def get_video_info(video_id_or_url: str) -> Dict[str, Any]:
    """
    Fetch metadata (title, duration, thumbnail, channel) for a YouTube video.
    Does not download the video file.
    """
    video_id = extract_video_id(video_id_or_url)
    if not video_id:
        raise ValueError("Invalid YouTube URL or video ID.")

    target_url = f"https://www.youtube.com/watch?v={video_id}"

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'extract_flat': False,
        'noplaylist': True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(target_url, download=False)
        if not info:
            raise RuntimeError("Could not retrieve video information.")

        duration_sec = info.get('duration') or 0
        minutes = duration_sec // 60
        seconds = duration_sec % 60
        duration_formatted = f"{minutes}:{seconds:02d}" if duration_sec else "Live / Unknown"

        thumbnails = info.get('thumbnails') or []
        thumbnail_url = thumbnails[-1].get('url') if thumbnails else None

        return {
            'id': video_id,
            'title': info.get('title', 'Unknown Title'),
            'channel': info.get('uploader') or info.get('channel', 'Unknown Artist'),
            'duration': duration_sec,
            'duration_formatted': duration_formatted,
            'thumbnail': thumbnail_url,
            'url': target_url
        }


def get_audio_stream_info(video_id_or_url: str) -> Dict[str, Any]:
    """
    Extract the direct stream URL and mime type for playback.
    Prefers m4a/aac (format 140) which Sonos supports natively without transcoding.
    """
    video_id = extract_video_id(video_id_or_url)
    if not video_id:
        raise ValueError("Invalid YouTube URL or video ID.")

    target_url = f"https://www.youtube.com/watch?v={video_id}"

    ydl_opts = {
        'format': 'bestaudio[ext=m4a]/bestaudio/140/best',
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'noplaylist': True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(target_url, download=False)
        if not info:
            raise RuntimeError("Could not extract stream URL.")

        stream_url = info.get('url')
        if not stream_url:
            raise RuntimeError("No direct stream URL found for this video.")

        ext = info.get('ext', 'm4a')
        mime_type = 'audio/mp4' if ext in ('m4a', 'mp4') else 'audio/webm'

        return {
            'id': video_id,
            'title': info.get('title', 'Unknown Title'),
            'channel': info.get('uploader', 'Unknown Artist'),
            'duration': info.get('duration', 0),
            'stream_url': stream_url,
            'http_headers': info.get('http_headers', {}),
            'mime_type': mime_type,
            'ext': ext
        }
