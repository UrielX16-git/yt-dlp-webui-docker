/**
 * yt-dlp WebUI — Modern Frontend Controller
 * Features: Concurrent tasks, persistent queue, YouTube search,
 * playlist item picker, suggestions, groups, player modal, toasts, drag & drop.
 */

(() => {
    'use strict';

    // --- Estado global ---
    let currentMode = 'url'; // 'url' | 'search'
    let currentUrl = '';
    let currentType = 'video'; // 'video' | 'audio'
    let currentQuality = 'best';
    let currentGroup = localStorage.getItem('ytdlp_group') || 'default';
    let availableSubs = [];
    let currentPlaylistInfo = null;
    let selectedPlaylistIndices = new Set();
    let historyFiles = [];

    // Tareas activas persistentes en localStorage: { [taskId]: { id, title, thumbnail, group, ... } }
    let activeTasks = {};
    try {
        activeTasks = JSON.parse(localStorage.getItem('ytdlp_active_tasks') || '{}');
    } catch {
        activeTasks = {};
    }

    // Intervalos
    let pollInterval = null;
    let timerInterval = null;
    let statsInterval = null;

    // --- Helpers de utilidad y seguridad ---
    function escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function formatBytes(bytes) {
        if (!bytes || bytes <= 0) return '0 B';
        const units = ['B', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(1024));
        return (bytes / Math.pow(1024, i)).toFixed(2) + ' ' + units[i];
    }

    function formatNumber(num) {
        if (!num && num !== 0) return '';
        return new Intl.NumberFormat('es-ES', { notation: 'compact', compactDisplay: 'short' }).format(num);
    }

    // --- Sistema de Toasts ---
    function showToast(message, type = 'info', duration = 4000) {
        const container = document.getElementById('toastContainer');
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;

        const iconMap = {
            success: 'fa-check-circle',
            error: 'fa-circle-exclamation',
            info: 'fa-circle-info'
        };

        toast.innerHTML = `
            <i class="fas ${iconMap[type] || 'fa-info-circle'} toast-icon"></i>
            <span class="toast-msg">${escapeHtml(message)}</span>
        `;
        container.appendChild(toast);

        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateY(10px)';
            toast.style.transition = '0.3s ease';
            setTimeout(() => toast.remove(), 300);
        }, duration);
    }

    // --- Diálogos Modales (reemplaza alert / confirm / prompt) ---
    function showDialog({ title, message, isPrompt = false, defaultValue = '', iconClass = 'fa-circle-question', isDanger = false }) {
        return new Promise((resolve) => {
            const modal = document.getElementById('dialogModal');
            const titleEl = document.getElementById('dialogTitle');
            const msgEl = document.getElementById('dialogMessage');
            const inputEl = document.getElementById('dialogInput');
            const iconEl = document.getElementById('dialogIcon');
            const btnOk = document.getElementById('dialogOk');
            const btnCancel = document.getElementById('dialogCancel');

            titleEl.textContent = title;
            msgEl.textContent = message || '';
            iconEl.innerHTML = `<i class="fas ${iconClass}"></i>`;
            iconEl.className = 'dialog-icon' + (isDanger ? ' danger' : '');

            if (isDanger) {
                btnOk.className = 'btn btn-danger';
            } else {
                btnOk.className = 'btn btn-primary';
            }

            if (isPrompt) {
                inputEl.classList.remove('hidden');
                inputEl.value = defaultValue;
                setTimeout(() => inputEl.focus(), 50);
            } else {
                inputEl.classList.add('hidden');
            }

            modal.classList.remove('hidden');

            function cleanup() {
                modal.classList.add('hidden');
                btnOk.removeEventListener('click', onOk);
                btnCancel.removeEventListener('click', onCancel);
                modal.removeEventListener('click', onBackdrop);
            }

            function onOk() {
                cleanup();
                resolve(isPrompt ? inputEl.value.trim() : true);
            }

            function onCancel() {
                cleanup();
                resolve(isPrompt ? null : false);
            }

            function onBackdrop(e) {
                if (e.target.hasAttribute('data-close') || e.target === modal) {
                    onCancel();
                }
            }

            btnOk.addEventListener('click', onOk);
            btnCancel.addEventListener('click', onCancel);
            modal.addEventListener('click', onBackdrop);
        });
    }

    function confirmDialog(title, message, isDanger = false) {
        return showDialog({ title, message, isDanger, iconClass: isDanger ? 'fa-triangle-exclamation' : 'fa-circle-question' });
    }

    function promptDialog(title, message, defaultValue = '') {
        return showDialog({ title, message, isPrompt: true, defaultValue, iconClass: 'fa-folder-plus' });
    }

    // --- Reproductor integrado ---
    function openPlayer(filename, title) {
        const modal = document.getElementById('playerModal');
        const body = document.getElementById('playerBody');
        const titleEl = document.getElementById('playerTitle');
        const dlBtn = document.getElementById('playerDownload');

        titleEl.textContent = title || filename;
        const fileUrl = `/descarga/view/${encodeURIComponent(currentGroup)}/${encodeURIComponent(filename)}`;
        const downloadUrl = `/descarga/archivo/${encodeURIComponent(currentGroup)}/${encodeURIComponent(filename)}`;
        dlBtn.href = downloadUrl;

        const ext = filename.split('.').pop().toLowerCase();
        const isAudio = ['mp3', 'm4a', 'wav', 'ogg', 'opus', 'flac'].includes(ext);

        if (isAudio) {
            body.innerHTML = `
                <div style="padding: 2rem; width: 100%; text-align: center;">
                    <i class="fas fa-music" style="font-size: 3rem; color: var(--primary-from); margin-bottom: 1.5rem; display: block;"></i>
                    <audio controls autoplay style="width: 100%; max-width: 500px;">
                        <source src="${fileUrl}">
                        Tu navegador no soporta el elemento de audio.
                    </audio>
                </div>
            `;
        } else {
            body.innerHTML = `
                <video controls autoplay playsinline style="width: 100%; max-height: 70vh;">
                    <source src="${fileUrl}">
                    Tu navegador no soporta reproducción de video.
                </video>
            `;
        }

        modal.classList.remove('hidden');

        function close(e) {
            if (e.target.hasAttribute('data-close') || e.target === modal) {
                modal.classList.add('hidden');
                body.innerHTML = '';
                modal.removeEventListener('click', close);
            }
        }
        modal.addEventListener('click', close);
    }

    // --- Persistencia de Tareas ---
    function saveActiveTasks() {
        localStorage.setItem('ytdlp_active_tasks', JSON.stringify(activeTasks));
        renderActiveTasks();
    }

    function registerTask(id, meta) {
        activeTasks[id] = {
            id,
            title: meta.title || 'Descarga',
            thumbnail: meta.thumbnail || '',
            group: meta.group || currentGroup,
            status: 'queued',
            progress: 0,
            speed: '',
            eta: '',
            isPlaylist: meta.isPlaylist || false,
            createdAt: Date.now()
        };
        saveActiveTasks();
    }

    function removeTask(id) {
        delete activeTasks[id];
        saveActiveTasks();
    }

    // --- Topbar: Salud de API, Estadísticas y Grupos ---
    async function checkApiHealth() {
        const el = document.getElementById('apiStatus');
        try {
            const res = await fetch('/health', { cache: 'no-store' });
            if (res.ok) {
                el.className = 'api-status online';
                el.querySelector('.label').textContent = 'API online';
            } else {
                throw new Error();
            }
        } catch {
            el.className = 'api-status offline';
            el.querySelector('.label').textContent = 'API sin conexión';
        }
    }

    async function updateQueueStats() {
        try {
            const res = await fetch('/descarga/queue/stats');
            if (!res.ok) return;
            const data = await res.json();
            const pill = document.getElementById('queueStats');
            document.getElementById('statPending').textContent = data.pending ?? 0;
            document.getElementById('statProcessing').textContent = data.processing ?? 0;
            document.getElementById('statCompleted').textContent = data.completed ?? 0;
            pill.classList.remove('hidden');
        } catch (e) {
            // Silencioso
        }
    }

    async function loadGroups() {
        try {
            const res = await fetch('/descarga/grupos');
            if (!res.ok) return;
            const groups = await res.json();
            const sel = document.getElementById('groupSelect');
            sel.innerHTML = '';
            groups.forEach(g => {
                const opt = document.createElement('option');
                opt.value = g;
                opt.textContent = g === 'default' ? 'default (general)' : g;
                if (g === currentGroup) opt.selected = true;
                sel.appendChild(opt);
            });
        } catch (e) {
            console.error('Error cargando grupos:', e);
        }
    }

    // --- Modos: URL vs Buscar ---
    function setMode(mode) {
        currentMode = mode;
        const tabUrl = document.getElementById('tabUrl');
        const tabSearch = document.getElementById('tabSearch');
        const input = document.getElementById('urlInput');
        const icon = document.getElementById('inputIcon');
        const btnLabel = document.getElementById('btnCheckLabel');

        if (mode === 'search') {
            tabSearch.classList.add('active');
            tabUrl.classList.remove('active');
            input.placeholder = 'Escribe lo que quieres buscar en YouTube…';
            icon.className = 'fas fa-magnifying-glass search-icon';
            btnLabel.textContent = 'Buscar';
        } else {
            tabUrl.classList.add('active');
            tabSearch.classList.remove('active');
            input.placeholder = 'Pega el enlace del video o playlist…';
            icon.className = 'fas fa-link search-icon';
            btnLabel.textContent = 'Analizar';
            document.getElementById('panelSearch').classList.add('hidden');
        }
        input.focus();
    }

    // --- Análisis de URL o Búsqueda ---
    async function handleMainAction(e) {
        if (e) e.preventDefault();
        const value = document.getElementById('urlInput').value.trim();
        if (!value) return;

        // Auto-detección: si parece URL, usar modo enlace
        const isUrl = /^https?:\/\//i.test(value);
        if (isUrl && currentMode !== 'url') {
            setMode('url');
        }

        if (currentMode === 'search') {
            await executeSearch(value);
        } else {
            await analyzeUrl(value);
        }
    }

    async function executeSearch(query) {
        showSkeleton(true);
        document.getElementById('panelSearch').classList.add('hidden');
        document.getElementById('panelInfo').classList.add('hidden');

        try {
            const res = await fetch(`/descarga/search-youtube?query=${encodeURIComponent(query)}&limit=8`);
            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Error en la búsqueda');
            }
            const data = await res.json();
            renderSearchResults(data.results || [], query);
        } catch (err) {
            showToast(err.message, 'error');
        } finally {
            showSkeleton(false);
        }
    }

    function renderSearchResults(results, query) {
        const panel = document.getElementById('panelSearch');
        const grid = document.getElementById('searchResults');
        const meta = document.getElementById('searchMeta');

        grid.innerHTML = '';
        meta.textContent = `${results.length} resultados para "${query}"`;

        if (results.length === 0) {
            grid.innerHTML = `<div class="empty-state" style="grid-column: 1 / -1;"><p>No se encontraron resultados</p></div>`;
            panel.classList.remove('hidden');
            return;
        }

        results.forEach(video => {
            const card = document.createElement('div');
            card.className = 'search-card';
            card.innerHTML = `
                <div class="search-thumb">
                    <img src="${escapeHtml(video.thumbnail || '')}" alt="${escapeHtml(video.title)}" loading="lazy">
                    <span class="duration-badge">${escapeHtml(video.duration || '00:00')}</span>
                </div>
                <div class="search-body">
                    <h4>${escapeHtml(video.title)}</h4>
                    <span class="meta"><i class="far fa-user"></i> ${escapeHtml(video.uploader || 'Desconocido')}</span>
                </div>
            `;
            card.addEventListener('click', () => {
                document.getElementById('urlInput').value = video.url;
                setMode('url');
                analyzeUrl(video.url);
            });
            grid.appendChild(card);
        });

        panel.classList.remove('hidden');
        panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    async function analyzeUrl(url) {
        currentUrl = url;
        showSkeleton(true);
        document.getElementById('panelSearch').classList.add('hidden');
        document.getElementById('panelInfo').classList.add('hidden');

        try {
            // Intentar detectar si es playlist
            const isPlaylistUrl = /[?&]list=([^#&]+)/.test(url);

            const res = await fetch('/descarga/info', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url })
            });

            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'No se pudo obtener información');
            }

            const data = await res.json();
            populateInfoCard(data, isPlaylistUrl);
        } catch (err) {
            showToast(err.message, 'error');
        } finally {
            showSkeleton(false);
        }
    }

    function populateInfoCard(data, isPlaylistCandidate) {
        document.getElementById('videoTitle').textContent = data.title || 'Sin título';
        document.getElementById('videoThumb').src = data.thumbnail || '';
        document.getElementById('videoDuration').textContent = data.duration || '00:00';
        document.getElementById('videoUploader').textContent = data.uploader || 'Autor desconocido';

        const viewsWrap = document.getElementById('videoViewsWrap');
        if (data.view_count) {
            document.getElementById('videoViews').textContent = `${formatNumber(data.view_count)} vistas`;
            viewsWrap.classList.remove('hidden');
        } else {
            viewsWrap.classList.add('hidden');
        }

        const srcLink = document.getElementById('videoSource');
        srcLink.href = currentUrl;

        // Subtítulos
        availableSubs = data.subtitles || [];
        const subsSelect = document.getElementById('subsLangSelect');
        const subsRow = document.getElementById('subsRow');
        const subsCheckbox = document.getElementById('subsCheckbox');
        subsCheckbox.checked = false;
        document.getElementById('subsOptions').classList.add('hidden');

        if (availableSubs.length > 0) {
            subsSelect.innerHTML = '<option value="all">Todos los idiomas disponibles</option>';
            availableSubs.forEach(lang => {
                const opt = document.createElement('option');
                opt.value = lang;
                opt.textContent = lang;
                subsSelect.appendChild(opt);
            });
            subsRow.classList.remove('hidden');
            document.getElementById('subsHint').textContent = `(${availableSubs.length} disponibles)`;
        } else {
            subsRow.classList.add('hidden');
        }

        // Playlist switch
        const plRow = document.getElementById('playlistRow');
        const plCheckbox = document.getElementById('playlistCheckbox');
        const plBadge = document.getElementById('playlistBadge');
        const plPreview = document.getElementById('playlistPreview');
        plPreview.classList.add('hidden');
        plCheckbox.checked = false;

        if (isPlaylistCandidate) {
            plRow.classList.remove('hidden');
            plBadge.classList.remove('hidden');
        } else {
            plRow.classList.add('hidden');
            plBadge.classList.add('hidden');
        }

        // Reset configuración de tipo y calidad
        setType('video');
        setQuality('best');

        const panel = document.getElementById('panelInfo');
        panel.classList.remove('hidden');
        panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    // --- Carga y previsualización de playlist ---
    async function loadPlaylistPreview() {
        const preview = document.getElementById('playlistPreview');
        const list = document.getElementById('plList');
        const meta = document.getElementById('plMeta');
        const titleEl = document.getElementById('plTitle');

        list.innerHTML = `<div class="empty-state small"><i class="fas fa-spinner fa-spin"></i> Obteniendo lista de videos…</div>`;
        preview.classList.remove('hidden');

        try {
            const res = await fetch('/descarga/playlist-info', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url: currentUrl, max_items: -1 })
            });

            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Error cargando playlist');
            }

            currentPlaylistInfo = await res.json();
            titleEl.textContent = currentPlaylistInfo.playlist_title || 'Playlist';
            meta.textContent = `${currentPlaylistInfo.returned_videos} videos disponibles`;

            selectedPlaylistIndices = new Set(currentPlaylistInfo.videos.map(v => v.index));
            renderPlaylistItems();
        } catch (err) {
            showToast(err.message, 'error');
            preview.classList.add('hidden');
            document.getElementById('playlistCheckbox').checked = false;
        }
    }

    function renderPlaylistItems() {
        const list = document.getElementById('plList');
        list.innerHTML = '';

        if (!currentPlaylistInfo || !currentPlaylistInfo.videos) return;

        currentPlaylistInfo.videos.forEach(v => {
            const row = document.createElement('label');
            row.className = 'pl-item';
            const checked = selectedPlaylistIndices.has(v.index) ? 'checked' : '';
            row.innerHTML = `
                <input type="checkbox" data-idx="${v.index}" ${checked}>
                <span class="idx">#${v.index}</span>
                <span class="title" title="${escapeHtml(v.title)}">${escapeHtml(v.title)}</span>
                <span class="dur">${escapeHtml(v.duration || '')}</span>
            `;
            const cb = row.querySelector('input');
            cb.addEventListener('change', () => {
                if (cb.checked) {
                    selectedPlaylistIndices.add(v.index);
                } else {
                    selectedPlaylistIndices.delete(v.index);
                }
                updateDownloadButtonLabel();
            });
            list.appendChild(row);
        });

        updateDownloadButtonLabel();
    }

    function updateDownloadButtonLabel() {
        const btnLabel = document.getElementById('btnDownloadLabel');
        const isPl = document.getElementById('playlistCheckbox').checked;
        if (isPl && currentPlaylistInfo) {
            btnLabel.textContent = `Descargar (${selectedPlaylistIndices.size} seleccionados)`;
        } else {
            btnLabel.textContent = 'Descargar';
        }
    }

    // --- Configuración (Formato, Calidad) ---
    function setType(type) {
        currentType = type;
        const btnV = document.getElementById('btnTypeVideo');
        const btnA = document.getElementById('btnTypeAudio');
        const qField = document.getElementById('qualityField');

        if (type === 'audio') {
            btnA.classList.add('active');
            btnV.classList.remove('active');
            qField.style.opacity = '0.4';
            qField.style.pointerEvents = 'none';
        } else {
            btnV.classList.add('active');
            btnA.classList.remove('active');
            qField.style.opacity = '1';
            qField.style.pointerEvents = 'auto';
        }
    }

    function setQuality(q) {
        currentQuality = q;
        document.querySelectorAll('#qualityChips .chip').forEach(c => {
            if (c.getAttribute('data-q') === q) c.classList.add('active');
            else c.classList.remove('active');
        });
    }

    // --- Iniciar Descarga ---
    async function startDownload() {
        const isPlaylist = document.getElementById('playlistCheckbox').checked;
        const subtitles = document.getElementById('subsCheckbox').checked;
        const subtitleLang = subtitles ? document.getElementById('subsLangSelect').value : null;
        const title = document.getElementById('videoTitle').textContent;
        const thumbnail = document.getElementById('videoThumb').src;

        let selectedIndices = null;
        if (isPlaylist && currentPlaylistInfo) {
            if (selectedPlaylistIndices.size === 0) {
                showToast('Selecciona al menos un video de la playlist', 'error');
                return;
            }
            selectedIndices = Array.from(selectedPlaylistIndices);
        }

        const btn = document.getElementById('btnDownload');
        btn.disabled = true;

        try {
            const res = await fetch('/descarga/iniciar', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    url: currentUrl,
                    format: currentType,
                    quality: currentQuality,
                    subtitles: subtitles,
                    subtitle_lang: subtitleLang,
                    download_playlist: isPlaylist,
                    max_items: -1,
                    group: currentGroup,
                    title: title,
                    thumbnail: thumbnail,
                    selected_indices: selectedIndices
                })
            });

            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Error al encolar la descarga');
            }

            const data = await res.json();
            registerTask(data.task_id, {
                title,
                thumbnail,
                group: currentGroup,
                isPlaylist
            });

            showToast('Descarga agregada a la cola', 'success');
            document.getElementById('panelInfo').classList.add('hidden');
            document.getElementById('urlInput').value = '';
            updateQueueStats();
        } catch (err) {
            showToast(err.message, 'error');
        } finally {
            btn.disabled = false;
        }
    }

    // --- Polling y Render de Tareas Activas ---
    async function pollActiveTasks() {
        const taskIds = Object.keys(activeTasks);
        if (taskIds.length === 0) {
            document.title = 'Descarga Videos · yt-dlp WebUI';
            return;
        }

        let maxProgress = 0;
        let anyDownloading = false;

        for (const id of taskIds) {
            try {
                const res = await fetch(`/descarga/status/${id}`);
                if (res.status === 404) {
                    // Tarea no encontrada en memoria (expiró o terminó y expiró en Valkey)
                    removeTask(id);
                    continue;
                }
                const data = await res.json();
                const task = activeTasks[id];
                if (!task) continue;

                task.status = data.status;
                task.progress = data.progress || 0;
                task.speed = data.speed || '';
                task.eta = data.eta || '';
                task.title = data.title || task.title;
                task.thumbnail = data.thumbnail || task.thumbnail;

                if (task.progress > maxProgress) maxProgress = task.progress;
                if (data.status === 'downloading') anyDownloading = true;

                // Playlist granular
                if (data.type === 'playlist') {
                    task.completedCount = data.completed_count || 0;
                    task.totalCount = data.total_count || 0;
                }

                // Manejo de finalización
                if (data.status === 'completed') {
                    showToast(`¡Completado: "${task.title}"!`, 'success');
                    notifyBrowser(`Descarga completada`, task.title);

                    // Auto-descargar archivo si es único
                    if (data.filename && !task.isPlaylist) {
                        triggerDownload(`/descarga/archivo/${encodeURIComponent(task.group)}/${encodeURIComponent(data.filename)}`);
                    }

                    removeTask(id);
                    loadHistory();
                    updateQueueStats();
                } else if (['error', 'failed', 'cancelled', 'completed_with_errors'].includes(data.status)) {
                    showToast(`Tarea ${data.status}: "${task.title}"`, 'error');
                    removeTask(id);
                    loadHistory();
                    updateQueueStats();
                }
            } catch (e) {
                console.error(`Error polling task ${id}:`, e);
            }
        }

        saveActiveTasks();

        // Actualizar título de la pestaña con progreso
        if (anyDownloading) {
            document.title = `(${maxProgress.toFixed(0)}%) Descarga Videos`;
        } else if (taskIds.length > 0) {
            document.title = `(${taskIds.length} en cola) Descarga Videos`;
        } else {
            document.title = 'Descarga Videos · yt-dlp WebUI';
        }
    }

    function renderActiveTasks() {
        const list = document.getElementById('activeList');
        const empty = document.getElementById('activeEmpty');
        const countBadge = document.getElementById('activeCount');
        const taskIds = Object.keys(activeTasks);

        countBadge.textContent = taskIds.length;

        if (taskIds.length === 0) {
            list.innerHTML = '';
            empty.classList.remove('hidden');
            return;
        }

        empty.classList.add('hidden');
        list.innerHTML = '';

        taskIds.forEach(id => {
            const task = activeTasks[id];
            const item = document.createElement('div');
            item.className = 'active-item';

            const statusLabels = {
                queued: '<span class="active-state queued"><i class="fas fa-hourglass-start"></i> En cola</span>',
                pending: '<span class="active-state queued"><i class="fas fa-hourglass-start"></i> En cola</span>',
                downloading: '<span class="active-state downloading"><i class="fas fa-spinner fa-spin"></i> Descargando</span>',
                processing: '<span class="active-state processing"><i class="fas fa-gears fa-spin"></i> Procesando</span>'
            };

            const statusHtml = statusLabels[task.status] || `<span class="active-state">${escapeHtml(task.status)}</span>`;

            let metaExtra = '';
            if (task.isPlaylist && task.totalCount) {
                metaExtra = `<span>${task.completedCount || 0}/${task.totalCount} videos</span>`;
            } else if (task.speed || task.eta) {
                metaExtra = `<span>${escapeHtml(task.speed || '')} ${task.eta ? '· ETA ' + escapeHtml(task.eta) : ''}</span>`;
            }

            item.innerHTML = `
                <div class="active-item-head">
                    <img class="active-thumb" src="${escapeHtml(task.thumbnail || '/static/icon.webp')}" alt="" onerror="this.src='/static/icon.webp'">
                    <div class="active-info">
                        <div class="active-title" title="${escapeHtml(task.title)}">${escapeHtml(task.title)}</div>
                        ${statusHtml}
                    </div>
                    <button class="icon-btn ghost tiny danger" title="Cancelar" data-cancel="${id}">
                        <i class="fas fa-xmark"></i>
                    </button>
                </div>
                <div class="progress-bar-wrap">
                    <div class="progress-bar-fill" style="width: ${Math.min(100, Math.max(0, task.progress || 0))}%;"></div>
                </div>
                <div class="active-meta">
                    <span>${(task.progress || 0).toFixed(1)}%</span>
                    ${metaExtra}
                </div>
            `;

            item.querySelector('[data-cancel]').addEventListener('click', () => cancelTask(id));
            list.appendChild(item);
        });
    }

    async function cancelTask(taskId) {
        const ok = await confirmDialog('¿Cancelar descarga?', 'La tarea se removerá de la cola.', true);
        if (!ok) return;

        try {
            await fetch('/descarga/cancel', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ task_id: taskId })
            });
            showToast('Cancelación solicitada', 'info');
            removeTask(taskId);
            updateQueueStats();
        } catch (err) {
            showToast('Error cancelando', 'error');
        }
    }

    function triggerDownload(url) {
        const a = document.createElement('a');
        a.href = url;
        a.download = '';
        document.body.appendChild(a);
        a.click();
        a.remove();
    }

    function notifyBrowser(title, body) {
        if (!('Notification' in window)) return;
        if (Notification.permission === 'granted') {
            new Notification(title, { body, icon: '/static/icon.webp' });
        } else if (Notification.permission !== 'denied') {
            Notification.requestPermission();
        }
    }

    // --- Historial ---
    async function loadHistory() {
        try {
            const res = await fetch(`/descarga/historial?group=${encodeURIComponent(currentGroup)}`);
            if (!res.ok) return;
            historyFiles = await res.json();
            renderHistory();
        } catch (e) {
            console.error('Error cargando historial:', e);
        }
    }

    function renderHistory() {
        const grid = document.getElementById('historyList');
        const empty = document.getElementById('historyEmpty');
        const countBadge = document.getElementById('historyCount');
        const filterText = document.getElementById('historyFilter').value.trim().toLowerCase();
        const activeTypeFilter = document.querySelector('#historyTypeFilter .chip.active')?.getAttribute('data-f') || 'all';

        let filtered = historyFiles.filter(f => {
            if (filterText && !f.name.toLowerCase().includes(filterText)) return false;
            if (activeTypeFilter === 'all') return true;
            if (activeTypeFilter === 'playlist') return f.type === 'playlist';
            const ext = f.name.split('.').pop().toLowerCase();
            const isAudio = ['mp3', 'm4a', 'wav', 'ogg', 'opus', 'flac'].includes(ext);
            if (activeTypeFilter === 'audio') return isAudio && f.type !== 'playlist';
            if (activeTypeFilter === 'video') return !isAudio && f.type !== 'playlist';
            return true;
        });

        countBadge.textContent = historyFiles.length;

        if (filtered.length === 0) {
            grid.innerHTML = '';
            empty.classList.remove('hidden');
            document.getElementById('historyEmptyText').textContent =
                filterText || activeTypeFilter !== 'all' ? 'No hay archivos que coincidan con el filtro.' : 'Aún no hay descargas en esta carpeta.';
            return;
        }

        empty.classList.add('hidden');
        grid.innerHTML = '';

        filtered.forEach(f => {
            const card = document.createElement('div');
            card.className = 'history-card';

            const ext = f.name.split('.').pop().toLowerCase();
            const isAudio = ['mp3', 'm4a', 'wav', 'ogg', 'opus', 'flac'].includes(ext);
            const isPlaylist = f.type === 'playlist';

            let iconClass = 'fa-file-video';
            let badgeClass = '';
            if (isPlaylist) {
                iconClass = 'fa-folder';
                badgeClass = 'folder';
            } else if (isAudio) {
                iconClass = 'fa-file-audio';
                badgeClass = 'audio';
            }

            const downloadUrl = `/descarga/archivo/${encodeURIComponent(currentGroup)}/${encodeURIComponent(f.name)}`;

            card.innerHTML = `
                <div class="history-card-head">
                    <div class="history-badge-icon ${badgeClass}">
                        <i class="fas ${iconClass}"></i>
                    </div>
                    <div class="history-name" title="${escapeHtml(f.name)}">${escapeHtml(f.name)}</div>
                </div>
                <div class="history-card-meta">
                    <span>${formatBytes(f.size)}</span>
                    <span class="timer-badge" data-expires="${f.expires_at}"><i class="fas fa-clock"></i> Calculando…</span>
                </div>
                <div class="history-actions">
                    ${!isPlaylist ? `<button class="icon-btn small" title="Reproducir" data-view="${escapeHtml(f.name)}"><i class="fas fa-play"></i></button>` : ''}
                    ${!isPlaylist ? `<a class="icon-btn small" title="Descargar" href="${downloadUrl}"><i class="fas fa-download"></i></a>` : ''}
                    <button class="icon-btn small danger" title="Eliminar" data-delete="${escapeHtml(f.name)}"><i class="fas fa-trash"></i></button>
                </div>
            `;

            const viewBtn = card.querySelector('[data-view]');
            if (viewBtn) {
                viewBtn.addEventListener('click', () => openPlayer(f.name, f.name));
            }

            card.querySelector('[data-delete]').addEventListener('click', () => deleteFile(f.name));
            grid.appendChild(card);
        });

        updateCountdownTimers();
    }

    function updateCountdownTimers() {
        const now = Date.now() / 1000;
        document.querySelectorAll('.timer-badge[data-expires]').forEach(el => {
            const exp = parseFloat(el.getAttribute('data-expires'));
            const rem = Math.max(0, exp - now);

            const h = Math.floor(rem / 3600);
            const m = Math.floor((rem % 3600) / 60);
            const s = Math.floor(rem % 60);
            const str = `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;

            el.innerHTML = `<i class="fas fa-clock"></i> ${str}`;

            if (rem < 300) {
                el.className = 'timer-badge danger';
            } else {
                el.className = 'timer-badge';
            }

            if (rem <= 0 && rem > -2) {
                loadHistory();
            }
        });
    }

    async function deleteFile(name) {
        const ok = await confirmDialog('¿Eliminar archivo?', `Se borrará definitivamente "${name}".`, true);
        if (!ok) return;

        try {
            const res = await fetch(`/descarga/archivo/eliminar/${encodeURIComponent(currentGroup)}/${encodeURIComponent(name)}`, {
                method: 'DELETE'
            });
            if (res.ok) {
                showToast('Archivo eliminado', 'info');
                loadHistory();
            } else {
                throw new Error();
            }
        } catch {
            showToast('Error al eliminar archivo', 'error');
        }
    }

    // --- Sugerencias Inteligentes ---
    async function loadSuggestions() {
        try {
            const res = await fetch(`/descarga/suggestions?limit=6&group=${encodeURIComponent(currentGroup)}`);
            if (!res.ok) return;
            const data = await res.json();
            const section = document.getElementById('suggestionsSection');
            const list = document.getElementById('suggestionsList');
            const reason = document.getElementById('suggestReason');

            if (!data.results || data.results.length === 0) {
                section.classList.add('hidden');
                return;
            }

            reason.textContent = data.reason || 'Basado en tus descargas';
            list.innerHTML = '';

            data.results.forEach(v => {
                const card = document.createElement('div');
                card.className = 'search-card';
                card.innerHTML = `
                    <div class="search-thumb">
                        <img src="${escapeHtml(v.thumbnail || '')}" alt="${escapeHtml(v.title)}" loading="lazy">
                        <span class="duration-badge">${escapeHtml(v.duration || '00:00')}</span>
                    </div>
                    <div class="search-body">
                        <h4>${escapeHtml(v.title)}</h4>
                        <span class="meta"><i class="far fa-user"></i> ${escapeHtml(v.uploader || '')}</span>
                    </div>
                `;
                card.addEventListener('click', () => {
                    document.getElementById('urlInput').value = v.url;
                    setMode('url');
                    analyzeUrl(v.url);
                });
                list.appendChild(card);
            });

            section.classList.remove('hidden');
        } catch (e) {
            // Silencioso
        }
    }

    // --- Grupos: creación ---
    async function createNewGroup() {
        const name = await promptDialog('Nueva carpeta', 'Nombre para organizar tus descargas (ej. Musica, Clases):');
        if (!name) return;

        // Validar caracteres
        if (!/^[\w\- ]{1,40}$/.test(name)) {
            showToast('Nombre inválido (usa letras, números y guiones, máx 40 caracteres)', 'error');
            return;
        }

        currentGroup = name;
        localStorage.setItem('ytdlp_group', currentGroup);
        await loadGroups();
        document.getElementById('groupSelect').value = currentGroup;
        showToast(`Carpeta cambiada a "${name}"`, 'success');
        loadHistory();
        loadSuggestions();
    }

    // --- UI Helpers ---
    function showSkeleton(show) {
        const skel = document.getElementById('panelSkeleton');
        const btn = document.getElementById('btnCheck');
        if (show) {
            skel.classList.remove('hidden');
            btn.disabled = true;
        } else {
            skel.classList.add('hidden');
            btn.disabled = false;
        }
    }

    // --- Drag & Drop y Portapapeles ---
    function setupDragAndDrop() {
        const overlay = document.getElementById('dropOverlay');
        let dragCounter = 0;

        window.addEventListener('dragenter', (e) => {
            e.preventDefault();
            dragCounter++;
            overlay.classList.remove('hidden');
        });

        window.addEventListener('dragleave', (e) => {
            e.preventDefault();
            dragCounter--;
            if (dragCounter <= 0) {
                overlay.classList.add('hidden');
                dragCounter = 0;
            }
        });

        window.addEventListener('dragover', (e) => e.preventDefault());

        window.addEventListener('drop', (e) => {
            e.preventDefault();
            dragCounter = 0;
            overlay.classList.add('hidden');

            const text = e.dataTransfer.getData('text/plain') || e.dataTransfer.getData('text/uri-list');
            if (text && /^https?:\/\//i.test(text.trim())) {
                document.getElementById('urlInput').value = text.trim();
                setMode('url');
                analyzeUrl(text.trim());
            }
        });
    }

    // --- Event Listeners Globales ---
    function setupEventListeners() {
        // Formulario principal
        document.getElementById('mainForm').addEventListener('submit', handleMainAction);

        // Tabs
        document.getElementById('tabUrl').addEventListener('click', () => setMode('url'));
        document.getElementById('tabSearch').addEventListener('click', () => setMode('search'));

        // Input helpers
        const input = document.getElementById('urlInput');
        const btnClear = document.getElementById('btnClear');
        const btnPaste = document.getElementById('btnPaste');

        input.addEventListener('input', () => {
            btnClear.hidden = !input.value.trim();
        });

        btnClear.addEventListener('click', () => {
            input.value = '';
            btnClear.hidden = true;
            input.focus();
        });

        btnPaste.addEventListener('click', async () => {
            try {
                const text = await navigator.clipboard.readText();
                if (text) {
                    input.value = text.trim();
                    btnClear.hidden = false;
                    handleMainAction();
                }
            } catch {
                input.focus();
            }
        });

        // Segmented control (tipo)
        document.getElementById('btnTypeVideo').addEventListener('click', () => setType('video'));
        document.getElementById('btnTypeAudio').addEventListener('click', () => setType('audio'));

        // Quality chips
        document.querySelectorAll('#qualityChips .chip').forEach(c => {
            c.addEventListener('click', () => setQuality(c.getAttribute('data-q')));
        });

        // Switches
        document.getElementById('subsCheckbox').addEventListener('change', (e) => {
            const opts = document.getElementById('subsOptions');
            if (e.target.checked && availableSubs.length > 0) opts.classList.remove('hidden');
            else opts.classList.add('hidden');
        });

        document.getElementById('playlistCheckbox').addEventListener('change', (e) => {
            if (e.target.checked) {
                loadPlaylistPreview();
            } else {
                document.getElementById('playlistPreview').classList.add('hidden');
                updateDownloadButtonLabel();
            }
        });

        // Playlist select all/none
        document.getElementById('plSelectAll').addEventListener('click', () => {
            if (!currentPlaylistInfo) return;
            selectedPlaylistIndices = new Set(currentPlaylistInfo.videos.map(v => v.index));
            renderPlaylistItems();
        });

        document.getElementById('plSelectNone').addEventListener('click', () => {
            selectedPlaylistIndices.clear();
            renderPlaylistItems();
        });

        // Botones de acción
        document.getElementById('btnDownload').addEventListener('click', startDownload);
        document.getElementById('btnBack').addEventListener('click', () => {
            document.getElementById('panelInfo').classList.add('hidden');
            document.getElementById('urlInput').focus();
        });

        // Filtros de historial
        document.getElementById('historyFilter').addEventListener('input', renderHistory);
        document.querySelectorAll('#historyTypeFilter .chip').forEach(c => {
            c.addEventListener('click', () => {
                document.querySelectorAll('#historyTypeFilter .chip').forEach(x => x.classList.remove('active'));
                c.classList.add('active');
                renderHistory();
            });
        });

        document.getElementById('btnRefreshHistory').addEventListener('click', () => {
            loadHistory();
            showToast('Historial actualizado', 'info', 2000);
        });

        // Selector de grupo
        document.getElementById('groupSelect').addEventListener('change', (e) => {
            currentGroup = e.target.value;
            localStorage.setItem('ytdlp_group', currentGroup);
            loadHistory();
            loadSuggestions();
            showToast(`Carpeta: ${currentGroup}`, 'info', 2000);
        });

        document.getElementById('btnNewGroup').addEventListener('click', createNewGroup);

        // Atajos de teclado globales
        window.addEventListener('keydown', (e) => {
            // Pegar con Ctrl+V cuando el foco no está en un input
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'v' && !['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName)) {
                navigator.clipboard.readText().then(text => {
                    if (text && /^https?:\/\//i.test(text.trim())) {
                        input.value = text.trim();
                        btnClear.hidden = false;
                        setMode('url');
                        analyzeUrl(text.trim());
                    }
                }).catch(() => {});
            }

            // Esc para cerrar modales o volver atrás
            if (e.key === 'Escape') {
                const playerModal = document.getElementById('playerModal');
                const dialogModal = document.getElementById('dialogModal');
                if (!playerModal.classList.contains('hidden')) {
                    playerModal.classList.add('hidden');
                    document.getElementById('playerBody').innerHTML = '';
                } else if (!dialogModal.classList.contains('hidden')) {
                    dialogModal.classList.add('hidden');
                } else if (!document.getElementById('panelInfo').classList.contains('hidden')) {
                    document.getElementById('panelInfo').classList.add('hidden');
                }
            }
        });

        setupDragAndDrop();
    }

    // --- Inicialización ---
    async function init() {
        setupEventListeners();
        renderActiveTasks();

        await checkApiHealth();
        await loadGroups();
        await loadHistory();
        await loadSuggestions();
        await updateQueueStats();

        // Polling de tareas activas cada 1.5s
        pollInterval = setInterval(pollActiveTasks, 1500);

        // Timers locales cada 1s (sin red)
        timerInterval = setInterval(updateCountdownTimers, 1000);

        // Estado de cola cada 5s
        statsInterval = setInterval(updateQueueStats, 5000);

        // Salud de API cada 15s
        setInterval(checkApiHealth, 15000);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
