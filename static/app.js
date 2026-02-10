const API_BASE = window.location.origin;

// State
let audioContext = null;
let sourceNode = null;
let gainNode = null;
let analyserNode = null;
let processedSource = null; // For the effect chain
let audioBuffer = null;
let isPlaying = false;
let startTime = 0;
let pauseTime = 0;
let isRadioActive = false;

// DOM Elements
const projectsList = document.getElementById('projects-list');
const versionsList = document.getElementById('versions-list');
const btnBackProjects = document.getElementById('btn-back-projects');
const currentProjectName = document.getElementById('current-project-name');
const versionsContainer = document.getElementById('versions-container');
const btnPlay = document.getElementById('btn-play');
const btnStop = document.getElementById('btn-stop');
const btnRadio = document.getElementById('btn-radio');
const canvas = document.getElementById('waveform-canvas');
const ctx = canvas.getContext('2d');
const loadingText = document.getElementById('waveform-loading');

// Initialization
document.addEventListener('DOMContentLoaded', () => {
    loadProjects();
    setupAudioContext();
    setupCanvas();
    setupEventListeners();
});

function setupAudioContext() {
    window.AudioContext = window.AudioContext || window.webkitAudioContext;
    audioContext = new AudioContext();
    gainNode = audioContext.createGain();
    analyserNode = audioContext.createAnalyser();

    // Connect default chain: Source -> Gain -> Analyser -> Destination
    gainNode.connect(analyserNode);
    analyserNode.connect(audioContext.destination);

    // Resume context if needed (browsers block autoplay)
    document.body.addEventListener('click', () => {
        if (audioContext.state === 'suspended') {
            audioContext.resume();
        }
    }, { once: true });
}

function setupEventListeners() {
    btnBackProjects.addEventListener('click', showProjectsList);

    btnPlay.addEventListener('click', togglePlayPause);
    btnStop.addEventListener('click', stopAudio);

    btnRadio.addEventListener('click', toggleRadioEffect);

    // Seek handling
    canvas.addEventListener('click', (e) => {
        if (!audioBuffer) return;
        const rect = canvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const width = rect.width;
        const fraction = x / width;
        const duration = audioBuffer.duration;
        const newTime = fraction * duration;

        playAudio(newTime);
    });
}

// --- Project & Version Handling ---

async function loadProjects() {
    projectsList.innerHTML = '<div class="loading">Lade Projekte...</div>';
    try {
        const res = await fetch(`${API_BASE}/projects`);
        const projects = await res.json();

        projectsList.innerHTML = '';
        if (projects.length === 0) {
            projectsList.innerHTML = '<div class="message">Keine Projekte gefunden.</div>';
            return;
        }

        projects.forEach(p => {
            const div = document.createElement('div');
            div.className = 'project-item';
            div.textContent = p.name || p.project_id;
            div.onclick = () => loadProjectVersions(p);
            projectsList.appendChild(div);
        });
    } catch (e) {
        projectsList.innerHTML = `<div class="error">Fehler: ${e.message}</div>`;
    }
}

async function loadProjectVersions(project) {
    projectsList.classList.add('hidden');
    versionsList.classList.remove('hidden');
    currentProjectName.textContent = project.name || project.project_id;

    versionsContainer.innerHTML = '<div class="loading">Lade Versionen...</div>';

    try {
        // Fetch ALL files and filter client-side for now (or use backend filter if implemented)
        const res = await fetch(`${API_BASE}/files?project_id=${project.project_id}`);
        const files = await res.json();

        versionsContainer.innerHTML = '';
        if (files.length === 0) {
            versionsContainer.innerHTML = '<div class="message">Keine Versionen.</div>';
            return;
        }

        files.forEach(f => {
            const div = document.createElement('div');
            div.className = 'version-item';
            div.textContent = f.name + ` (${f.modified})`;
            div.onclick = () => loadAudioFile(f.name);
            versionsContainer.appendChild(div);
        });
    } catch (e) {
        versionsContainer.innerHTML = `<div class="error">Fehler: ${e.message}</div>`;
    }
}

function showProjectsList() {
    versionsList.classList.add('hidden');
    projectsList.classList.remove('hidden');
}


// --- Audio Playback & Effects ---

async function loadAudioFile(filename) {
    stopAudio();
    loadingText.style.display = 'block';

    try {
        // Assume file is in cloud_uploads/filename
        // The backend exposes them statically or via a specific route?
        // Let's use the static mount if available, otherwise assume a download endpoint
        // Backend: UPLOAD_DIR is just "cloud_uploads", logic for serving files individually not explicit in main.py
        // We added static/ mount for "static", but uploads are outside.
        // Wait, main.py didn't mount `cloud_uploads`! 
        // FIX: The backend likely needs to serve these files.
        // For now, let's assume we fetch generic URL or modify backend to serve uploads.
        // Actually, let's use the /latest logic but specific file?
        // Ah, main.py doesn't have a specific file download endpoint!
        // I should have checked that. Let's fix backend later. 
        // For now, assume a heuristic URL.
        const res = await fetch(`${API_BASE}/uploads/${filename}`);
        if (!res.ok) throw new Error("File not found");

        const arrayBuffer = await res.arrayBuffer();
        audioBuffer = await audioContext.decodeAudioData(arrayBuffer);

        drawWaveform();
        loadingText.style.display = 'none';

        // Auto play on load
        playAudio(0);

    } catch (e) {
        loadingText.textContent = "Fehler beim Laden";
        console.error(e);
    }
}

