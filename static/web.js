let currentUrl = '';
let currentType = 'video';
let currentTaskId = null;
let pollInterval = null;
let historyInterval = null;
let availableSubs = [];

// Event Listeners
document.getElementById('urlInput').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') checkUrl();
});
document.getElementById('btnCheck').addEventListener('click', checkUrl);

async function checkCookieStatus() {
    try {
        const res = await fetch('/cookies/status');
        const data = await res.json();
        const btn = document.getElementById('btnUploadCookies');
        if (data.exists) {
            btn.style.backgroundColor = '#10b981'; // Green
            btn.title = "Cookies activas (YouTube)";
        } else {
            btn.style.backgroundColor = '#ef4444'; // Red
            btn.title = "Sin cookies (YouTube)";
        }
    } catch (e) {
        console.error("Error checking cookies:", e);
    }
}

async function uploadCookies(input) {
    if (!input.files || !input.files[0]) return;

    const file = input.files[0];
    const formData = new FormData();
    formData.append('file', file);

    try {
        const res = await fetch('/cookies/upload', {
            method: 'POST',
            body: formData
        });
        const data = await res.json();

        if (data.error) throw new Error(data.error);

        alert('Cookies subidas correctamente.');
        checkCookieStatus(); // Refresh status
    } catch (e) {
        alert('Error al subir cookies: ' + e.message);
    } finally {
        input.value = ''; // Reset input
    }
}

function setType(type) {
    currentType = type;
    document.querySelectorAll('.toggle-btn').forEach(b => b.classList.remove('active'));
    document.querySelector(`.toggle-btn[data-type="${type}"]`).classList.add('active');

    const qGroup = document.getElementById('qualityGroup');
    if (type === 'audio') qGroup.style.opacity = '0.5';
    else qGroup.style.opacity = '1';
}

function toggleSubsOptions() {
    const checked = document.getElementById('subsCheckbox').checked;
    const opts = document.getElementById('subsOptions');
    if (checked && availableSubs.length > 0) {
        opts.classList.remove('hidden');
    } else {
        opts.classList.add('hidden');
    }
}

function togglePlaylistOptions() {
    const checked = document.getElementById('playlistCheckbox').checked;
    const opts = document.getElementById('playlistOptions');
    if (checked) {
        opts.classList.remove('hidden');
    } else {
        opts.classList.add('hidden');
    }
}


async function checkUrl() {
    let url = document.getElementById('urlInput').value.trim();
    if (!url) return;

    currentUrl = url;
    showLoader(true);

    try {
        const res = await fetch('/descarga/info', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url })
        });
        const data = await res.json();

        if (data.error) throw new Error(data.error);

        document.getElementById('videoTitle').textContent = data.title;
        document.getElementById('videoThumb').src = data.thumbnail;
        document.getElementById('videoDuration').textContent = data.duration;
        document.getElementById('videoUploader').textContent = data.uploader;

        // Procesar subtítulos
        availableSubs = data.subtitles || [];
        const subSelect = document.getElementById('subsLangSelect');
        subSelect.innerHTML = '<option value="all">Todos los disponibles</option>';

        if (availableSubs.length > 0) {
            availableSubs.forEach(lang => {
                const opt = document.createElement('option');
                opt.value = lang;
                opt.textContent = lang;
                subSelect.appendChild(opt);
            });
        }

        // Resetear UI de subs
        document.getElementById('subsCheckbox').checked = false;
        toggleSubsOptions();

        showStep('info');
    } catch (e) {
        alert('Error: ' + e.message);
    } finally {
        showLoader(false);
    }
}

async function startDownload() {
    const quality = document.getElementById('qualitySelect').value;
    const subtitles = document.getElementById('subsCheckbox').checked;
    const subtitleLang = document.getElementById('subsLangSelect').value;
    const downloadPlaylist = document.getElementById('playlistCheckbox').checked;
    const maxItemsInput = document.getElementById('maxItemsInput').value;
    const maxItems = maxItemsInput ? parseInt(maxItemsInput) : -1;

    // Reset UI before showing progress
    document.getElementById('progressStatus').textContent = 'Iniciando...';
    document.getElementById('progressPercent').textContent = '0%';
    document.getElementById('progressBar').style.width = '0%';
    document.getElementById('progressBar').style.backgroundColor = 'var(--accent-color)';
    document.getElementById('speed').textContent = '0 MiB/s';
    document.getElementById('eta').textContent = '00:00';

    showStep('progress');

    try {
        const res = await fetch('/descarga/iniciar', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                url: currentUrl,
                format: currentType,
                quality: quality,
                subtitles: subtitles,
                subtitle_lang: subtitleLang,
                download_playlist: downloadPlaylist,
                max_items: maxItems
            })
        });
        const data = await res.json();
        currentTaskId = data.task_id;
        startPolling();
    } catch (e) {
        alert('Error al iniciar: ' + e.message);
        resetStep();
    }
}

