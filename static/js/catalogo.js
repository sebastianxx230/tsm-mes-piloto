const desktopRows = Array.from(document.querySelectorAll('.ot-row-desktop'));
const mobileCards = Array.from(document.querySelectorAll('.ot-row-mobile'));
let filteredIndices = desktopRows.map((_, i) => i);
let currentPage = 1;
let rowsPerPage = 25;
let currentStateFilter = 'all';

function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>'"]/g, character => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        "'": '&#39;',
        '"': '&quot;'
    })[character]);
}

document.addEventListener('DOMContentLoaded', () => {
    filterAndSort();
    initializePhotoCountTooltips();
    initializeGlobalTracking();
});

const photoCountCache = new Map();
let photoCountTooltip = null;

function getPhotoCountTooltip() {
    if (photoCountTooltip) return photoCountTooltip;
    photoCountTooltip = document.createElement('div');
    photoCountTooltip.className = 'photo-count-tooltip';
    photoCountTooltip.setAttribute('role', 'status');
    photoCountTooltip.hidden = true;
    document.body.appendChild(photoCountTooltip);
    return photoCountTooltip;
}

function positionPhotoCountTooltip(trigger) {
    const tooltip = getPhotoCountTooltip();
    const rect = trigger.getBoundingClientRect();
    const tooltipWidth = tooltip.offsetWidth || 190;
    const left = Math.min(
        Math.max(rect.left + rect.width / 2 - tooltipWidth / 2, 8),
        window.innerWidth - tooltipWidth - 8
    );
    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${Math.max(rect.top - tooltip.offsetHeight - 9, 8)}px`;
}

function showPhotoCountTooltip(trigger, message) {
    const tooltip = getPhotoCountTooltip();
    tooltip.textContent = message;
    tooltip.hidden = false;
    positionPhotoCountTooltip(trigger);
}

function hidePhotoCountTooltip(trigger) {
    trigger.dataset.photoTooltipActive = 'false';
    const tooltip = getPhotoCountTooltip();
    tooltip.hidden = true;
}

function updatePhotoCountBadges(url, count) {
    document.querySelectorAll('.photo-count-trigger').forEach(trigger => {
        if (trigger.dataset.photoCountUrl !== url) return;
        const badge = trigger.querySelector('.photo-count-badge');
        if (!badge) return;
        badge.textContent = count > 99 ? '99+' : String(count);
        badge.classList.remove('hidden');
    });
}

function photoCountMessage(payload) {
    if (!payload.folder_found) return 'Sin carpeta de fotografías en Drive';
    return payload.count === 1 ? '1 fotografía registrada' : `${payload.count} fotografías registradas`;
}

async function loadPhotoCount(trigger) {
    const url = trigger.dataset.photoCountUrl;
    trigger.dataset.photoTooltipActive = 'true';

    if (photoCountCache.has(url)) {
        const payload = photoCountCache.get(url);
        showPhotoCountTooltip(trigger, photoCountMessage(payload));
        return;
    }

    showPhotoCountTooltip(trigger, 'Consultando fotografías…');
    try {
        const response = await fetch(url, {headers: {'Accept': 'application/json'}});
        const payload = await response.json();
        if (!response.ok || !payload.success) {
            throw new Error(payload.error || 'No fue posible consultar las fotografías.');
        }
        photoCountCache.set(url, payload);
        updatePhotoCountBadges(url, payload.count);
        if (trigger.dataset.photoTooltipActive === 'true') {
            showPhotoCountTooltip(trigger, photoCountMessage(payload));
        }
    } catch (error) {
        if (trigger.dataset.photoTooltipActive === 'true') {
            showPhotoCountTooltip(trigger, error.message || 'No fue posible consultar las fotografías.');
        }
    }
}

function initializePhotoCountTooltips() {
    document.querySelectorAll('.photo-count-trigger').forEach(trigger => {
        trigger.addEventListener('mouseenter', () => loadPhotoCount(trigger));
        trigger.addEventListener('mouseleave', () => hidePhotoCountTooltip(trigger));
        trigger.addEventListener('focus', () => loadPhotoCount(trigger));
        trigger.addEventListener('blur', () => hidePhotoCountTooltip(trigger));
    });
}

// --- LÓGICA DEL RASTREO GLOBAL ---
const trackingSearchCache = new Map();
const TRACKING_CACHE_TTL_MS = 30000;
const TRACKING_DEBOUNCE_MS = 350;
let trackingSearchController = null;
let trackingSearchSequence = 0;
let trackingDebounceTimer = null;

function initializeGlobalTracking() {
    const input = document.getElementById('input-rastreo-codigo');
    const modal = document.getElementById('modal-buscador-codigo');
    if (!input || !modal) return;

    input.addEventListener('keydown', event => {
        if (event.key !== 'Enter') return;
        event.preventDefault();
        window.clearTimeout(trackingDebounceTimer);
        ejecutarRastreoCodigo();
    });

    // Anticipa la búsqueda cuando el usuario termina de escribir. La espera
    // breve y la cancelación evitan disparar consultas por cada tecla.
    input.addEventListener('input', () => {
        window.clearTimeout(trackingDebounceTimer);
        const code = input.value.trim();
        if (code.length < 2) return;
        trackingDebounceTimer = window.setTimeout(
            () => ejecutarRastreoCodigo(),
            TRACKING_DEBOUNCE_MS
        );
    });

    modal.addEventListener('click', event => {
        if (event.target === modal) cerrarBuscadorCodigo();
    });

    document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && modal.classList.contains('modal-open')) {
            cerrarBuscadorCodigo();
        }
    });
}

function abrirBuscadorCodigo() {
    const modal = document.getElementById('modal-buscador-codigo');
    const box = document.getElementById('box-buscador-codigo');

    modal.classList.add('modal-open');
    setTimeout(() => {
        box.classList.add('modal-box-open');
        document.getElementById('input-rastreo-codigo').focus();
    }, 10);
}

function cerrarBuscadorCodigo() {
    const modal = document.getElementById('modal-buscador-codigo');
    const box = document.getElementById('box-buscador-codigo');

    window.clearTimeout(trackingDebounceTimer);
    trackingSearchController?.abort();
    box.classList.remove('modal-box-open');
    setTimeout(() => { modal.classList.remove('modal-open'); }, 200);
}

function setTrackingLoading(code) {
    const emptyState = document.getElementById('rastreo-empty-state');
    const tableWrapper = document.getElementById('rastreo-tabla-wrapper');
    emptyState.classList.remove('hidden');
    tableWrapper.classList.add('hidden');
    emptyState.innerHTML = `
        <svg class="animate-spin w-8 h-8 text-blue-600 mb-3" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
        <p class="text-[13px] font-bold text-slate-600">Buscando ${escapeHtml(code)} en la planta...</p>
    `;
}

function cacheTrackingResults(code, payload) {
    if (trackingSearchCache.size >= 20) {
        trackingSearchCache.delete(trackingSearchCache.keys().next().value);
    }
    trackingSearchCache.set(code, {...payload, storedAt: Date.now()});
}

function getCachedTrackingResults(code) {
    const cached = trackingSearchCache.get(code);
    if (!cached) return null;
    if (Date.now() - cached.storedAt > TRACKING_CACHE_TTL_MS) {
        trackingSearchCache.delete(code);
        return null;
    }
    return cached;
}

function renderTrackingResults(code, results, truncated = false, resultLimit = results.length) {
    const tbody = document.getElementById('rastreo-tbody');
    const emptyState = document.getElementById('rastreo-empty-state');
    const tableWrapper = document.getElementById('rastreo-tabla-wrapper');
    const resultSummary = document.getElementById('rastreo-result-summary');

    if (results.length === 0) {
        emptyState.classList.remove('hidden');
        tableWrapper.classList.add('hidden');
        resultSummary.classList.add('hidden');
        tbody.replaceChildren();
        emptyState.innerHTML = `
            <p class="text-[13px] font-bold text-slate-600 mb-1">Sin coincidencias</p>
            <p class="text-[11px] font-medium text-slate-500">No se encontró la marca "${escapeHtml(code)}" en ningún elemento registrado.</p>
        `;
        return;
    }

    emptyState.classList.add('hidden');
    tableWrapper.classList.remove('hidden');
    tableWrapper.className = 'w-full overflow-x-auto rounded-lg border border-slate-200 shadow-sm';
    resultSummary.classList.remove('hidden');
    resultSummary.textContent = truncated
        ? `Mostrando los primeros ${resultLimit} resultados. Escribe una marca más específica para acotar el rastreo.`
        : `${results.length} ${results.length === 1 ? 'elemento encontrado' : 'elementos encontrados'}.`;

    const groupedResults = new Map();
    results.forEach(result => {
        const key = `${result.ot}|${result.pl_nombre}`;
        if (!groupedResults.has(key)) {
            groupedResults.set(key, {
                ot: result.ot,
                pl_nombre: result.pl_nombre,
                estado: result.estado,
                elementos: []
            });
        }
        groupedResults.get(key).elementos.push(result);
    });

    let html = '';
    groupedResults.forEach(group => {
        const safeOt = escapeHtml(group.ot);
        const safePackingList = escapeHtml(group.pl_nombre);
        const safeStatus = escapeHtml(group.estado);
        html += `
            <tr class="bg-slate-50 border-y border-slate-200">
                <td class="px-4 py-3 text-center border-r border-slate-200 whitespace-nowrap">
                    <div class="font-black text-slate-800 text-[13px] leading-tight">OT ${safeOt}</div>
                    <div class="text-[10px] font-extrabold text-blue-600 mt-0.5 tracking-wide">${safePackingList}</div>
                    <div class="mt-1.5"><span class="px-1.5 py-0.5 rounded text-[8px] font-bold tracking-widest uppercase bg-white border border-slate-300 text-slate-500 shadow-sm align-middle">${safeStatus}</span></div>
                </td>
                <td class="px-4 py-3 text-left border-r border-slate-200"></td>
                <td class="px-4 py-3 text-center"></td>
            </tr>
        `;

        group.elementos.forEach(element => {
            const safeBrand = escapeHtml(element.marca);
            const safeDescription = escapeHtml(element.descripcion);
            const safeQuantity = escapeHtml(element.cantidad);
            html += `
                <tr class="hover:bg-blue-50 transition-colors bg-white">
                    <td class="px-4 py-2 font-black text-blue-700 text-center border-r border-slate-100 whitespace-nowrap">${safeBrand}</td>
                    <td class="px-4 py-2 text-[11px] font-semibold text-slate-600 border-r border-slate-100 truncate max-w-[200px]" title="${safeDescription}">${safeDescription}</td>
                    <td class="px-4 py-2 font-black text-slate-800 text-center min-w-[80px]">${safeQuantity}</td>
                </tr>
            `;
        });
    });
    tbody.innerHTML = html;
}

async function ejecutarRastreoCodigo() {
    const input = document.getElementById('input-rastreo-codigo');
    const codigo = input.value.trim().toUpperCase();

    if (!codigo) {
        mostrarAlerta('Ingresa un código para buscar.', 'info');
        return;
    }
    if (codigo.length < 2) {
        mostrarAlerta('Ingresa al menos 2 caracteres para buscar.', 'info');
        return;
    }

    const cachedSearch = getCachedTrackingResults(codigo);
    if (cachedSearch) {
        renderTrackingResults(
            codigo,
            cachedSearch.results,
            cachedSearch.truncated,
            cachedSearch.resultLimit
        );
        return;
    }

    trackingSearchController?.abort();
    trackingSearchController = new AbortController();
    const sequence = ++trackingSearchSequence;
    const searchButton = document.getElementById('btn-rastrear-codigo');
    searchButton.disabled = true;
    setTrackingLoading(codigo);

    try {
        const response = await fetch(
            `/api/produccion/buscar_codigo/${encodeURIComponent(codigo)}`,
            {
                headers: {'Accept': 'application/json'},
                cache: 'no-store',
                signal: trackingSearchController.signal
            }
        );
        const results = await response.json();
        if (!response.ok || !Array.isArray(results)) {
            throw new Error(results.error || 'No fue posible completar la búsqueda.');
        }

        const truncated = response.headers.get('X-Results-Truncated') === 'true';
        const resultLimit = Number(response.headers.get('X-Result-Limit')) || results.length;
        cacheTrackingResults(codigo, {results, truncated, resultLimit});
        if (sequence === trackingSearchSequence) {
            renderTrackingResults(codigo, results, truncated, resultLimit);
        }
    } catch (error) {
        if (error.name === 'AbortError') return;
        mostrarAlerta(error.message || 'Error al conectar con la base de datos.', 'error');
        document.getElementById('rastreo-empty-state').innerHTML =
            '<p class="text-red-500 font-bold">No fue posible completar la búsqueda.</p>';
    } finally {
        if (sequence === trackingSearchSequence) searchButton.disabled = false;
    }
}

// --- FIN RASTREO GLOBAL ---

function setStateFilterDropdown(selectElement) { setStateFilter(selectElement.value, null); }

function setStateFilter(state, btnElement) {
    currentStateFilter = state;
    document.querySelectorAll('.kpi-card').forEach(b => { b.classList.remove('active'); });
    if(btnElement) { btnElement.classList.add('active'); }
    else {
        const mapping = { 'all': 0, 'en proceso': 1, 'terminado': 2, 'no empezado': 3 };
        const idx = mapping[state];
        if(idx !== undefined) document.querySelectorAll('.kpi-card')[idx].classList.add('active');
    }
    const stateDropdown = document.getElementById('stateSelect');
    if(stateDropdown && stateDropdown.value !== state) { stateDropdown.value = state; }
    filterAndSort();
}

function filterAndSort() {
    const search = document.getElementById('searchInput').value.toLowerCase();
    const sortVal = document.getElementById('sortSelect').value;
    filteredIndices = [];
    desktopRows.forEach((row, idx) => {
        const txt = row.innerText.toLowerCase();
        const st = row.dataset.state;
        let matchSt = (currentStateFilter === 'all') ? true : st.includes(currentStateFilter);
        const isCurrentYear = row.dataset.currentYear === 'true';

        if (search === '') {
            if (isCurrentYear && matchSt) { filteredIndices.push(idx); }
            else { row.style.display = 'none'; mobileCards[idx].style.display = 'none'; }
        } else {
            if (txt.includes(search) && matchSt) { filteredIndices.push(idx); }
            else { row.style.display = 'none'; mobileCards[idx].style.display = 'none'; }
        }
    });

    filteredIndices.sort((a, b) => {
        const otA = JSON.parse(desktopRows[a].dataset.json).ot;
        const otB = JSON.parse(desktopRows[b].dataset.json).ot;
        if (sortVal === 'recent') { return otB.localeCompare(otA); }
        else { return otA.localeCompare(otB); }
    });

    const tbody = document.getElementById('tableBody');
    const mContainer = document.getElementById('mobileCardsContainer');
    filteredIndices.forEach(idx => {
        tbody.appendChild(desktopRows[idx]);
        mContainer.insertBefore(mobileCards[idx], document.getElementById('emptyStateMobile'));
    });

    currentPage = 1;
    renderPagination();
}

function renderPagination() {
    const totalRows = filteredIndices.length;
    const totalPages = Math.ceil(totalRows / rowsPerPage) || 1;

    filteredIndices.forEach(idx => {
        desktopRows[idx].style.display = 'none';
        mobileCards[idx].style.display = 'none';
    });

    const start = (currentPage - 1) * rowsPerPage;
    const end = start + rowsPerPage;
    for (let i = start; i < end && i < totalRows; i++) {
        const idx = filteredIndices[i];
        desktopRows[idx].style.display = '';
        mobileCards[idx].style.display = '';
    }

    const emptyStateRow = document.getElementById('emptyStateRow');
    const emptyStateMobile = document.getElementById('emptyStateMobile');
    if (emptyStateRow) emptyStateRow.style.display = totalRows === 0 ? '' : 'none';
    if (emptyStateMobile) emptyStateMobile.style.display = totalRows === 0 ? '' : 'none';

    const infoSpan = document.getElementById('pagination-info');
    if (infoSpan) {
        const startText = totalRows === 0 ? 0 : start + 1;
        const endText = Math.min(end, totalRows);
        infoSpan.innerText = `Mostrando ${startText} a ${endText} de ${totalRows} OTs`;
    }

    const pgContainer = document.getElementById('pagination-controls');
    if(pgContainer) {
        let html = '<div class="inline-flex shadow-sm rounded-sm">';
        const prevDisabled = currentPage === 1;

        html += `<button onclick="goToPage(${currentPage - 1})" class="h-7 px-2 flex items-center justify-center border border-slate-300 bg-white rounded-l-sm ${prevDisabled ? 'opacity-50 cursor-not-allowed text-slate-400' : 'hover:bg-slate-100 text-slate-600 z-10'} transition-colors" ${prevDisabled ? 'disabled' : ''}><span class="material-symbols-rounded text-[16px]">chevron_left</span></button>`;

        let startPage = Math.max(1, currentPage - 1);
        let endPage = Math.min(totalPages, startPage + 2);
        if (endPage - startPage < 2) { startPage = Math.max(1, endPage - 2); }

        if (startPage > 1) {
            html += `<button onclick="goToPage(1)" class="h-7 px-2.5 flex items-center justify-center border border-slate-300 bg-white text-slate-700 hover:bg-slate-100 font-bold text-[11px] -ml-px z-10 transition-colors">1</button>`;
            if (startPage > 2) html += `<span class="h-7 px-2 flex items-center justify-center border border-slate-300 bg-slate-50 text-slate-400 -ml-px z-10 text-[11px]">...</span>`;
        }

        for (let p = startPage; p <= endPage; p++) {
            if (p === currentPage) { html += `<button class="h-7 px-2.5 flex items-center justify-center border border-blue-600 bg-blue-600 text-white font-bold text-[11px] -ml-px z-20">${p}</button>`; }
            else { html += `<button onclick="goToPage(${p})" class="h-7 px-2.5 flex items-center justify-center border border-slate-300 bg-white text-slate-700 hover:bg-slate-100 font-bold text-[11px] -ml-px z-10 transition-colors">${p}</button>`; }
        }

        if (endPage < totalPages) {
            if (endPage < totalPages - 1) html += `<span class="h-7 px-2 flex items-center justify-center border border-slate-300 bg-slate-50 text-slate-400 -ml-px z-10 text-[11px]">...</span>`;
            html += `<button onclick="goToPage(${totalPages})" class="h-7 px-2.5 flex items-center justify-center border border-slate-300 bg-white text-slate-700 hover:bg-slate-100 font-bold text-[11px] -ml-px z-10 transition-colors">${totalPages}</button>`;
        }

        const nextDisabled = currentPage === totalPages;
        html += `<button onclick="goToPage(${currentPage + 1})" class="h-7 px-2 flex items-center justify-center border border-slate-300 bg-white rounded-r-sm -ml-px ${nextDisabled ? 'opacity-50 cursor-not-allowed text-slate-400' : 'hover:bg-slate-100 text-slate-600 z-10'} transition-colors" ${nextDisabled ? 'disabled' : ''}><span class="material-symbols-rounded text-[16px]">chevron_right</span></button>`;
        html += '</div>';
        pgContainer.innerHTML = html;
    }
}

function goToPage(p) {
    const totalPages = Math.ceil(filteredIndices.length / rowsPerPage);
    if (p < 1 || p > totalPages) return;
    currentPage = p; renderPagination();
}

function changeRowsPerPage(selectElement) {
    rowsPerPage = parseInt(selectElement.value);
    currentPage = 1; renderPagination();
}

function mostrarAlerta(mensaje, tipo = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    const bg = tipo === 'error' ? 'bg-red-600' : (tipo === 'exito' ? 'bg-[#0f172a]' : 'bg-slate-800');
    const icon = tipo === 'error' ? 'error' : (tipo === 'exito' ? 'check_circle' : 'info');

    toast.className = `${bg} text-white px-5 py-3 rounded-full shadow-lg font-bold text-[12px] flex items-center gap-2.5 transform transition-all duration-300 -translate-y-10 opacity-0 mt-2 z-[999999]`;
    const iconElement = document.createElement('span');
    iconElement.className = 'material-symbols-rounded text-[18px]';
    iconElement.textContent = icon;
    const messageElement = document.createElement('span');
    messageElement.textContent = String(mensaje ?? '');
    toast.append(iconElement, messageElement);
    container.appendChild(toast);
    requestAnimationFrame(() => { toast.classList.remove('-translate-y-10', 'opacity-0'); toast.classList.add('translate-y-0', 'opacity-100'); });
    setTimeout(() => { toast.classList.remove('translate-y-0', 'opacity-100'); toast.classList.add('-translate-y-10', 'opacity-0'); setTimeout(() => toast.remove(), 3000); }, 3000);
}

let onConfirmCallback = null;
function solicitarConfirmacion(mensaje, callback) {
    document.getElementById('confirm-text').innerText = mensaje;
    onConfirmCallback = callback;
    const modal = document.getElementById('confirm-modal');
    const box = document.getElementById('confirm-box');
    modal.classList.remove('hidden'); requestAnimationFrame(() => { box.classList.remove('scale-95'); });
}
function cerrarModalConfirm() {
    const modal = document.getElementById('confirm-modal');
    const box = document.getElementById('confirm-box');
    box.classList.add('scale-95'); setTimeout(() => modal.classList.add('hidden'), 200); onConfirmCallback = null;
}
document.getElementById('btn-modal-ejecutar').onclick = function() {
    if(onConfirmCallback) onConfirmCallback(); cerrarModalConfirm();
};

const modal = document.getElementById('otModal');
const modalContent = document.getElementById('otModalContent');
let editingOtVersion = null;

function openModal(mode, btn = null) {
    modal.classList.add('active'); setTimeout(() => modalContent.style.transform = 'scale(1)', 10);
    document.getElementById('inputModo').value = mode;

    if (mode === 'create') {
        editingOtVersion = null;
        document.getElementById('modalTitle').innerText = 'REGISTRAR NUEVA ORDEN';
        document.getElementById('otForm').reset();
        document.getElementById('inputOT').readOnly = false;
        document.getElementById('inputDesc').value = '';
    } else {
        document.getElementById('modalTitle').innerText = 'EDITAR ORDEN DE TRABAJO';
        let dataJSON;
        if(btn.closest('tr')) { dataJSON = btn.closest('tr').dataset.json; }
        else { dataJSON = btn.closest('.ot-row-mobile').dataset.json; }

        const data = JSON.parse(dataJSON);
        editingOtVersion = Number(data.version || 1);
        document.getElementById('inputOT').value = data.ot;
        document.getElementById('inputOT').readOnly = true;
        document.getElementById('inputCliente').value = data.cliente;
        document.getElementById('inputDesc').value = data.descripcion;
        if (data.fecha_iniciado && data.fecha_iniciado !== '-') {
            const parts = data.fecha_iniciado.split('/');
            if (parts.length === 3) document.getElementById('inputFecha').value = `${parts[2]}-${parts[1]}-${parts[0]}`;
        }
        let estadoSelect = document.getElementById('inputEstado');
        for (let i = 0; i < estadoSelect.options.length; i++) {
            if (estadoSelect.options[i].value.toLowerCase() === data.estado.toLowerCase()) { estadoSelect.selectedIndex = i; break; }
        }
    }
}

function closeModal() {
    modalContent.style.transform = 'scale(0.95)'; setTimeout(() => modal.classList.remove('active'), 200);
}

async function submitOT(e) {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(e.target).entries());
    if (data.modo === 'edit') data.expected_version = editingOtVersion;
    const csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');

    try {
        const res = await fetch('/catalogo-ot/guardar', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify(data)
        });
        const payload = await res.json().catch(() => ({}));
        if (res.ok) {
            window.location.reload();
        } else {
            mostrarAlerta(payload.error || 'Error al guardar el registro.', 'error');
        }
    } catch (e) { mostrarAlerta('Error de conexión.', 'error'); }
}

function eliminarOT(id, version) {
    solicitarConfirmacion('¿Archivar esta OT? Sus datos y trazabilidad se conservarán.', async () => {
        const csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');
        try {
            const res = await fetch(`/catalogo-ot/eliminar/${id}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify({expected_version: Number(version)})
            });
            const payload = await res.json().catch(() => ({}));
            if (res.ok) window.location.reload(); else mostrarAlerta(payload.error || 'No tienes permisos o falló el archivado.', 'error');
        } catch (e) { mostrarAlerta('Error de conexión.', 'error'); }
    });
}
