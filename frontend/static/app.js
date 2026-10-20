// State
let selectedSpeaker = null;
let currentVideoInfo = null;
let pollTimer = null;
let volumeDebounceTimer = null;

// DOM Elements
const serviceStatusEl = document.getElementById('service-status');
const alertBannerEl = document.getElementById('alert-banner');
const speakersListEl = document.getElementById('speakers-list');
const speakersLoadingEl = document.getElementById('speakers-loading');
const refreshSpeakersBtn = document.getElementById('refresh-speakers-btn');

const ytUrlInput = document.getElementById('yt-url');
const loadInfoBtn = document.getElementById('load-info-btn');
const videoPreviewEl = document.getElementById('video-preview');
const previewThumbnailEl = document.getElementById('preview-thumbnail');
const previewTitleEl = document.getElementById('preview-title');
const previewChannelEl = document.getElementById('preview-channel');
const previewDurationEl = document.getElementById('preview-duration');

const playBtn = document.getElementById('play-btn');
const playBtnText = document.getElementById('play-btn-text');

const speakerControlsPanel = document.getElementById('speaker-controls-panel');
const volumeSlider = document.getElementById('volume-slider');
const volumeValEl = document.getElementById('volume-val');
const btnPause = document.getElementById('btn-pause');
const btnResume = document.getElementById('btn-resume');
const btnStop = document.getElementById('btn-stop');

const playbackPulse = document.getElementById('playback-pulse');
const playbackStateBadge = document.getElementById('playback-state-badge');
const npTitleEl = document.getElementById('np-title');
const npSpeakerEl = document.getElementById('np-speaker');


// Helper: Show Alert
function showAlert(message, type = 'error', timeout = 6000) {
  alertBannerEl.textContent = message;
  alertBannerEl.className = `alert-banner ${type}`;
  alertBannerEl.classList.remove('hidden');

  if (timeout) {
    setTimeout(() => {
      alertBannerEl.classList.add('hidden');
    }, timeout);
  }
}

function clearAlert() {
  alertBannerEl.classList.add('hidden');
}


// Check Health
async function checkHealth() {
  try {
    const res = await fetch('/api/health');
    if (res.ok) {
      serviceStatusEl.textContent = 'Online';
      serviceStatusEl.className = 'badge badge-online';
    } else {
      throw new Error();
    }
  } catch (err) {
    serviceStatusEl.textContent = 'Offline';
    serviceStatusEl.className = 'badge badge-offline';
  }
}


// Load Sonos Speakers
async function loadSpeakers(force = false) {
  speakersLoadingEl.classList.remove('hidden');
  speakersListEl.innerHTML = '';

  try {
    const res = await fetch(`/api/speakers?force=${force}`);
    const data = await res.json();

    speakersLoadingEl.classList.add('hidden');

    if (data.status !== 'ok' || !data.speakers || data.speakers.length === 0) {
      speakersListEl.innerHTML = '<div class="np-sub">No Sonos speakers discovered. Ensure they are powered on and on this Wi-Fi/LAN.</div>';
      return;
    }

    data.speakers.forEach(sp => {
      const item = document.createElement('div');
      item.className = 'speaker-item';
      if (selectedSpeaker && selectedSpeaker.ip === sp.ip) {
        item.classList.add('selected');
        selectedSpeaker = sp; // update state
      }

      item.innerHTML = `
        <div>
          <div class="speaker-name">${sp.name}</div>
          <div class="speaker-ip">${sp.ip}</div>
        </div>
        <div class="speaker-state">${sp.state || ''}</div>
      `;

      item.addEventListener('click', () => selectSpeaker(sp));
      speakersListEl.appendChild(item);
    });

    // Auto-select first speaker if none selected
    if (!selectedSpeaker && data.speakers.length > 0) {
      selectSpeaker(data.speakers[0]);
    }
  } catch (err) {
    speakersLoadingEl.classList.add('hidden');
    showAlert(`Failed to discover Sonos speakers: ${err.message}`);
  }
}


// Select a Speaker
function selectSpeaker(speaker) {
  selectedSpeaker = speaker;

  // Update UI selection
  const items = speakersListEl.querySelectorAll('.speaker-item');
  items.forEach(el => {
    if (el.querySelector('.speaker-name').textContent === speaker.name) {
      el.classList.add('selected');
    } else {
      el.classList.remove('selected');
    }
  });

  // Enable controls panel
  speakerControlsPanel.classList.remove('disabled');
  volumeSlider.value = speaker.volume || 20;
  volumeValEl.textContent = speaker.volume || 20;

  updatePlayButton();
  updateNowPlaying(speaker);
}


