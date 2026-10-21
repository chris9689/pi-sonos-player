import os
import re
import socket
import logging

from flask import Flask, request, jsonify, render_template, Response, stream_with_context
from dotenv import load_dotenv

from youtube import extract_video_id, get_video_info, get_audio_stream_info, prefetch_stream, http
from sonos_controller import (
    discover_speakers, play_audio_stream, control_playback,
    get_sonos_by_identifier, format_speaker_status,
)

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger("pi-sonos-player")

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'frontend'))
app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, 'templates'),
    static_folder=os.path.join(BASE_DIR, 'static'),
)

PORT = int(os.environ.get("PORT", 5000))
HOST = os.environ.get("HOST", "0.0.0.0")
THREADS = int(os.environ.get("THREADS", 8))

# googlevideo throttles/rejects large single range requests; fetch upstream in slices
UPSTREAM_CHUNK = 8 * 1024 * 1024
RANGE_REGEX = re.compile(r'^bytes=(\d*)-(\d*)$')


def get_local_ip(target_ip: str = '1.1.1.1') -> str:
    """LAN IP of this host on the route towards target_ip (no packets are sent)."""
    env_ip = os.environ.get("PI_IP")
    if env_ip:
        return env_ip

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((target_ip, 1400))
        return s.getsockname()[0]
    except Exception:
        return '127.0.0.1'
    finally:
        s.close()


def error(message: str, code: int):
    return jsonify({'status': 'error', 'message': message}), code


def resolve_speaker(speaker_id: str):
    if not speaker_id:
        return None, error('No Sonos speaker selected.', 400)
    sp = get_sonos_by_identifier(speaker_id)
    if not sp:
        return None, error(f"Speaker '{speaker_id}' not found.", 404)
    return sp, None


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/health')
def health():
    return jsonify({'status': 'ok', 'service': 'pi-sonos-player'})


@app.route('/api/speakers')
def get_speakers():
    force = request.args.get('force', 'false').lower() == 'true'
    try:
        return jsonify({'status': 'ok', 'speakers': discover_speakers(force=force)})
    except Exception as e:
        logger.error(f"Error fetching speakers: {e}")
        return error(str(e), 500)


@app.route('/api/info', methods=['POST'])
def video_info():
    url = (request.get_json(silent=True) or {}).get('url', '').strip()
    video_id = extract_video_id(url)
    if not video_id:
        return error('Invalid YouTube URL.', 400)

    # Resolve the stream now so pressing Play starts quickly
    prefetch_stream(video_id)
    try:
        return jsonify({'status': 'ok', 'info': get_video_info(video_id)})
    except Exception as e:
        logger.warning(f"Error fetching video info: {e}")
        return error(f"Could not load video info: {e}", 400)


@app.route('/api/play', methods=['POST'])
def play():
    data = request.get_json(silent=True) or {}
    video_id = extract_video_id(data.get('url', '').strip())
    if not video_id:
        return error('Invalid YouTube URL.', 400)

    sp, err = resolve_speaker(data.get('speaker', '').strip())
    if err:
        return err

    try:
        prefetch_stream(video_id)
        info = get_video_info(video_id)
        stream_url = f"http://{get_local_ip(sp.ip_address)}:{PORT}/api/stream/{video_id}.m4a"

        logger.info(f"Playing '{info['title']}' on {sp.player_name}: {stream_url}")
        status = play_audio_stream(sp, stream_url, info['title'], info['channel'])
        return jsonify({'status': 'ok', 'speaker': status, 'track': info})
    except Exception as e:
        logger.error(f"Playback error: {e}")
        return error(str(e), 500)


@app.route('/api/control', methods=['POST'])
def control():
    data = request.get_json(silent=True) or {}
    action = str(data.get('action', '')).strip().lower()
    if action not in ('play', 'pause', 'stop', 'volume'):
        return error(f"Invalid action: '{action}'", 400)

    sp, err = resolve_speaker(str(data.get('speaker', '')).strip())
    if err:
        return err

    try:
        return jsonify({'status': 'ok', 'speaker': control_playback(sp, action, data.get('value'))})
    except ValueError as e:
        return error(str(e), 400)
    except Exception as e:
        logger.error(f"Control error: {e}")
        return error(str(e), 500)


@app.route('/api/status')
def speaker_status():
    sp, err = resolve_speaker(request.args.get('speaker', '').strip())
    if err:
        return err
    return jsonify({'status': 'ok', 'speaker': format_speaker_status(sp)})


def _parse_range(header: str, total: int):
    match = RANGE_REGEX.match(header.strip())
    if not match:
        return None
    start_s, end_s = match.groups()
    if start_s == '':
        if end_s == '':
            return None
        start, end = max(total - int(end_s), 0), total - 1
    else:
        start = int(start_s)
        end = min(int(end_s), total - 1) if end_s else total - 1
    return (start, end) if start <= end else None


@app.route('/api/stream/<name>', methods=['GET', 'HEAD'])
def stream_audio(name):
    """
    Audio proxy for Sonos: serves the YouTube audio stream with Range support,
    fetching upstream in slices and transparently refreshing expired URLs.
    """
    video_id = extract_video_id(name.rsplit('.', 1)[0])
    if not video_id:
        return "Invalid video ID", 400

    try:
        info = get_audio_stream_info(video_id)
    except Exception as e:
        logger.error(f"Failed to resolve audio stream for {video_id}: {e}")
        return "Stream extraction error", 502

    total = info.get('filesize')
    if not total:
        return "Stream size unknown", 502

    headers = {
        'Content-Type': info['mime_type'],
        'Accept-Ranges': 'bytes',
        'Cache-Control': 'no-cache',
    }

    status = 200
    start, end = 0, total - 1
    if 'Range' in request.headers:
        byte_range = _parse_range(request.headers['Range'], total)
        if not byte_range:
            return Response(status=416, headers={'Content-Range': f'bytes */{total}'})
        start, end = byte_range
        status = 206
        headers['Content-Range'] = f'bytes {start}-{end}/{total}'

    headers['Content-Length'] = str(end - start + 1)

    if request.method == 'HEAD':
        return Response(status=status, headers=headers)

    def generate():
        pos = start
        refreshed = False
        while pos <= end:
            current = get_audio_stream_info(video_id, refresh=refreshed)
            chunk_end = min(pos + UPSTREAM_CHUNK - 1, end)
            upstream = http.get(
                current['stream_url'],
                headers={**current['http_headers'], 'Range': f'bytes={pos}-{chunk_end}'},
                stream=True,
                timeout=(5, 30),
            )
            try:
                if upstream.status_code in (403, 410) and not refreshed:
                    logger.info(f"Upstream URL rejected ({upstream.status_code}), refreshing {video_id}")
                    refreshed = True
                    continue
                if upstream.status_code != 206:
                    logger.error(f"Unexpected upstream status {upstream.status_code} for {video_id}")
                    return
                received = 0
                for chunk in upstream.iter_content(chunk_size=64 * 1024):
                    received += len(chunk)
                    pos += len(chunk)
                    yield chunk
                if not received:
                    return
                refreshed = False
            finally:
                upstream.close()

    return Response(stream_with_context(generate()), status=status, headers=headers)


if __name__ == '__main__':
    if os.environ.get("FLASK_DEBUG") == "1":
        app.run(host=HOST, port=PORT, threaded=True, debug=True)
    else:
        from waitress import serve
        logger.info(f"Starting Pi-Sonos-Player on http://{HOST}:{PORT} ({THREADS} threads)")
        serve(app, host=HOST, port=PORT, threads=THREADS, channel_timeout=300, ident=None)
