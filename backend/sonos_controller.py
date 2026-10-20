import logging
import threading
import time
from typing import List, Dict, Any, Optional
import soco
from soco.exceptions import SoCoException

logger = logging.getLogger(__name__)

# Cache discovered speakers
_speakers_cache: Dict[str, soco.SoCo] = {}
_cache_lock = threading.Lock()
_last_scan_time = 0
CACHE_TTL = 30  # seconds


def get_sonos_by_identifier(identifier: str) -> Optional[soco.SoCo]:
    """
    Find a SoCo speaker instance by IP address or Player Name.
    """
    with _cache_lock:
        if identifier in _speakers_cache:
            return _speakers_cache[identifier]

    # Try connecting directly if identifier looks like an IP
    if identifier.count('.') == 3:
        try:
            sp = soco.SoCo(identifier)
            _ = sp.player_name  # test connectivity
            with _cache_lock:
                _speakers_cache[identifier] = sp
                _speakers_cache[sp.player_name] = sp
            return sp
        except Exception as e:
            logger.warning(f"Could not connect directly to Sonos at IP {identifier}: {e}")

    # Refresh discovery
    discover_speakers(force=True)
    with _cache_lock:
        return _speakers_cache.get(identifier)


def discover_speakers(force: bool = False) -> List[Dict[str, Any]]:
    """
    Discover Sonos speakers using SSDP and return structured speaker info.
    """
    global _last_scan_time
    now = time.time()

    with _cache_lock:
        if not force and _speakers_cache and (now - _last_scan_time < CACHE_TTL):
            # Return cached list without scanning again
            unique_speakers = {sp.uid: sp for sp in _speakers_cache.values()}
            return [_format_speaker_info(sp) for sp in unique_speakers.values()]

    try:
        found = soco.discover(timeout=4)
    except Exception as e:
        logger.error(f"Error during Sonos discovery: {e}")
        found = None

    new_cache: Dict[str, soco.SoCo] = {}
    if found:
        for sp in found:
            try:
                name = sp.player_name
                ip = sp.ip_address
                new_cache[ip] = sp
                new_cache[name] = sp
            except Exception as e:
                logger.warning(f"Error reading speaker properties: {e}")

    with _cache_lock:
        _speakers_cache.clear()
        _speakers_cache.update(new_cache)
        _last_scan_time = now
        unique_speakers = {sp.uid: sp for sp in _speakers_cache.values()}
        return [_format_speaker_info(sp) for sp in unique_speakers.values()]


def _format_speaker_info(sp: soco.SoCo) -> Dict[str, Any]:
    """
    Extract safe, serializable speaker metadata.
    """
    try:
        transport_info = sp.get_current_transport_info()
        state = transport_info.get('current_transport_state', 'UNKNOWN')
    except Exception:
        state = 'UNKNOWN'

    try:
        volume = sp.volume
    except Exception:
        volume = 0

    try:
        track_info = sp.get_current_track_info()
    except Exception:
        track_info = {}

    return {
        'name': sp.player_name,
        'ip': sp.ip_address,
        'uid': sp.uid,
        'volume': volume,
        'is_coordinator': sp.is_coordinator,
        'state': state,
        'current_track': {
            'title': track_info.get('title', ''),
            'artist': track_info.get('artist', ''),
            'album': track_info.get('album', ''),
            'duration': track_info.get('duration', '0:00'),
            'position': track_info.get('position', '0:00'),
            'uri': track_info.get('uri', '')
        }
    }


def play_audio_stream(identifier: str, stream_url: str, title: str, artist: str = "YouTube") -> Dict[str, Any]:
    """
    Set URI and start playback on the specified Sonos speaker.
    Generates DIDL-Lite metadata so track name and artist appear in Sonos controllers.
    """
    sp = get_sonos_by_identifier(identifier)
    if not sp:
        raise ValueError(f"Sonos speaker '{identifier}' not found.")

    # DIDL-Lite metadata template with resource protocolInfo
    meta_template = (
        '<DIDL-Lite xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/" '
        'xmlns:r="urn:schemas-rinconnetworks-com:metadata-1-0/" '
        'xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/">'
        '<item id="-1" parentID="-1" restricted="1">'
        '<res protocolInfo="http-get:*:audio/mp4:*">{uri}</res>'
        '<dc:title>{title}</dc:title>'
        '<dc:creator>{artist}</dc:creator>'
        '<upnp:class>object.item.audioItem.musicTrack</upnp:class>'
        '</item>'
        '</DIDL-Lite>'
    )
    # Basic XML escaping
    clean_title = (title or "YouTube Audio").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    clean_artist = (artist or "YouTube").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    clean_uri = stream_url.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    metadata = meta_template.format(uri=clean_uri, title=clean_title, artist=clean_artist)

    try:
        # Stop existing playback if any
        try:
            sp.stop()
        except Exception:
            pass

        sp.play_uri(stream_url, meta=metadata, title=clean_title)
        return _format_speaker_info(sp)
    except SoCoException as e:
        logger.error(f"SoCo error playing stream on {identifier}: {e}")
        raise RuntimeError(f"Sonos playback failed: {e}")


def control_playback(identifier: str, action: str, value: Optional[int] = None) -> Dict[str, Any]:
    """
    Control playback: play, pause, stop, volume.
    """
    sp = get_sonos_by_identifier(identifier)
    if not sp:
        raise ValueError(f"Sonos speaker '{identifier}' not found.")

    action = action.lower()
    try:
        if action == 'play':
            sp.play()
        elif action == 'pause':
            sp.pause()
        elif action == 'stop':
            sp.stop()
        elif action == 'volume':
            if value is None or not (0 <= value <= 100):
                raise ValueError("Volume must be an integer between 0 and 100.")
            sp.volume = value
        else:
            raise ValueError(f"Unknown playback action: {action}")

        return _format_speaker_info(sp)
    except SoCoException as e:
        logger.error(f"SoCo error controlling {identifier} ({action}): {e}")
        raise RuntimeError(f"Sonos action '{action}' failed: {e}")