// Update Play Button State
function updatePlayButton() {
  if (!selectedSpeaker) {
    playBtn.disabled = true;
    playBtnText.textContent = '1. Select a Sonos speaker';
  } else if (!ytUrlInput.value.trim()) {
    playBtn.disabled = true;
    playBtnText.textContent = '2. Paste a YouTube URL';
  } else {
    playBtn.disabled = false;
    playBtnText.textContent = `▶ Play on ${selectedSpeaker.name}`;
  }
}


// Load Video Info
async function fetchVideoInfo() {
  const url = ytUrlInput.value.trim();
  if (!url) return;

  clearAlert();
  loadInfoBtn.disabled = true;
  loadInfoBtn.textContent = 'Loading...';

  try {
    const res = await fetch('/api/info', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url })
    });
    const data = await res.json();

    if (data.status !== 'ok') {
      throw new Error(data.message || 'Could not fetch video info.');
    }

    currentVideoInfo = data.info;
    previewThumbnailEl.src = currentVideoInfo.thumbnail || '';
    previewTitleEl.textContent = currentVideoInfo.title;
    previewChannelEl.textContent = currentVideoInfo.channel;
    previewDurationEl.textContent = currentVideoInfo.duration_formatted;
    videoPreviewEl.classList.remove('hidden');

    updatePlayButton();
  } catch (err) {
    videoPreviewEl.classList.add('hidden');
    showAlert(err.message);
  } finally {
    loadInfoBtn.disabled = false;
    loadInfoBtn.textContent = 'Fetch Info';
  }
}


// Play Audio on Speaker
async function startPlayback() {
  if (!selectedSpeaker || !ytUrlInput.value.trim()) return;

  clearAlert();
  playBtn.disabled = true;
  playBtnText.textContent = 'Starting stream on Sonos...';

  try {
    const res = await fetch('/api/play', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        speaker: selectedSpeaker.ip,
        url: ytUrlInput.value.trim()
      })
    });
    const data = await res.json();

    if (data.status !== 'ok') {
      throw new Error(data.message || 'Playback failed.');
    }

    showAlert(`Playing "${data.track.title}" on ${selectedSpeaker.name}`, 'success');
    updateNowPlaying(data.speaker, data.track);
  } catch (err) {
    showAlert(`Playback error: ${err.message}`);
  } finally {
    updatePlayButton();
  }
}


// Send Transport Control
async function sendControl(action, value = null) {
  if (!selectedSpeaker) return;

  try {
    const res = await fetch('/api/control', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        speaker: selectedSpeaker.ip,
        action: action,
        value: value
      })
    });
    const data = await res.json();

    if (data.status === 'ok') {
      updateNowPlaying(data.speaker);
    }
  } catch (err) {
    showAlert(`Control error: ${err.message}`);
  }
}


// Update Now Playing Display
function updateNowPlaying(speaker, track = null) {
  if (!speaker) return;

  const state = speaker.state || 'IDLE';
  playbackStateBadge.textContent = state;

  if (state === 'PLAYING') {
    playbackStateBadge.className = 'badge badge-playing';
    playbackPulse.classList.add('active');
  } else {
    playbackStateBadge.className = 'badge badge-idle';
    playbackPulse.classList.remove('active');
  }

  npSpeakerEl.textContent = `Speaker: ${speaker.name} (${speaker.ip})`;

  const curTrack = track || speaker.current_track;
  if (curTrack && curTrack.title) {
    npTitleEl.textContent = `${curTrack.title} — ${curTrack.artist || 'YouTube'}`;
  } else if (state === 'STOPPED') {
    npTitleEl.textContent = 'Playback stopped';
  }
}


// Poll Active Speaker Status
async function pollSpeakerStatus() {
  if (!selectedSpeaker) return;

  try {
    const res = await fetch(`/api/status?speaker=${encodeURIComponent(selectedSpeaker.ip)}`);
    const data = await res.json();
    if (data.status === 'ok') {
      selectedSpeaker = data.speaker;
      updateNowPlaying(data.speaker);
    }
  } catch (e) {
    // Silent fail on routine poll
  }
}


// Event Listeners
refreshSpeakersBtn.addEventListener('click', () => loadSpeakers(true));

ytUrlInput.addEventListener('input', () => {
  updatePlayButton();
});

ytUrlInput.addEventListener('paste', () => {
  setTimeout(fetchVideoInfo, 100);
});

loadInfoBtn.addEventListener('click', fetchVideoInfo);
playBtn.addEventListener('click', startPlayback);

btnPause.addEventListener('click', () => sendControl('pause'));
btnResume.addEventListener('click', () => sendControl('play'));
btnStop.addEventListener('click', () => sendControl('stop'));

volumeSlider.addEventListener('input', (e) => {
  const val = parseInt(e.target.value, 10);
  volumeValEl.textContent = val;

  clearTimeout(volumeDebounceTimer);
  volumeDebounceTimer = setTimeout(() => {
    sendControl('volume', val);
  }, 250);
});


// Initialization
checkHealth();
loadSpeakers();
setInterval(pollSpeakerStatus, 4000);