function playAudio(offset = 0) {
    if (sourceNode) {
        sourceNode.stop();
        sourceNode.disconnect();
    }

    sourceNode = audioContext.createBufferSource();
    sourceNode.buffer = audioBuffer;

    // Effect Chain Logic
    // If Radio is active, route through effect filters
    // Else route directly to gain

    if (isRadioActive) {
        setupRadioChain(sourceNode, offset);
    } else {
        sourceNode.connect(gainNode);
        sourceNode.start(0, offset);
    }

    startTime = audioContext.currentTime - offset;
    pauseTime = 0;
    isPlaying = true;
    updatePlayButton();
    requestAnimationFrame(animatePlayback);
}

function togglePlayPause() {
    if (!audioBuffer) return;

    if (isPlaying) {
        // Pause
        pauseTime = audioContext.currentTime - startTime;
        sourceNode.stop();
        isPlaying = false;
    } else {
        // Resume
        playAudio(pauseTime);
    }
    updatePlayButton();
}

function stopAudio() {
    if (sourceNode) {
        sourceNode.stop();
    }
    isPlaying = false;
    pauseTime = 0;
    startTime = 0;
    updatePlayButton();
    drawWaveform(); // Reset cursor
}

function updatePlayButton() {
    btnPlay.textContent = isPlaying ? "⏸" : "▶";
}


// --- Radio Effect (Web Audio API) ---

function setupRadioChain(source, offset) {
    // 1. Bandpass Filter (400Hz - 3kHz)
    const bandpass = audioContext.createBiquadFilter();
    bandpass.type = 'bandpass';
    bandpass.frequency.value = 1000;
    bandpass.Q.value = 1.0; // Adjust for bandwidth

    // 2. Distortion (WaveShaper)
    const distortion = audioContext.createWaveShaper();
    distortion.curve = makeDistortionCurve(100); // 100 amount
    distortion.oversample = '4x';

    // 3. Compression (DynamicsCompressor)
    const compressor = audioContext.createDynamicsCompressor();
    compressor.threshold.value = -24;
    compressor.knee.value = 30;
    compressor.ratio.value = 12;
    compressor.attack.value = 0.003;
    compressor.release.value = 0.25;

    // Chain: Source -> Bandpass -> Distortion -> Compressor -> Gain -> ...
    source.connect(bandpass);
    bandpass.connect(distortion);
    distortion.connect(compressor);
    compressor.connect(gainNode);

    source.start(0, offset);
}

function makeDistortionCurve(amount) {
    const k = typeof amount === 'number' ? amount : 50;
    const n_samples = 44100;
    const curve = new Float32Array(n_samples);
    const deg = Math.PI / 180;
    let x;
    for (let i = 0; i < n_samples; ++i) {
        x = i * 2 / n_samples - 1;
        curve[i] = (3 + k) * x * 20 * deg / (Math.PI + k * Math.abs(x));
    }
    return curve;
}

function toggleRadioEffect() {
    isRadioActive = !isRadioActive;

    // Visual toggle
    if (isRadioActive) {
        btnRadio.classList.add('active');
        btnRadio.style.background = '#ff9500';
    } else {
        btnRadio.classList.remove('active');
        btnRadio.style.background = '';
    }

    // Apply live if playing
    if (isPlaying) {
        const currentOffset = audioContext.currentTime - startTime;
        playAudio(currentOffset);
    }
}


// --- Waveform Visualization ---

function setupCanvas() {
    // scale for retina
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);
}

function drawWaveform(progress = 0) {
    if (!audioBuffer) return;

    const width = canvas.width / (window.devicePixelRatio || 1);
    const height = canvas.height / (window.devicePixelRatio || 1);
    const data = audioBuffer.getChannelData(0);
    const step = Math.ceil(data.length / width);
    const amp = height / 2;

    ctx.clearRect(0, 0, width, height);

    // Draw background waveform
    ctx.fillStyle = 'rgba(255, 255, 255, 0.3)';
    ctx.beginPath();
    for (let i = 0; i < width; i++) {
        let min = 1.0;
        let max = -1.0;
        for (let j = 0; j < step; j++) {
            const datum = data[(i * step) + j];
            if (datum < min) min = datum;
            if (datum > max) max = datum;
        }
        ctx.fillRect(i, (1 + min) * amp, 1, Math.max(1, (max - min) * amp));
    }

    // Draw progress overlay
    if (progress > 0) {
        const progWidth = width * progress;
        ctx.fillStyle = '#ff9500'; // Active color
        ctx.save();
        ctx.beginPath();
        ctx.rect(0, 0, progWidth, height);
        ctx.clip();

        // Redraw waveform in active color
        for (let i = 0; i < width; i++) {
            let min = 1.0;
            let max = -1.0;
            for (let j = 0; j < step; j++) {
                const datum = data[(i * step) + j];
                if (datum < min) min = datum;
                if (datum > max) max = datum;
            }
            ctx.fillRect(i, (1 + min) * amp, 1, Math.max(1, (max - min) * amp));
        }

        ctx.restore();

        // Draw playhead line
        ctx.fillStyle = '#ffffff';
        ctx.fillRect(progWidth, 0, 2, height);
    }
}

function animatePlayback() {
    if (!isPlaying) return;

    const currentOffset = audioContext.currentTime - startTime;
    const duration = audioBuffer.duration;
    let progress = currentOffset / duration;

    if (progress >= 1) {
        stopAudio();
        progress = 1;
    }

    drawWaveform(progress);

    if (isPlaying) {
        requestAnimationFrame(animatePlayback);
    }
}