async function cancelDownload() {
    if (!currentTaskId) return;
    if (!confirm('¿Seguro que quieres cancelar?')) return;

    await fetch('/descarga/cancel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_id: currentTaskId })
    });
}

function startPolling() {
    if (pollInterval) clearInterval(pollInterval);

    pollInterval = setInterval(async () => {
        try {
            const res = await fetch(`/descarga/status/${currentTaskId}`);
            if (res.status === 404) {
                // Si da 404, puede que haya terminado y expirado muy rápido o se canceló
                // Intentamos recargar historial y parar polling
                clearInterval(pollInterval);
                loadHistory();
                return;
            }

            const status = await res.json();

            const bar = document.getElementById('progressBar');
            const txt = document.getElementById('progressStatus');
            const pct = document.getElementById('progressPercent');

            // Actualizar barra principal
            bar.style.width = status.progress + '%';
            pct.textContent = status.progress.toFixed(1) + '%';

            // Actualizar detalles
            if (status.type === 'playlist') {
                // Lógica para Playlists Granulares
                const container = document.getElementById('playlistContainer') || createPlaylistContainer();

                // Mostrar resumen
                txt.textContent = `Descargando Playlist: ${status.completed_count}/${status.total_count} videos completados`;

                // Renderizar lista de items
                renderPlaylistItems(status.items, container);

                // Ocultar info de velocidad individual en el header global para no confundir
                document.getElementById('speed').textContent = '';
                document.getElementById('eta').textContent = '';

            } else {
                // Lógica de descarga normal
                document.getElementById('speed').textContent = status.speed || '--';
                document.getElementById('eta').textContent = status.eta || '--';

                if (status.status === 'downloading') {
                    txt.textContent = 'Descargando...';
                } else if (status.status === 'processing') {
                    txt.textContent = 'Procesando...';
                    bar.style.backgroundColor = '#f59e0b';
                }
            }

            // Manejo de estados finales
            if (status.status === 'completed' || status.status === 'ready_for_zip') {
                // Si es playlist, esperar a que el 'completed' real llegue (después del ZIP)
                if (status.type === 'playlist' && status.status !== 'completed') {
                    return; // Seguir polling hasta que el ZIP termine
                }

                clearInterval(pollInterval);
                txt.textContent = '¡Completado!';
                bar.style.backgroundColor = '#10b981';
                setTimeout(loadHistory, 1500);

                if (status.type === 'playlist') {
                    alert(`Playlist "${status.playlist_title || 'descargada'}" completada.\nCarpeta: ${status.playlist_folder}\nZIP disponible en historial.`);
                    showStep('url');
                    // Limpiar contenedor de playlist visual
                    const container = document.getElementById('playlistContainer');
                    if (container) container.remove();

                } else if (status.filename) {
                    window.location.href = `/descarga/archivo/${status.filename}`;
                    showStep('url');
                } else {
                    alert('Descarga completada. Revisa el historial.');
                    showStep('url');
                }

            } else if (status.status === 'error' || status.status === 'cancelled' || status.status === 'failed' || status.status === 'completed_with_errors') {
                clearInterval(pollInterval);
                if (status.type === 'playlist') {
                    alert(`Playlist finalizada con errores.\n${status.failed_count} fallidos.`);
                } else {
                    alert('Estado: ' + status.status + (status.error ? '\n' + status.error : ''));
                }
                resetStep();
                const container = document.getElementById('playlistContainer');
                if (container) container.remove();
            }
        } catch (e) {
            console.error("Polling error:", e);
            // No parar polling inmediatamente por un error de red transitorio
        }
    }, 2000); // Polling cada 2s
}

function createPlaylistContainer() {
    const statusSection = document.getElementById('step-progress');
    let container = document.getElementById('playlistContainer');
    if (!container) {
        container = document.createElement('div');
        container.id = 'playlistContainer';
        container.className = 'playlist-progress-container';
        // Insertar después de la barra de progreso
        const progressWrapper = document.querySelector('.progress-container');
        progressWrapper.parentNode.insertBefore(container, progressWrapper.nextSibling);
    }
    return container;
}

