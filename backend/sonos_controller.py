import logging
import threading
import time
from typing import List, Dict, Any, Optional
from xml.sax.saxutils import escape

import soco
from soco.exceptions import SoCoException

logger = logging.getLogger(__name__)

# Speakers keyed by both IP and player name
_speakers_cache: Dict[str, soco.SoCo] = {}
_cache_lock = threading.Lock()
_last_scan_time = 0.0
CACHE_TTL = 30  # seconds


def get_sonos_by_identifier(identifier: str) -> Optional[soco.SoCo]:
    """Find a speaker by IP address or player name."""
    with _cache_lock:
        if identifier in _speakers_cache:
            return _speakers_cache[identifier]

    if identifier.count('.') == 3:
        try:
            sp = soco.SoCo(identifier)
            name = sp.player_name  # connectivity check
            with _cache_lock:
                _speakers_cache[identifier] = sp
                _speakers_cache[name] = sp
            return sp
        except Exception as e:
            logger.warning(f"Could not connect directly to Sonos at {identifier}: {e}")

    discover_speakers(force=True)
    with _cache_lock:
        return _speakers_cache.get(identifier)


def _coordinator(sp: soco.SoCo) -> soco.SoCo:
    """Transport commands must go to the group coordinator, otherwise Sonos rejects them."""
    try:
        if not sp.is_coordinator and sp.group:
            return sp.group.coordinator
    except Exception as e:
        logger.warning(f"Could not resolve group coordinator: {e}")
    return sp


def _list_entry(sp: soco.SoCo) -> Dict[str, Any]:
    return {'name': sp.player_name, 'ip': sp.ip_address, 'uid': sp.uid}


def discover_speakers(force: bool = False) -> List[Dict[str, Any]]:
    """Discover visible Sonos zones via SSDP. Returns lightweight entries (no per-speaker status calls)."""
    global _last_scan_time

    with _cache_lock:
        if not force and _speakers_cache and (time.time() - _last_scan_time < CACHE_TTL):
            unique = {sp.uid: sp for sp in _speakers_cache.values()}
            return sorted((_list_entry(sp) for sp in unique.values()), key=lambda s: s['name'].lower())

    try:
        found = soco.discover(timeout=4) or set()
    except Exception as e:
        logger.error(f"Error during Sonos discovery: {e}")
        found = set()

    new_cache: Dict[str, soco.SoCo] = {}
    for sp in found:
        try:
            new_cache[sp.ip_address] = sp
            new_cache[sp.player_name] = sp
        except Exception as e:
            logger.warning(f"Error reading speaker properties: {e}")

    with _cache_lock:
        _speakers_cache.clear()
        _speakers_cache.update(new_cache)
        _last_scan_time = time.time()
        unique = {sp.uid: sp for sp in _speakers_cache.values()}
        return sorted((_list_entry(sp) for sp in unique.values()), key=lambda s: s['name'].lower())


def format_speaker_status(sp: soco.SoCo) -> Dict[str, Any]:
    """Serializable status: volume from the speaker itself, transport/track from its coordinator."""
    coord = _coordinator(sp)

    try:
        state = coord.get_current_transport_info().get('current_transport_state', 'UNKNOWN')
    except Exception:
        state = 'UNKNOWN'

    try:
        volume = sp.volume
    except Exception:
        volume = None

    try:
        track = coord.get_current_track_info()
    except Exception:
        track = {}

    return {
        'name': sp.player_name,
        'ip': sp.ip_address,
        'uid': sp.uid,
        'volume': volume,
        'state': state,
        'current_track': {
            'title': track.get('title', ''),
            'artist': track.get('artist', ''),
            'duration': track.get('duration', ''),
            'position': track.get('position', ''),
        }
    }


def play_audio_stream(sp: soco.SoCo, stream_url: str, title: str, artist: str) -> Dict[str, Any]:
    """Start playback of an HTTP stream with DIDL-Lite metadata (shows title in Sonos apps)."""
    coord = _coordinator(sp)
    attr = {'"': '&quot;'}
    metadata = (
        '<DIDL-Lite xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/" '
        'xmlns:r="urn:schemas-rinconnetworks-com:metadata-1-0/" '
        'xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/">'
        '<item id="-1" parentID="-1" restricted="1">'
        f'<res protocolInfo="http-get:*:audio/mp4:*">{escape(stream_url, attr)}</res>'
        f'<dc:title>{escape(title, attr)}</dc:title>'
        f'<dc:creator>{escape(artist, attr)}</dc:creator>'
        '<upnp:class>object.item.audioItem.musicTrack</upnp:class>'
        '</item>'
        '</DIDL-Lite>'
    )

    try:
        coord.play_uri(stream_url, meta=metadata)
        return format_speaker_status(sp)
    except SoCoException as e:
        logger.error(f"SoCo error playing stream on {sp.player_name}: {e}")
        raise RuntimeError(f"Sonos playback failed: {e}")


def control_playback(sp: soco.SoCo, action: str, value: Optional[int] = None) -> Dict[str, Any]:
    """Transport control: play, pause, stop, volume."""
    coord = _coordinator(sp)
    try:
        if action == 'play':
            coord.play()
        elif action == 'pause':
            coord.pause()
        elif action == 'stop':
            coord.stop()
        elif action == 'volume':
            if not isinstance(value, int) or not (0 <= value <= 100):
                raise ValueError("Volume must be an integer between 0 and 100.")
            sp.volume = value
        else:
            raise ValueError(f"Unknown playback action: {action}")

        return format_speaker_status(sp)
    except SoCoException as e:
        logger.error(f"SoCo error controlling {sp.player_name} ({action}): {e}")
        raise RuntimeError(f"Sonos action '{action}' failed: {e}")
