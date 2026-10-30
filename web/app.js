'use strict';
const $ = id => document.getElementById(id);
const state = {upload: null, localObject: null, capabilities: null, jobs: [], resultJob: null, hasComparison: false, view: 'source'};
const defaults = {
    'Faithful': [0.70, 0.75, 0.75, -1], 'Natural': [1, 1, 1, -1],
    'Strong / Cinematic': [1.65, 1.40, 1.50, 1], 'Extreme / Overdrive': [2.50, 2, 2, 1.50]
};
const sliders = [
    ['intensity', 'intensityValue'], ['localTone', 'localToneValue'],
    ['localStructure', 'localStructureValue'], ['skinStructure', 'skinStructureValue']
];
async function jsonRequest(path, options = {}) {
    const response = await fetch(path, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status})`);
    return data;
}
function showError(error) {
    $('errorBox').hidden = false;
    $('errorBox').textContent = error.message || String(error);
    $('errorBox').scrollIntoView({block: 'nearest', behavior: 'smooth'});
}
function clearError() { $('errorBox').hidden = true; $('errorBox').textContent = ''; }
function selectTab(name) {
    document.querySelectorAll('[data-tab]').forEach(btn => {
        const active = btn.dataset.tab === name;
        btn.classList.toggle('active', active);
        btn.setAttribute('aria-selected', String(active));
    });
    document.querySelectorAll('[data-page]').forEach(page => {page.hidden = page.dataset.page !== name;});
}
document.querySelectorAll('[data-tab]').forEach(btn => btn.addEventListener('click', () => selectTab(btn.dataset.tab)));
function parseClips() {
    const lines = $('clips').value.trim().split(/\r?\n/).map(v => v.trim()).filter(Boolean);
    return lines.map(line => {
        const match = line.match(/^(\d+(?:\.\d+)?)\s*-\s*(end|\d+(?:\.\d+)?)$/i);
        if (!match) {selectTab('cut');throw new Error(`Invalid interval "${line}". Use 0-547 or 945-end.`);}
        return {start: Number(match[1]), end: match[2].toLowerCase() === 'end' ? null : Number(match[2])};
    });
}
function renderOptions() {
    return {
        profile: $('profile').value, codec: $('codec').value, container: $('container').value,
        quality: $('quality').value, warmup_frames: Number($('warmup').value),
        export_preset: $('exportPreset').value, target_fps: $('targetFps').value,
        clips: parseClips(),
        intensity: Number($('intensity').value), local_tone: Number($('localTone').value),
        local_structure: Number($('localStructure').value), skin_structure: Number($('skinStructure').value)
    };
}
function updateSliders() {for (const [id, out] of sliders) $(out).textContent = Number($(id).value).toFixed(2);}
const exportRecipes = {
    'HEVC Main10 - Maximum quality (CQ18)': ['H.265', 'Maximum quality', 'HEVC Main10 · P7 · CQ18. Larger files; best detail retention.', 'HEVC'],
    'HEVC Main10 - Balanced (CQ20)': ['H.265', 'Balanced quality', 'HEVC Main10 · P7 · CQ20. High quality with efficient file sizes.', 'HEVC'],
    'HEVC Main10 - Smaller files (CQ24)': ['H.265', 'Smaller files', 'HEVC Main10 · P7 · CQ24. More compression, reduced file size.', 'HEVC'],
    'H.264 - Compatible (CQ20)': ['H.264', 'Compatible output', 'H.264 · P6 · CQ20. Broad video-player compatibility.', 'H.264'],
    'AV1 - Efficient (CQ20)': ['AV1', 'Efficient AV1', 'AV1 · P6 · CQ20. Requires an NVIDIA AV1 encoder and a capable player.', 'AV1'],
};
function updateExportRecipe() {
    const selected = $('exportPreset').value;
    const recipe = exportRecipes[selected];
    const custom = !recipe;
    $('customExportFields').hidden = !custom;
    if (recipe) {
        $('codec').value = recipe[3];
        $('container').value = 'MP4';
        $('quality').value = 'Balanced';
        $('recipeIcon').textContent = recipe[0];
        $('recipeTitle').textContent = recipe[1];
        $('recipeDescription').textContent = recipe[2];
    } else {
        $('recipeIcon').textContent = 'TUNE';
        $('recipeTitle').textContent = 'Custom encoding';
        $('recipeDescription').textContent = 'Choose a codec, container and quality. The DLSS processing engine stays the same.';
    }
}
$('exportPreset').addEventListener('change', updateExportRecipe);
$('profile').addEventListener('change', () => {
    defaults[$('profile').value].forEach((value, i) => $(sliders[i][0]).value = value);
    updateSliders();
});
sliders.forEach(([id]) => $(id).addEventListener('input', updateSliders));
function setView(mode) {
    state.view = mode;
    $('dropzone').hidden = Boolean(state.upload || state.resultJob);
    $('sourcePlayer').hidden = mode !== 'source' || !state.upload;
    $('resultPlayer').hidden = mode !== 'result' || !state.resultJob;
    $('previewArea').hidden = mode !== 'compare' || !state.hasComparison;
    if (mode !== 'source') $('sourcePlayer').pause();
    if (mode !== 'result') $('resultPlayer').pause();
    $('viewSource').disabled = !state.upload;
    $('viewOutput').disabled = !state.resultJob;
    $('viewCompare').disabled = !state.hasComparison;
    $('stageMode').textContent = mode === 'result' ? 'OUTPUT / H.264 SAMPLE' : mode === 'compare' ? 'FRAME COMPARISON' : state.upload ? 'SOURCE / READY' : 'NO SOURCE';
    [['source','viewSource'], ['result','viewOutput'], ['compare','viewCompare']].forEach(([v,id]) => $(id).classList.toggle('selected', mode === v));
}
$('viewSource').addEventListener('click', () => setView('source'));
$('viewOutput').addEventListener('click', () => setView('result'));
$('viewCompare').addEventListener('click', () => setView('compare'));
function refreshButtons() {
    const available = Boolean(state.upload && state.capabilities?.render_available);
    $('renderButton').disabled = !available;
    $('previewButton').disabled = !available || !state.capabilities?.preview_available;
    $('viewSource').disabled = !state.upload;
}
function updateDiagnostics(caps) {
    const gpu = caps.gpus?.[0];
    $('healthGpuName').textContent = gpu?.name || 'No GPU detected';
    $('healthGpuInfo').textContent = gpu
        ? [gpu.driver && `Driver ${gpu.driver}`, gpu.memory_mb && `${(Number(gpu.memory_mb) / 1024).toFixed(1)} GiB VRAM`, gpu.compute_capability && `CUDA ${gpu.compute_capability}`].filter(Boolean).join(' · ')
        : 'NVIDIA GPU not found';

    const renderReady = Boolean(caps.render_available);
    $('healthRender').textContent = renderReady ? 'Available' : 'Unavailable';
    $('healthRenderNote').textContent = caps.reason || 'No additional information';
    $('healthRenderTile').classList.toggle('is-ready', renderReady);
    $('healthRenderTile').classList.toggle('is-unavailable', !renderReady);

    const previewReady = Boolean(caps.preview_available);
    $('healthPreview').textContent = previewReady ? 'Available' : 'Unavailable';
    $('healthPreviewTile').classList.toggle('is-ready', previewReady);
    $('healthPreviewTile').classList.toggle('is-unavailable', !previewReady);

    $('healthFfmpeg').textContent = caps.ffmpeg || 'Not found';
    $('healthFfprobe').textContent = caps.ffprobe || 'Not found';
    $('diagnosticsText').textContent = JSON.stringify(caps, null, 2);
}

async function getCapabilities() {
    try {
        state.capabilities = await jsonRequest('/api/capabilities');
        const caps = state.capabilities;
        $('gpuState').textContent = caps.gpus?.length ? caps.gpus.map(g => g.name).join(', ') : caps.reason || 'Renderer unavailable';
        $('statusDot').classList.toggle('ready', caps.render_available);
        updateDiagnostics(caps);
    } catch (error) {showError(error);} finally {refreshButtons();}
}
function readableTime(s) {
    if (!Number.isFinite(s)) return '00:00';
    s = Math.max(0, Math.floor(s));
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    return (h ? `${h}:` : '') + `${String(m).padStart(2,'0')}:${String(sec).padStart(2,'0')}`;
}
function updatePlayhead() {
    const v = $('sourcePlayer');
    $('timecode').textContent = `${readableTime(v.currentTime)} / ${readableTime(v.duration)}`;
    $('seekSlider').value = v.duration ? String(Math.min(1000, Math.floor(v.currentTime / v.duration * 1000))) : '0';
}
$('sourcePlayer').addEventListener('loadedmetadata', () => {$('seekSlider').disabled = false; updatePlayhead();});
$('sourcePlayer').addEventListener('timeupdate', updatePlayhead);
$('seekSlider').addEventListener('input', () => {
    const v = $('sourcePlayer');
    if (Number.isFinite(v.duration)) v.currentTime = Number($('seekSlider').value) / 1000 * v.duration;
});
function uploadVideo(file) {
    if (!file) return;
    clearError();
    if (state.localObject) URL.revokeObjectURL(state.localObject);
    state.localObject = URL.createObjectURL(file);
    state.upload = null;
    state.resultJob = null;
    state.hasComparison = false;
    $('resultPlayer').removeAttribute('src');
    $('resultPlayer').load();
    $('sourcePlayer').src = state.localObject;
    $('sourceName').textContent = file.name;
    $('sourceSize').textContent = (file.size / 1048576).toFixed(1) + ' MiB';
    $('uploadState').textContent = 'Uploading source…';
    $('dropzone').hidden = true;
    $('sourcePlayer').hidden = false;
    $('uploadProgress').hidden = false;
    $('uploadFill').style.width = '0%';
    setView('source'); refreshButtons();
    const form = new FormData(); form.append('file', file);
    const xhr = new XMLHttpRequest(); xhr.open('POST', '/api/uploads');
    xhr.upload.onprogress = event => {if (event.lengthComputable) {
        const percent = event.loaded / event.total * 100;
        $('uploadFill').style.width = percent.toFixed(1) + '%';
        $('uploadState').textContent = `Uploading · ${percent.toFixed(0)}%`;
    }};
    xhr.onload = () => {
        $('uploadProgress').hidden = true;
        let response = {}; try {response = JSON.parse(xhr.responseText);} catch {}
        if (xhr.status === 201) {
            state.upload = response;
            $('uploadState').textContent = 'Ready to render · original file preserved';
            setView('source'); refreshButtons();
        } else {$('uploadState').textContent = 'Upload failed: ' + (response.detail || xhr.statusText);}
    };
    xhr.onerror = () => {$('uploadProgress').hidden = true; $('uploadState').textContent = 'Upload failed: network error';};
    xhr.send(form);
}
const fileDialog = () => $('fileInput').click();
$('openMediaButton').addEventListener('click', fileDialog);
$('dropzone').addEventListener('click', fileDialog);
$('dropzone').addEventListener('keydown', event => {if (event.key === 'Enter' || event.key === ' ') {event.preventDefault(); fileDialog();}});
$('fileInput').addEventListener('change', e => {uploadVideo(e.target.files[0]); e.target.value = '';});
$('stage').addEventListener('dragover', e => {e.preventDefault(); $('dropzone').classList.add('drag');});
$('stage').addEventListener('dragleave', () => $('dropzone').classList.remove('drag'));
$('stage').addEventListener('drop', e => {e.preventDefault(); $('dropzone').classList.remove('drag'); if(e.dataTransfer.files.length) uploadVideo(e.dataTransfer.files[0]);});
$('renderButton').addEventListener('click', async () => {
    if (!state.upload) return;
    clearError();
    try {
        $('renderButton').disabled = true;
        const job = await jsonRequest('/api/jobs', {method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({upload_id: state.upload.id, options: renderOptions()})});
        $('uploadState').textContent = `Render queued · ${job.id.slice(0, 8)}`;
        await refreshJobs(); document.getElementById('queue').scrollIntoView({behavior:'smooth',block:'start'});
    } catch (error) {showError(error);} finally {refreshButtons();}
});
$('previewButton').addEventListener('click', async () => {
    if (!state.upload) return;
    clearError(); $('previewButton').disabled = true;
    $('previewButton').textContent = 'Rendering still…';
    try {
        const result = await jsonRequest('/api/preview', {method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({upload_id: state.upload.id, timestamp: $('sourcePlayer').currentTime || 0, options: renderOptions()})});
        $('beforeImg').src = result.before; $('afterImg').src = result.after;
        state.hasComparison = true;
        $('compareSlider').value = '50';
        applyComparison(); setView('compare');
        $('previewNote').textContent = 'Static image preview; temporal video rendering may differ.';
    } catch (error) {showError(error);} finally {$('previewButton').textContent = 'Generate before / after'; refreshButtons();}
});
function applyComparison() {
    const p = Number($('compareSlider').value);
    $('afterClip').style.clipPath = `inset(0 ${100 - p}% 0 0)`;
    $('splitLine').style.left = `${p}%`;
}
$('compareSlider').addEventListener('input', applyComparison);
function node(tag, className, content) {const n = document.createElement(tag); if(className)n.className = className; if(content !== undefined)n.textContent = content; return n;}
function link(label, url) {const a = node('a', null, label); a.href = url; return a;}
async function viewResult(job, full = false) {
    clearError();
    state.resultJob = job;
    const v = $('resultPlayer');
    v.src = '/api/jobs/' + job.id + (full ? '/video' : '/sample');
    v.load();
    setView('result');
    $('sourceName').textContent = job.filename;
    $('uploadState').textContent = full ? 'Full rendered output · browser HEVC playback depends on OS/browser codecs' : '12-second H.264 inspection sample · full export available below';
    $('stage').scrollIntoView({behavior: 'smooth', block: 'center'});
    try {await v.play();} catch {/* A user gesture may still be required; native video controls remain available. */}
}
$('resultPlayer').addEventListener('error', () => {
    if (state.view === 'result') $('uploadState').textContent = 'Preview playback failed. Check the job output, use Download video, or open the full export in VLC.';
});
function jobCard(job) {
    const card = node('article', 'job');
    const top = node('div', 'job-top');
    top.append(node('div', 'job-title', job.filename), node('span', 'job-state ' + job.status, job.status)); card.append(top);
    const progress = node('div','job-progress'); const fill = node('span'); fill.style.width = (job.progress * 100).toFixed(1) + '%'; progress.append(fill); card.append(progress);
    card.append(node('div','job-message',(job.message || '') + (job.status === 'running' ? ` · ${(job.progress * 100).toFixed(0)}%` : '')));
    if (job.error) card.append(node('div', 'info error', job.error));
    const actions = node('div', 'job-actions');
    if (['queued','running'].includes(job.status)) {
        const button = node('button', 'cancel', 'Cancel');
        button.onclick = async () => {try {await jsonRequest('/api/jobs/' + job.id + '/cancel', {method:'POST'}); await refreshJobs();} catch(e) {showError(e);}};
        actions.append(button);
    }
    if (job.status === 'completed') {
        const preview = node('button', null, '▶ Watch 12s sample');
        preview.onclick = () => viewResult(job);
        const full = node('button', null, 'Try full playback');
        full.onclick = () => viewResult(job, true);
        actions.append(preview, full, link('↓ Download full video', '/api/jobs/' + job.id + '/download'), link('JSON report', '/api/jobs/' + job.id + '/report'));
        if (job.frames) actions.append(node('span','job-message',`${job.frames.toLocaleString()} native frames`));
    }
    card.append(actions); return card;
}
async function refreshJobs() {
    try {
        state.jobs = await jsonRequest('/api/jobs');
        const list = $('jobList'); list.replaceChildren();
        if (!state.jobs.length) list.append(node('div', 'queue-empty', 'Your render history is empty. Add footage to begin.'));
        else state.jobs.forEach(job => list.append(jobCard(job)));
    } catch (error) {showError(error);}
}
$('refreshButton').addEventListener('click', refreshJobs);
function showDiagnostics() {$('diagnostics').showModal();}
$('diagnoseButton').addEventListener('click', showDiagnostics);
$('railDiagnostics').addEventListener('click', showDiagnostics);
$('closeDiagnostics').addEventListener('click', () => $('diagnostics').close());
$('diagnosticsRefresh').addEventListener('click', getCapabilities);
(async () => {updateExportRecipe(); setView('source'); await getCapabilities(); await refreshJobs(); setInterval(refreshJobs, 2000);})();

// Two-state appearance toggle. Follow system until the user makes a choice.
const systemTheme = window.matchMedia('(prefers-color-scheme: dark)');
const themeKey = 'framecraft-theme-v2';
const themeToggle = $('themeToggle');
const themeIcon = $('themeIcon');
const themeLabel = $('themeLabel');

function getManualTheme() {
    try {
        const savedTheme = localStorage.getItem(themeKey);
        return ['light', 'dark'].includes(savedTheme) ? savedTheme : null;
    } catch (_) {
        return null;
    }
}

let manualTheme = getManualTheme();

function currentTheme() {
    return manualTheme || (systemTheme.matches ? 'dark' : 'light');
}

function applyTheme() {
    const theme = currentTheme();
    const dark = theme === 'dark';
    document.documentElement.dataset.theme = theme;
    themeIcon.textContent = dark ? '☾' : '☀';
    themeLabel.textContent = dark ? 'Dark' : 'Light';
    themeToggle.setAttribute('aria-label', `Switch to ${dark ? 'light' : 'dark'} mode`);
    themeToggle.setAttribute('aria-pressed', String(dark));
    themeToggle.title = `Current appearance: ${dark ? 'Dark' : 'Light'}. Click to switch.`;
    document.querySelector('meta[name="theme-color"]').content = dark ? '#171a23' : '#ffffff';
}

themeToggle.addEventListener('click', () => {
    manualTheme = currentTheme() === 'dark' ? 'light' : 'dark';
    try {
        localStorage.setItem(themeKey, manualTheme);
    } catch (_) {
        // Still allow switching when localStorage is disabled.
    }
    applyTheme();
});

systemTheme.addEventListener('change', () => {
    if (manualTheme === null) applyTheme();
});

applyTheme();