function renderPlaylistItems(items, container) {
    if (!items) return;

    container.innerHTML = '';

    items.forEach(item => {
        const div = document.createElement('div');
        div.className = 'playlist-item-row';
        div.style.display = 'flex';
        div.style.alignItems = 'center';
        div.style.fontSize = '0.85rem';
        div.style.margin = '4px 0';
        div.style.padding = '4px';
        div.style.borderBottom = '1px solid #eee';

        let icon = '<i class="fas fa-clock text-gray"></i>';
        let color = '#666';

        if (item.status === 'downloading') {
            icon = '<i class="fas fa-spinner fa-spin"></i>';
            color = 'var(--accent-color)';
        } else if (item.status === 'completed') {
            icon = '<i class="fas fa-check-circle"></i>';
            color = '#10b981';
        } else if (item.status === 'failed') {
            icon = '<i class="fas fa-times-circle"></i>';
            color = '#ef4444';
        }

        div.innerHTML = `
            <div style="width: 25px; color: ${color}">${icon}</div>
            <div style="width: 30px; font-weight: bold;">#${item.index}</div>
            <div style="flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${item.title}</div>
            <div style="width: 60px; text-align: right; font-size: 0.8em;">${item.progress.toFixed(0)}%</div>
        `;

        container.appendChild(div);
    });
}


// --- History & Timer Logic ---
async function loadHistory() {
    try {
        const res = await fetch('/descarga/historial');
        const files = await res.json();
        renderHistory(files);
    } catch (e) {
        console.error("Error loading history:", e);
    }
}

function renderHistory(files) {
    const list = document.getElementById('historyList');
    list.innerHTML = '';

    files.forEach(f => {
        const item = document.createElement('div');
        item.className = 'history-item';

        let icon = 'fa-file-video';
        let downloadBtn = `<a href="/descarga/archivo/${f.name}" class="btn-icon small" title="Descargar"><i class="fas fa-download"></i></a>`;
        let viewBtn = `<a href="/descarga/view/${f.name}" target="_blank" class="btn-icon small" title="Ver"><i class="fas fa-eye"></i></a>`;

        if (f.type === 'playlist') {
            icon = 'fa-folder';
            downloadBtn = `<button class="btn-icon small disabled" disabled title="Es una carpeta"><i class="fas fa-folder-open"></i></button>`;
            viewBtn = '';
        }

        // Usamos data-expires para que el timer local lo lea
        item.innerHTML = `
            <div class="file-info">
                <div class="file-name"><i class="fas ${icon}"></i> ${f.name}</div>
                <div class="file-meta">
                    ${(f.size / 1024 / 1024).toFixed(2)} MB | 
                    <span class="timer-display" data-expires="${f.expires_at}"><i class="fas fa-stopwatch"></i> Calculando...</span>
                </div>
            </div>
            <div class="file-actions">
                ${viewBtn}
                ${downloadBtn}
                <button onclick="deleteFile('${f.name}')" class="btn-icon small danger" title="Borrar"><i class="fas fa-trash"></i></button>
            </div>
        `;
        list.appendChild(item);
    });

    // Actualizar timers inmediatamente
    updateTimers();
}

function updateTimers() {
    const now = Date.now() / 1000; // Segundos
    document.querySelectorAll('.timer-display').forEach(el => {
        const expiresAt = parseFloat(el.getAttribute('data-expires'));
        const remaining = Math.max(0, expiresAt - now);

        const h = Math.floor(remaining / 3600);
        const m = Math.floor((remaining % 3600) / 60);
        const s = Math.floor(remaining % 60);
        const timeStr = `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;

        el.innerHTML = `<i class="fas fa-stopwatch"></i> ${timeStr}`;

        // Actualizar color
        if (remaining < 300) {
            el.className = 'timer-display timer-danger';
        } else {
            el.className = 'timer-display timer-normal';
        }

        // Opcional: Si llega a 0, podríamos recargar el historial para confirmar que se borró
        if (remaining <= 0 && remaining > -2) { // Margen pequeño para no spamear
            loadHistory();
        }
    });
}

// Timer local cada segundo (sin peticiones al servidor)
setInterval(updateTimers, 1000);

async function deleteFile(name) {
    if (!confirm(`¿Eliminar ${name}?`)) return;
    await fetch(`/descarga/archivo/eliminar/${name}`, { method: 'DELETE' });
    loadHistory();
}

function showStep(stepId) {
    document.querySelectorAll('.step-section').forEach(el => el.classList.add('hidden'));
    document.getElementById(`step-${stepId}`).classList.remove('hidden');
}

function resetStep() {
    currentUrl = '';
    document.getElementById('urlInput').value = '';
    document.getElementById('progressBar').style.width = '0%';
    document.getElementById('progressBar').style.backgroundColor = 'var(--accent-color)';
    showStep('url');
}

function showLoader(show) {
    const btn = document.getElementById('btnCheck');
    if (show) btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
    else btn.innerHTML = '<i class="fas fa-search"></i>';
}

// Init
loadHistory();
checkCookieStatus();
