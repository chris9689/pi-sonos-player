const $ = (id) => document.getElementById(id);

const els = {
  status: $('service-status'),
  speakers: $('speakers-list'),
  refresh: $('refresh-speakers-btn'),
  form: $('url-form'),
  url: $('yt-url'),
  clear: $('clear-btn'),
  paste: $('paste-btn'),
  preview: $('video-preview'),
  thumb: $('preview-thumb'),
  title: $('preview-title'),
  channel: $('preview-channel'),
  play: $('play-btn'),
  playText: $('play-btn-text'),
  toggle: $('btn-toggle'),
  iconPlay: $('icon-play'),
  iconPause: $('icon-pause'),
  stop: $('btn-stop'),
  volume: $('volume-slider'),
  volumeVal: $('volume-val'),
  pulse: $('playback-pulse'),
  npTitle: $('np-title'),
  npSub: $('np-sub'),
  toast: $('toast'),
};

const STORAGE_KEY = 'pi-sonos-speaker';
const ID_RE = /(?:[?&]v=|youtu\.be\/|\/(?:shorts|embed|live)\/)([\w-]{11})/;

let speakers = [];
let selected = null;          // { name, ip, uid }
let videoId = null;
let infoRequest = 0;
let playerState = 'IDLE';
let volumeTimer = null;
let volumeTouchedAt = 0;
let pollTimer = null;
let toastTimer = null;

// ---------- helpers ----------
function parseVideoId(text) {
  text = (text || '').trim();
  if (/^[\w-]{11}$/.test(text)) return text;
  const m = text.match(ID_RE);
  return m ? m[1] : null;
}

function toast(message, type = 'error', ms = 4000) {
  els.toast.textContent = message;
  els.toast.className = `toast ${type}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => els.toast.classList.add('hidden'), ms);
}

async function api(path, body) {
  const opts = body
    ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
    : {};
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.status !== 'ok') throw new Error(data.message || `Request failed (${res.status})`);
  return data;
}

function setVolumeUI(v) {
  if (v === null || v === undefined) return;
  els.volume.value = v;
  els.volume.style.setProperty('--fill', `${v}%`);
  els.volumeVal.textContent = v;
}

// ---------- health ----------
async function checkHealth() {
  try {
    await api('/api/health');
    els.status.className = 'status-dot online';
    els.status.title = 'Online';
  } catch {
    els.status.className = 'status-dot offline';
    els.status.title = 'Offline';
  }
}

// ---------- speakers ----------
function renderSpeakers() {
  els.speakers.replaceChildren();
  if (!speakers.length) {
    const div = document.createElement('div');
    div.className = 'empty';
    div.textContent = 'No speakers found. Make sure they are on the same network, then rescan.';
    els.speakers.append(div);
    return;
  }
  for (const sp of speakers) {
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'chip';
    chip.setAttribute('role', 'radio');
    chip.setAttribute('aria-checked', String(selected?.uid === sp.uid));
    chip.textContent = sp.name;
    chip.addEventListener('click', () => selectSpeaker(sp));
    els.speakers.append(chip);
  }
}

async function loadSpeakers(force = false) {
  els.refresh.classList.add('spinning');
  try {
    const data = await api(`/api/speakers?force=${force}`);
    speakers = data.speakers || [];
    const saved = localStorage.getItem(STORAGE_KEY);
    const match = speakers.find(s => s.uid === selected?.uid)
      || speakers.find(s => s.uid === saved)
      || (speakers.length === 1 ? speakers[0] : null);
    renderSpeakers();
    if (match) selectSpeaker(match);
  } catch (err) {
    speakers = [];
    renderSpeakers();
    toast(`Speaker discovery failed: ${err.message}`);
  } finally {
    els.refresh.classList.remove('spinning');
  }
}

function selectSpeaker(sp) {
  selected = sp;
  localStorage.setItem(STORAGE_KEY, sp.uid);
  els.speakers.querySelectorAll('.chip').forEach((chip, i) => {
    chip.setAttribute('aria-checked', String(speakers[i]?.uid === sp.uid));
  });
  els.volume.disabled = false;
  els.toggle.disabled = false;
  els.stop.disabled = false;
  els.npSub.textContent = sp.name;
  updatePlayButton();
  pollStatus();
}

// ---------- video ----------
function updatePlayButton() {
  els.play.disabled = !(selected && videoId);
  if (!selected) els.playText.textContent = 'Select a speaker';
  else if (!videoId) els.playText.textContent = 'Paste a YouTube link';
  else els.playText.textContent = `Play on ${selected.name}`;
}

async function onUrlChanged() {
  const raw = els.url.value;
  els.clear.classList.toggle('hidden', !raw);
  els.paste.classList.toggle('hidden', !!raw || !navigator.clipboard?.readText);

  const id = parseVideoId(raw);
  if (id === videoId) return;
  videoId = id;
  updatePlayButton();

  if (!id) {
    els.preview.classList.add('hidden');
    return;
  }

  // Thumbnail is loaded by the phone directly from YouTube's CDN (no Pi work)
  els.thumb.src = `https://i.ytimg.com/vi/${id}/mqdefault.jpg`;
  els.title.textContent = 'Loading title…';
  els.channel.textContent = '';
  els.preview.classList.add('loading');
  els.preview.classList.remove('hidden');

  const req = ++infoRequest;
  try {
    const { info } = await api('/api/info', { url: id });
    if (req !== infoRequest) return;
    els.title.textContent = info.title;
    els.channel.textContent = info.channel || '';
  } catch {
    if (req !== infoRequest) return;
    els.title.textContent = 'YouTube video';
  } finally {
    if (req === infoRequest) els.preview.classList.remove('loading');
  }
}

