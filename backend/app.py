import os
import socket
import logging
import requests
from flask import Flask, request, jsonify, render_template, Response, stream_with_context
from dotenv import load_dotenv

from youtube import extract_video_id, get_video_info, get_audio_stream_info
from sonos_controller import discover_speakers, play_audio_stream, control_playback, get_sonos_by_identifier, _format_speaker_info

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger("pi-sonos-player")

app = Flask(
    __name__,
    template_folder=os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'frontend', 'templates')),
    static_folder=os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'frontend', 'static'))
)

PORT = int(os.environ.get("PORT", 5000))
HOST = os.environ.get("HOST", "0.0.0.0")


def get_local_ip() -> str:
    """Detect LAN IP address of this Raspberry Pi."""
    env_ip = os.environ.get("PI_IP")
    if env_ip:
        return env_ip

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Connect to an external address (doesn't send packets) to find the primary interface IP
        s.connect(('1.1.1.1', 80))
        return s.getsockname()[0]
    except Exception:
        return '127.0.0.1'
    finally:
        s.close()


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/health')
def health():
    return jsonify({
        'status': 'ok',
        'service': 'pi-sonos-player',
        'local_ip': get_local_ip(),
        'port': PORT
    })


@app.route('/api/speakers', methods=['GET'])
def get_speakers():
    force = request.args.get('force', 'false').lower() == 'true'
    try:
        speakers = discover_speakers(force=force)
        return jsonify({'status': 'ok', 'speakers': speakers})
    except Exception as e:
        logger.error(f"Error fetching speakers: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/info', methods=['POST'])
def video_info():
    data = request.get_json() or {}
    url = data.get('url', '').strip()
    if not url:
        return jsonify({'status': 'error', 'message': 'Please provide a YouTube URL.'}), 400

    video_id = extract_video_id(url)
    if not video_id:
        return jsonify({'status': 'error', 'message': 'Invalid YouTube URL format.'}), 400

    try:
        info = get_video_info(video_id)
        return jsonify({'status': 'ok', 'info': info})
    except Exception as e:
        logger.warning(f"Error fetching video info: {e}")
        return jsonify({'status': 'error', 'message': f"Could not load video info: {str(e)}"}), 400


@app.route('/api/play', methods=['POST'])
def play():
    data = request.get_json() or {}
    speaker_id = data.get('speaker', '').strip()
    url = data.get('url', '').strip()

    if not speaker_id:
        return jsonify({'status': 'error', 'message': 'No Sonos speaker selected.'}), 400

    if not url:
        return jsonify({'status': 'error', 'message': 'No YouTube URL provided.'}), 400

    video_id = extract_video_id(url)
    if not video_id:
        return jsonify({'status': 'error', 'message': 'Invalid YouTube URL format.'}), 400

    try:
        # Retrieve track info for display
        info = get_video_info(video_id)
        title = info.get('title', 'YouTube Audio')
        artist = info.get('channel', 'YouTube')

        local_ip = get_local_ip()
        stream_url = f"http://{local_ip}:{PORT}/api/stream/{video_id}.m4a"

        logger.info(f"Commanding Sonos '{speaker_id}' to play stream: {stream_url}")
        status = play_audio_stream(speaker_id, stream_url, title, artist)

        return jsonify({
            'status': 'ok',
            'speaker': status,
            'track': info,
            'stream_url': stream_url
        })
    except Exception as e:
        logger.error(f"Playback error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/control', methods=['POST'])
def control():
    data = request.get_json() or {}
    speaker_id = data.get('speaker', '').strip()
    action = data.get('action', '').strip().lower()
    value = data.get('value')

    if not speaker_id:
        return jsonify({'status': 'error', 'message': 'No speaker specified.'}), 400

    if action not in ('play', 'pause', 'stop', 'volume'):
        return jsonify({'status': 'error', 'message': f"Invalid action: '{action}'"}), 400

    try:
        status = control_playback(speaker_id, action, value)
        return jsonify({'status': 'ok', 'speaker': status})
    except Exception as e:
        logger.error(f"Control error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/status', methods=['GET'])
def speaker_status():
    speaker_id = request.args.get('speaker', '').strip()
    if not speaker_id:
        return jsonify({'status': 'error', 'message': 'No speaker specified.'}), 400

    sp = get_sonos_by_identifier(speaker_id)
    if not sp:
        return jsonify({'status': 'error', 'message': f"Speaker '{speaker_id}' not found."}), 404

    return jsonify({'status': 'ok', 'speaker': _format_speaker_info(sp)})


@app.route('/api/stream/<path:video_id>')
def stream_audio(video_id):
    """
    HTTP Audio Stream Proxy for Sonos UPnP playback.
    Fetches the direct YouTube audio stream and pipes it to Sonos,
    forwarding HTTP Range requests for seamless seeking and buffering.
    """
    # Strip audio extension if passed (e.g. .m4a or .mp3)
    for ext in ('.m4a', '.mp3', '.mp4', '.aac', '.webm'):
        if video_id.endswith(ext):
            video_id = video_id[:-len(ext)]
            break

    if not extract_video_id(video_id):
        return "Invalid video ID", 400

    try:
        stream_info = get_audio_stream_info(video_id)
        upstream_url = stream_info['stream_url']
        mime_type = stream_info.get('mime_type', 'audio/mp4')
    except Exception as e:
        logger.error(f"Failed to get audio stream for {video_id}: {e}")
        return f"Stream extraction error: {e}", 502

    # Forward Range header if requested by Sonos
    req_headers = {}
    if 'Range' in request.headers:
        req_headers['Range'] = request.headers['Range']

    try:
        upstream_res = requests.get(
            upstream_url,
            headers=req_headers,
            stream=True,
            timeout=(5, 30)
        )
    except Exception as e:
        logger.error(f"Failed to connect to upstream audio stream: {e}")
        return "Upstream connection failed", 502

    def generate_chunks():
        try:
            for chunk in upstream_res.iter_content(chunk_size=65536):
                if chunk:
                    yield chunk
        finally:
            upstream_res.close()

    # Pass relevant headers to Sonos
    resp_headers = {
        'Content-Type': mime_type,
        'Accept-Ranges': 'bytes',
        'Cache-Control': 'no-cache'
    }

    if 'Content-Length' in upstream_res.headers:
        resp_headers['Content-Length'] = upstream_res.headers['Content-Length']
    if 'Content-Range' in upstream_res.headers:
        resp_headers['Content-Range'] = upstream_res.headers['Content-Range']

    return Response(
        stream_with_context(generate_chunks()),
        status=upstream_res.status_code,
        headers=resp_headers
    )


if __name__ == '__main__':
    logger.info(f"Starting Pi-Sonos-Player on http://{HOST}:{PORT}")
    app.run(host=HOST, port=PORT, threaded=True)