async function startPlayback(e) {
  e?.preventDefault();
  if (!selected || !videoId) return;

  els.play.disabled = true;
  els.play.classList.add('busy');
  els.playText.textContent = 'Starting…';
  try {
    const data = await api('/api/play', { speaker: selected.ip, url: videoId });
    renderStatus(data.speaker, data.track);
    toast(`Playing on ${selected.name}`, 'success', 2500);
    els.url.blur();
  } catch (err) {
    toast(`Playback failed: ${err.message}`);
  } finally {
    els.play.classList.remove('busy');
    updatePlayButton();
  }
}

// ---------- transport ----------
async function sendControl(action, value) {
  if (!selected) return;
  try {
    const data = await api('/api/control', { speaker: selected.ip, action, value });
    renderStatus(data.speaker);
  } catch (err) {
    toast(err.message);
  }
}

function renderStatus(sp, track) {
  if (!sp) return;
  playerState = sp.state || 'IDLE';
  const playing = playerState === 'PLAYING' || playerState === 'TRANSITIONING';

  els.pulse.classList.toggle('active', playing);
  els.iconPlay.classList.toggle('hidden', playing);
  els.iconPause.classList.toggle('hidden', !playing);

  const t = track || sp.current_track || {};
  els.npTitle.textContent = t.title || (playerState === 'STOPPED' ? 'Stopped' : 'Nothing playing');
  const stateLabel = { PLAYING: 'Playing', PAUSED_PLAYBACK: 'Paused', STOPPED: 'Stopped', TRANSITIONING: 'Buffering…' }[playerState] || '';
  els.npSub.textContent = [sp.name, stateLabel].filter(Boolean).join(' · ');

  // Don't fight the user while they drag the slider
  if (Date.now() - volumeTouchedAt > 1500) setVolumeUI(sp.volume);
}

async function pollStatus() {
  if (!selected || document.hidden) return;
  try {
    const data = await api(`/api/status?speaker=${encodeURIComponent(selected.ip)}`);
    renderStatus(data.speaker);
  } catch { /* transient */ }
}

function startPolling() {
  clearInterval(pollTimer);
  pollTimer = setInterval(pollStatus, 5000);
}

// ---------- events ----------
els.refresh.addEventListener('click', () => loadSpeakers(true));
els.form.addEventListener('submit', startPlayback);
els.url.addEventListener('input', onUrlChanged);

els.clear.addEventListener('click', () => {
  els.url.value = '';
  onUrlChanged();
  els.url.focus();
});

els.paste.addEventListener('click', async () => {
  try {
    els.url.value = await navigator.clipboard.readText();
    onUrlChanged();
  } catch {
    els.url.focus();
  }
});

els.toggle.addEventListener('click', () => {
  sendControl(playerState === 'PLAYING' ? 'pause' : 'play');
});
els.stop.addEventListener('click', () => sendControl('stop'));

els.volume.addEventListener('input', (e) => {
  const v = parseInt(e.target.value, 10);
  volumeTouchedAt = Date.now();
  setVolumeUI(v);
  clearTimeout(volumeTimer);
  volumeTimer = setTimeout(() => sendControl('volume', v), 250);
});

document.addEventListener('visibilitychange', () => {
  if (!document.hidden) { checkHealth(); pollStatus(); }
});

// ---------- init ----------
// Allow sharing links via e.g. http://<pi>:5000/?url=<youtube link> (bookmarklets / phone shortcuts)
const params = new URLSearchParams(location.search);
const shared = params.get('url') || params.get('text') || params.get('v');
if (shared) {
  els.url.value = shared;
  history.replaceState(null, '', location.pathname);
}

onUrlChanged();
checkHealth();
loadSpeakers();
startPolling();
