let pesos = { hab: 12, arm: 24, sol: 28, lim: 12, lib: 6, gal: 6, are: 6, pin: 6, des: 0 };
const procesosProd = ['hab', 'arm', 'sol', 'lim', 'lib', 'gal', 'are', 'pin', 'des'];
let activeProcs = { hab: true, arm: true, sol: true, lim: true, lib: true, gal: true, are: false, pin: false, des: true };

pesos = {...pesos, ...(window.ProduccionConfig.processWeights || {})};
activeProcs = {...activeProcs, ...(window.ProduccionConfig.activeProcesses || {})};

const otId = window.ProduccionConfig.otId;
const currentUserId = window.ProduccionConfig.currentUserId;
const isAdmin = window.ProduccionConfig.isAdmin;
const canEdit = window.ProduccionConfig.canEdit;
let currentOtVersion = Number(window.ProduccionConfig.otVersion || 1);

let currentPlId = null;
let currentPlName = "";
let currentPlVersion = null;
let currentPlEtag = null;
let autoSyncInterval = null;
let currentDetalleRow = null;
let lastDetalleTrigger = null;

let hasPendingImport = false;
let tabsRequestInFlight = false;
let componentsRequestInFlight = false;
let messagesRequestInFlight = false;
let importSaveInFlight = false;
let cellSaveInFlight = false;
let lastMessageSyncAt = 0;
let loadedComponentsFingerprint = null;
let pendingSaveConfirmation = null;

const cellSaveTimers = new Map();
let cellSaveQueue = Promise.resolve();
let processConfigSaveQueue = Promise.resolve();
const AUTO_SYNC_INTERVAL_MS = 12000;
const MESSAGE_SYNC_INTERVAL_MS = 15000;
const CELL_SAVE_DELAY_MS = 650;

function getCsrfToken() { const meta = document.querySelector('meta[name="csrf-token"]'); return meta ? meta.getAttribute('content') : ''; }

async function readJsonResponse(response) {
    try {
        return await response.json();
    } catch (error) {
        return {};
    }
}

function responseError(data, fallback) {
    return data && typeof data.error === 'string' && data.error.trim()
        ? data.error.trim()
        : fallback;
}

function updatePackingListVersion(response, data = null) {
    const previousVersion = Number.isFinite(Number(currentPlVersion))
        ? Number(currentPlVersion)
        : null;
    const headerVersion = Number(
        response?.headers?.get('X-Packing-List-Version')
    );
    const bodyVersion = Number(data?.version ?? data?.pl?.version);
    const versions = [headerVersion, bodyVersion].filter(
        version => Number.isFinite(version) && version >= 1
    );

    const nextVersion = versions.length ? Math.max(...versions) : null;
    if (nextVersion !== null) {
        currentPlVersion = previousVersion === null
            ? nextVersion
            : Math.max(previousVersion, nextVersion);
    }

    const etag = response?.headers?.get('ETag');
    if (
        etag
        && (
            previousVersion === null
            || nextVersion === null
            || nextVersion >= previousVersion
        )
    ) {
        currentPlEtag = etag;
    }
}

function isChatOpen() {
    const drawer = document.getElementById('chat-drawer');
    return Boolean(drawer && !drawer.classList.contains('translate-x-full'));
}

function setImportBusy(isBusy) {
    importSaveInFlight = isBusy;
    const button = document.getElementById('btn-guardar-avances');
    if (!button) return;
    button.disabled = isBusy;
    button.classList.toggle('opacity-60', isBusy);
    button.classList.toggle('cursor-wait', isBusy);
}

function setPendingImport(isPending) {
    hasPendingImport = isPending;
    const status = document.getElementById('draft-status');
    if (status) status.classList.toggle('hidden', !isPending);
}

function normalizeOperatorNames(value) {
    return String(value ?? '')
        .split(/[,;\n]+/)
        .map(name => name.trim())
        .filter(Boolean)
        .filter((name, index, values) => values.findIndex(item => item.toLocaleLowerCase() === name.toLocaleLowerCase()) === index)
        .join(', ');
}

function stableComponentsFingerprint(components) {
    return JSON.stringify(components.map(component => ({
        marca: String(component.marca ?? '').trim(),
        cantidad: Number(component.cantidad || 0),
        descripcion: String(component.descripcion ?? '').trim(),
        longitud: String(component.longitud ?? '').trim(),
        hab: Number(component.hab ?? component.hab_real ?? 0),
        arm: Number(component.arm ?? component.arm_real ?? 0),
        sol: Number(component.sol ?? component.sol_real ?? 0),
        lim: Number(component.lim ?? component.lim_real ?? 0),
        lib: Number(component.lib ?? component.lib_real ?? 0),
        gal: Number(component.gal ?? component.gal_real ?? 0),
        are: Number(component.are ?? component.are_real ?? 0),
        pin: Number(component.pin ?? component.pin_real ?? 0),
        des: Number(component.des ?? component.des_real ?? 0),
        alerta: Boolean(component.alerta),
        tipo: String(component.tipo || 'fab'),
        estado_suministro: String(component.estado_suministro || 'No requerido'),
        operario: String(component.operario || '').trim()
    })));
}

function solicitarConfirmacionGuardado(nombre, cantidad) {
    const overlay = document.getElementById('save-confirm-overlay');
    if (!overlay) return Promise.resolve(window.confirm(`¿Guardar ${cantidad} elementos en "${nombre}"?`));
    document.getElementById('save-confirm-description').textContent = `Se reemplazará la información almacenada de “${nombre}”.`;
    document.getElementById('save-confirm-count').textContent = String(cantidad);
    overlay.classList.remove('hidden');
    overlay.setAttribute('aria-hidden', 'false');
    requestAnimationFrame(() => {
        overlay.classList.remove('opacity-0');
        overlay.querySelector('.production-confirm-dialog')?.classList.remove('scale-95');
    });
    return new Promise(resolve => {
        pendingSaveConfirmation = resolve;
        const close = accepted => {
            overlay.classList.add('opacity-0');
            overlay.querySelector('.production-confirm-dialog')?.classList.add('scale-95');
            overlay.setAttribute('aria-hidden', 'true');
            setTimeout(() => overlay.classList.add('hidden'), 180);
            const callback = pendingSaveConfirmation;
            pendingSaveConfirmation = null;
            callback?.(accepted);
        };
        overlay.querySelector('[data-save-confirm-accept]').onclick = () => close(true);
        overlay.querySelector('[data-save-confirm-cancel]').onclick = () => close(false);
        overlay.onclick = event => { if (event.target === overlay) close(false); };
    });
}

async function guardarFechaTermino(input) {
    if (!canEdit || !input) return;
    const previous = input.dataset.previous ?? '';
    input.disabled = true;
    try {
        const response = await fetch(`/api/produccion/ot/${otId}/fecha-termino`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken()},
            body: JSON.stringify({
                fecha_termino: input.value,
                expected_version: currentOtVersion
            })
        });
        const data = await readJsonResponse(response);
        if (!response.ok || !data.success) throw new Error(responseError(data, 'No se pudo actualizar la fecha.'));
        currentOtVersion = Number(data.version || currentOtVersion);
        input.dataset.previous = data.fecha_termino || '';
        mostrarAlerta('Fecha de término actualizada.', 'exito');
    } catch (error) {
        input.value = previous;
        mostrarAlerta(error.message, 'error');
    } finally {
        input.disabled = false;
    }
}

function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>'"]/g, character => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        "'": '&#39;',
        '"': '&quot;'
    })[character]);
}

function mostrarAlerta(mensaje, tipo = 'info') {
    const container = document.getElementById('toast-container');
    if(!container) return;
    const toast = document.createElement('div');
    const bg = tipo === 'error' ? 'bg-red-600' : (tipo === 'exito' ? 'bg-slate-900' : 'bg-blue-600');
    const icon = tipo === 'error' ? 'error' : (tipo === 'exito' ? 'check_circle' : 'info');
    toast.className = `${bg} text-white px-5 py-3 rounded-lg shadow-xl font-bold text-[13px] flex items-center gap-2 transform transition-all duration-300 -translate-y-10 opacity-0 z-[999999]`;
    const iconElement = document.createElement('span');
    iconElement.className = 'material-symbols-rounded text-[20px]';
    iconElement.textContent = icon;
    const messageElement = document.createElement('span');
    messageElement.textContent = String(mensaje ?? '');
    toast.append(iconElement, messageElement);
    container.appendChild(toast);
    requestAnimationFrame(() => { toast.classList.remove('-translate-y-10', 'opacity-0'); toast.classList.add('translate-y-0', 'opacity-100'); });
    setTimeout(() => { toast.classList.remove('translate-y-0', 'opacity-100'); toast.classList.add('-translate-y-10', 'opacity-0'); setTimeout(() => toast.remove(), 300); }, 3000);
}

document.addEventListener("DOMContentLoaded", () => {
    try {
        aplicarConfiguracionProcesosUI();
        actualizarColorFecha();
        cargarTabs();
        iniciarAutoSync();
        configurarDetalleElemento();
        const endDateInput = document.getElementById('fecha-termino-input');
        if (endDateInput) endDateInput.dataset.previous = endDateInput.value;
        window.addEventListener('resize', programarAjusteAlturaMatriz);
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) return;
            if (currentPlId && !hasPendingImport && !hayGuardadosCeldaPendientes()) sincronizarComponentesBD();
            if (isChatOpen()) cargarMensajes();
        });
        window.addEventListener('pagehide', () => {
            if (autoSyncInterval) clearInterval(autoSyncInterval);
            cellSaveTimers.forEach(timerId => clearTimeout(timerId));
            cellSaveTimers.clear();
        });
        window.setTimeout(ajustarAlturaMatriz, 250);
    } catch (e) {
        console.error("Error inicializando Producción:", e);
        mostrarAlerta("No fue posible inicializar la pantalla de Producción.", "error");
    }
});


let matrixResizeTimer = null;

function programarAjusteAlturaMatriz() {
    window.clearTimeout(matrixResizeTimer);
    matrixResizeTimer = window.setTimeout(ajustarAlturaMatriz, 100);
}

function configurarDetalleElemento() {
    const overlay = document.getElementById('detalle-overlay');
    if (!overlay) return;

    overlay.addEventListener('click', (event) => {
        if (event.target === overlay) cerrarDetalle();
    });

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && !overlay.classList.contains('hidden')) {
            cerrarDetalle();
        }
    });
}

function ajustarAlturaMatriz() {
    const wrapper = document.querySelector('.matrix-wrapper');
    const tableModule = document.getElementById('table-module');
    if (!wrapper || !tableModule || tableModule.classList.contains('table-maximized')) return;

    if (window.innerWidth < 768) {
        wrapper.style.removeProperty('height');
        wrapper.style.removeProperty('max-height');
        return;
    }

    const top = wrapper.getBoundingClientRect().top;
    if (top <= 0) return;
    const availableHeight = Math.max(320, Math.floor(window.innerHeight - top - 12));
    wrapper.style.height = `${availableHeight}px`;
    wrapper.style.maxHeight = `${availableHeight}px`;
}


function abrirModalPL(modalId, boxId, inputId) {
    if (!canEdit) return;
    const modal = document.getElementById(modalId);
    const box = document.getElementById(boxId);
    document.getElementById(inputId).value = '';
    modal.classList.remove('hidden');
    setTimeout(() => { modal.classList.remove('opacity-0'); box.classList.remove('scale-95'); document.getElementById(inputId).focus(); }, 10);
}

function cerrarModalPL(modalId, boxId) {
    const modal = document.getElementById(modalId);
    const box = document.getElementById(boxId);
    modal.classList.add('opacity-0'); box.classList.add('scale-95');
    setTimeout(() => modal.classList.add('hidden'), 200);
}

async function cargarTabs() {
    if (tabsRequestInFlight) return;
    tabsRequestInFlight = true;

    try {
        const res = await fetch(`/api/produccion/packing_lists/${otId}`, {
            headers: { 'Accept': 'application/json' }
        });
        const data = await readJsonResponse(res);
        if (!res.ok) {
            throw new Error(responseError(data, "No se pudieron cargar las packing lists."));
        }
        if (!Array.isArray(data)) {
            throw new Error("La respuesta de packing lists no es válida.");
        }

        const pls = data;
        const container = document.getElementById('tabs-container');
        if (!container) return;

        if (pls.length === 0) {
            document.getElementById('empty-tabs-state')?.classList.remove('hidden');
            document.getElementById('main-content')?.classList.add('hidden');
            container.classList.add('hidden');
            container.innerHTML = '';
            currentPlId = null;
            currentPlName = "";
            currentPlVersion = null;
            currentPlEtag = null;
            setPendingImport(false);
            return;
        }

        document.getElementById('empty-tabs-state')?.classList.add('hidden');
        document.getElementById('main-content')?.classList.remove('hidden');
        container.classList.remove('hidden');

        const currentStillExists = pls.some(pl => Number(pl.id) === Number(currentPlId));
        if (!currentStillExists) {
            currentPlId = Number(pls[0].id);
            currentPlEtag = null;
            setPendingImport(false);
        }

        let html = '';
        pls.forEach((pl, index) => {
            const plId = Number(pl.id);
            const isActive = plId === Number(currentPlId)
                || (currentPlId === null && index === 0);

            if (isActive) {
                const previousId = currentPlId;
                currentPlId = plId;
                currentPlName = String(pl.nombre || '');
                const listedVersion = Number(pl.version || 1);
                if (Number(previousId) !== plId) currentPlEtag = null;
                currentPlVersion = Number.isFinite(listedVersion) ? listedVersion : 1;
            }

            const css = isActive
                ? 'border-blue-600 text-blue-700 bg-blue-50/50 hover:bg-blue-100'
                : 'border-transparent text-slate-500 hover:text-slate-800 hover:bg-slate-100';
            const dragAttributes = canEdit
                ? 'draggable="true" ondragstart="handleDragStart(event)" ondragover="handleDragOver(event)" ondragenter="handleDragEnter(event)" ondragleave="handleDragLeave(event)" ondrop="handleDrop(event)" ondragend="handleDragEnd(event)"'
                : 'draggable="false"';

            html += `<button ${dragAttributes} data-id="${plId}" data-version="${Number(pl.version || 1)}" onclick="seleccionarTab(${plId})" class="tab-item mb-1 shrink-0 rounded-md px-4 py-2 text-[12px] font-bold uppercase tracking-wider shadow-sm ${css} transition-colors">${escapeHtml(pl.nombre)}</button>`;
        });

        if (canEdit) {
            html += `<button onclick="abrirModalPL('modal-nuevo-pl', 'box-nuevo-pl', 'input-nuevo-pl')" class="mb-1 ml-1 flex shrink-0 items-center gap-1 rounded-md border border-dashed border-blue-300 bg-white px-3 py-2 text-[12px] font-bold text-blue-700 transition-colors hover:bg-blue-50"><span class="material-symbols-rounded text-[16px]">add</span> Lista</button>`;
        }
        container.innerHTML = html;

        if (currentPlId) {
            await cargarComponentesTab({ force: true });
        }
    } catch (error) {
        console.error("Error al cargar packing lists:", error);
        mostrarAlerta(error.message || "No se pudieron cargar las packing lists.", "error");
    } finally {
        tabsRequestInFlight = false;
    }
}

function seleccionarTab(id) {
    const nextId = Number(id);
    if (Number(currentPlId) === nextId) return;

    if (hasPendingImport) {
        const discard = confirm(
            "Hay datos de Excel pendientes de guardar.\n\n" +
            "¿Deseas descartarlos y cambiar de packing list?"
        );
        if (!discard) return;
    }

    setPendingImport(false);
    currentPlId = nextId;
    currentPlVersion = null;
    currentPlEtag = null;
    cargarTabs();
}

async function guardarNuevoPL() {
    if (!canEdit) return;
    const input = document.getElementById('input-nuevo-pl');
    const nombre = input.value.trim().toUpperCase();
    if (!nombre) {
        mostrarAlerta("Debes ingresar un nombre.", "info");
        input.focus();
        return;
    }

    try {
        const res = await fetch('/api/produccion/packing_lists', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify({ ot_id: otId, nombre })
        });
        const data = await readJsonResponse(res);
        if (!res.ok || !data.success) {
            throw new Error(responseError(data, "No se pudo crear la packing list."));
        }

        cerrarModalPL('modal-nuevo-pl', 'box-nuevo-pl');
        currentPlId = Number(data.pl.id);
        currentPlName = String(data.pl.nombre || nombre);
        currentPlVersion = Number(data.pl.version || 1);
        currentPlEtag = null;
        setPendingImport(false);
        await cargarTabs();
        mostrarAlerta(`Pestaña "${nombre}" creada.`, "exito");
    } catch (error) {
        mostrarAlerta(error.message || "No se pudo crear la packing list.", "error");
    }
}

function prepararRenombrarPL() { if(!isAdmin || !currentPlId) return; abrirModalPL('modal-renombrar-pl', 'box-renombrar-pl', 'input-renombrar-pl'); document.getElementById('input-renombrar-pl').value = currentPlName; }

async function guardarRenombrePL() {
    if (!isAdmin || !currentPlId) return;
    const input = document.getElementById('input-renombrar-pl');
    const nombre = input.value.trim().toUpperCase();
    if (!nombre) {
        mostrarAlerta("Ingresa un nombre válido.", "info");
        input.focus();
        return;
    }

    try {
        const res = await fetch(`/api/produccion/packing_lists/${currentPlId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify({ nombre })
        });
        const data = await readJsonResponse(res);
        if (!res.ok || !data.success) {
            throw new Error(responseError(data, "No se pudo renombrar la packing list."));
        }

        currentPlName = String(data.pl?.nombre || nombre);
        currentPlVersion = Number(data.pl?.version || currentPlVersion || 1);
        currentPlEtag = null;
        cerrarModalPL('modal-renombrar-pl', 'box-renombrar-pl');
        await cargarTabs();
        mostrarAlerta("Nombre actualizado.", "exito");
    } catch (error) {
        mostrarAlerta(error.message || "No se pudo renombrar la packing list.", "error");
    }
}

async function eliminarMatrizActual() {
    if (!isAdmin || !currentPlId) return;
    if (!confirm(
        `⚠️ ATENCIÓN ADMIN ⚠️\n\n` +
        `Se archivará "${currentPlName}".\n` +
        `Sus elementos y trazabilidad se conservarán.\n\n¿Deseas continuar?`
    )) return;

    try {
        const res = await fetch(`/api/produccion/packing_lists/${currentPlId}`, {
            method: 'DELETE',
            headers: { 'X-CSRFToken': getCsrfToken() }
        });
        const data = await readJsonResponse(res);
        if (!res.ok || !data.success) {
            throw new Error(responseError(data, "No se pudo archivar la packing list."));
        }

        mostrarAlerta("Packing list archivada.", "exito");
        currentPlId = null;
        currentPlName = "";
        currentPlVersion = null;
        currentPlEtag = null;
        setPendingImport(false);
        await cargarTabs();
    } catch (error) {
        mostrarAlerta(error.message || "No se pudo archivar la packing list.", "error");
    }
}

let draggedTab = null;
function handleDragStart(e) { if (!canEdit) return; draggedTab = e.target; e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', draggedTab.dataset.id); setTimeout(() => e.target.classList.add('opacity-50'), 0); }
function handleDragOver(e) { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; return false; }
function handleDragEnter(e) { e.preventDefault(); e.target.classList.add('bg-slate-200'); }
function handleDragLeave(e) { e.target.classList.remove('bg-slate-200'); }
function handleDragEnd(e) { e.target.classList.remove('opacity-50'); document.querySelectorAll('.tab-item').forEach(t => t.classList.remove('bg-slate-200')); }
async function handleDrop(e) {
    if (!canEdit) return false;
    e.stopPropagation(); const dropTarget = e.target.closest('.tab-item');
    if (draggedTab !== dropTarget && dropTarget) {
        const container = document.getElementById('tabs-container'); const allTabs = Array.from(container.querySelectorAll('.tab-item'));
        const srcIdx = allTabs.indexOf(draggedTab); const destIdx = allTabs.indexOf(dropTarget);
        if (srcIdx < destIdx) { dropTarget.parentNode.insertBefore(draggedTab, dropTarget.nextSibling); } else { dropTarget.parentNode.insertBefore(draggedTab, dropTarget); }
        guardarOrdenTabs();
    }
    return false;
}
async function guardarOrdenTabs() {
    if (!canEdit) return;
    const tabs = document.querySelectorAll('.tab-item');
    const ordenIds = Array.from(tabs)
        .map(tab => Number.parseInt(tab.dataset.id, 10))
        .filter(Number.isFinite);

    try {
        const res = await fetch('/api/produccion/packing_lists/reordenar', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify({ orden: ordenIds })
        });
        const data = await readJsonResponse(res);
        if (!res.ok || !data.success) {
            throw new Error(responseError(data, "No se pudo guardar el nuevo orden."));
        }
        mostrarAlerta("Orden actualizado.", "exito");
    } catch (error) {
        mostrarAlerta(error.message || "No se pudo guardar el nuevo orden.", "error");
        await cargarTabs();
    }
}

const nombresTipos = {
    'fab': 'MATERIALES DE FABRICACIÓN',
    'p_template': 'PERNERÍA TEMPLATE',
    'p_torre': 'PERNERÍA TORRE',
    'c_vida': 'CABLE DE VIDA',
    'vientos': 'SISTEMA DE VIENTOS',
    'fabricacion': 'MATERIALES DE FABRICACIÓN',
    'suministro': 'OTROS SUMINISTROS'
};


function parseOperarios(str) {
    let op = {}; if(!str) return op;
    str.split('|').forEach(pair => {
        let parts = pair.split(':');
        if(parts.length === 2) op[parts[0]] = parts[1];
    });
    return op;
}
function stringifyOperarios(op) {
    return Object.entries(op).filter(([k,v]) => v.trim() !== '').map(([k,v]) => `${k}:${v}`).join('|');
}


async function obtenerComponentesRemotos({ force = false } = {}) {
    if (!currentPlId || componentsRequestInFlight) return null;
    componentsRequestInFlight = true;

    try {
        const headers = { 'Accept': 'application/json' };
        if (!force && currentPlEtag) headers['If-None-Match'] = currentPlEtag;

        const res = await fetch(`/api/produccion/componentes/${currentPlId}`, {
            headers
        });

        if (res.status === 304) {
            updatePackingListVersion(res);
            return { notModified: true, componentes: [] };
        }

        const data = await readJsonResponse(res);
        if (!res.ok) {
            throw new Error(responseError(data, "No se pudieron cargar los elementos."));
        }
        if (!Array.isArray(data)) {
            throw new Error("La respuesta de elementos no es válida.");
        }

        updatePackingListVersion(res);
        return { notModified: false, componentes: data };
    } finally {
        componentsRequestInFlight = false;
    }
}

async function cargarComponentesTab({ force = false } = {}) {
    if (!currentPlId) return;
    if (hasPendingImport && !force) return;

    try {
        const result = await obtenerComponentesRemotos({ force });
        if (!result || result.notModified) return;
        renderizarTabla(result.componentes, true);
        loadedComponentsFingerprint = stableComponentsFingerprint(result.componentes);
    } catch (error) {
        console.error("Error al cargar elementos:", error);
        mostrarAlerta(error.message || "No se pudieron cargar los elementos.", "error");
    }
}

function iniciarAutoSync() {
    if (autoSyncInterval) clearInterval(autoSyncInterval);

    autoSyncInterval = setInterval(() => {
        if (document.hidden) return;

        if (currentPlId && !hasPendingImport && !hayGuardadosCeldaPendientes()) {
            sincronizarComponentesBD();
        }

        const now = Date.now();
        if (
            isChatOpen()
            && now - lastMessageSyncAt >= MESSAGE_SYNC_INTERVAL_MS
        ) {
            cargarMensajes();
        }
    }, AUTO_SYNC_INTERVAL_MS);
}

async function sincronizarComponentesBD() {
    if (!currentPlId || hasPendingImport || hayGuardadosCeldaPendientes() || document.hidden) return;

    try {
        const result = await obtenerComponentesRemotos();
        if (!result || result.notModified) return;

        const componentes = result.componentes;
        const tbody = document.getElementById('matriz-body');
        if (!tbody) return;

        const filas = Array.from(tbody.querySelectorAll('tr[data-cant]'));
        const remoteIds = componentes.map(item => String(item.id));
        const localIds = filas.map(row => String(row.dataset.id || ''));

        const structureChanged = (
            componentes.length !== filas.length
            || remoteIds.some((id, index) => id !== localIds[index])
        );
        if (structureChanged) {
            renderizarTabla(componentes, true);
            loadedComponentsFingerprint = stableComponentsFingerprint(componentes);
            return;
        }

        const mapComp = {};
        componentes.forEach(component => {
            mapComp[String(component.id)] = component;
        });

        filas.forEach(tr => {
            const bdComp = mapComp[String(tr.dataset.id)];
            if (!bdComp) return;
            const cant = Number.parseFloat(tr.dataset.cant) || 0;

            const inputOperario = tr.querySelector('.input-operario');
            if (
                inputOperario
                && document.activeElement !== inputOperario
                && inputOperario.value !== String(bdComp.operario || '')
            ) {
                inputOperario.value = String(bdComp.operario || '');
            }

            const isSuministro = (
                bdComp.tipo !== 'fab'
                && bdComp.tipo !== 'fabricacion'
            );

            if (isSuministro) {
                const selectEstado = tr.querySelector('.select-estado-suministro');
                if (
                    selectEstado
                    && document.activeElement !== selectEstado
                    && selectEstado.value !== bdComp.estado_suministro
                ) {
                    selectEstado.value = bdComp.estado_suministro;
                    actualizarEstadoUI(selectEstado);
                }
            } else {
                procesosProd.forEach(proc => {
                    if (proc === 'des') return;
                    const input = tr.querySelector(`.proc-${proc}`);
                    const remoteValue = Number(bdComp[`${proc}_real`]);
                    if (
                        input
                        && document.activeElement !== input
                        && Number(input.value) !== remoteValue
                    ) {
                        input.value = remoteValue;
                        validarYCalcular(input, cant, proc, true);
                    }
                });
            }

            const inputDespacho = tr.querySelector('.proc-des');
            const remoteDispatch = Number(bdComp.des_real);
            if (
                inputDespacho
                && document.activeElement !== inputDespacho
                && Number(inputDespacho.value) !== remoteDispatch
            ) {
                inputDespacho.value = remoteDispatch;
                validarYCalcular(inputDespacho, cant, 'des', true);
            }

            const alertButton = tr.querySelector('button[title="Reportar incidencia"]');
            if (alertButton) {
                const hasAlert = tr.classList.contains('row-alert');
                if (bdComp.alerta && !hasAlert) {
                    tr.classList.add('row-alert');
                    alertButton.innerHTML = `<span class="material-symbols-rounded text-[18px] text-red-500">warning</span>`;
                } else if (!bdComp.alerta && hasAlert) {
                    tr.classList.remove('row-alert');
                    alertButton.innerHTML = `<span class="material-symbols-rounded text-[18px] text-slate-300 hover:text-slate-500 transition-colors">emoji_flags</span>`;
                }
            }
        });
        loadedComponentsFingerprint = stableComponentsFingerprint(componentes);
    } catch (error) {
        console.error("Error sincronizando elementos:", error);
    }
}

async function guardarCampoComponente(componentId, campo, valor) {
    cellSaveInFlight = true;
    try {
        const res = await fetch('/api/produccion/actualizar_celda', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify({
                id: Number(componentId),
                campo,
                valor,
                expected_version: Number(currentPlVersion)
            })
        });
        const data = await readJsonResponse(res);
        if (!res.ok || !data.success) {
            if (Number.isFinite(Number(data.current_version))) {
                currentPlVersion = Number(data.current_version);
            }
            throw new Error(responseError(data, "No se pudo guardar el cambio."));
        }
        updatePackingListVersion(res, data);
        return true;
    } catch (error) {
        mostrarAlerta(error.message || "No se pudo guardar el cambio.", "error");
        window.setTimeout(() => sincronizarComponentesBD(), 500);
        return false;
    } finally {
        cellSaveInFlight = false;
    }
}

function hayGuardadosCeldaPendientes() {
    return cellSaveInFlight || cellSaveTimers.size > 0;
}

function programarGuardadoCelda(componentId, campo, valor) {
    const key = `${componentId}:${campo}`;
    const previousTimer = cellSaveTimers.get(key);
    if (previousTimer) clearTimeout(previousTimer);

    const timerId = window.setTimeout(() => {
        cellSaveTimers.delete(key);
        cellSaveQueue = cellSaveQueue
            .then(() => guardarCampoComponente(componentId, campo, valor))
            .catch(() => false);
    }, CELL_SAVE_DELAY_MS);

    cellSaveTimers.set(key, timerId);
}

async function guardarPackingListBD() {
    if (!canEdit || importSaveInFlight) return;

    const filas = Array.from(
        document.querySelectorAll('#matriz-body tr[data-cant]')
    );
    if (filas.length === 0) {
        mostrarAlerta("Sube el Excel primero.", "error");
        return;
    }
    if (!currentPlId) {
        mostrarAlerta("Selecciona un Packing List primero.", "error");
        return;
    }
    if (!Number.isFinite(Number(currentPlVersion))) {
        mostrarAlerta(
            "No se pudo identificar la versión de esta lista. Recarga la pantalla.",
            "error"
        );
        return;
    }

    const componentes = [];
    filas.forEach(fila => {
        const tipoRow = fila.dataset.tipo || 'fab';
        const isSuministro = (
            tipoRow !== 'fab'
            && tipoRow !== 'fabricacion'
        );
        const values = {};

        if (!isSuministro) {
            procesosProd.forEach(process => {
                if (process === 'des') return;
                const input = fila.querySelector(`.proc-${process}`);
                values[process] = input
                    ? (Number.parseFloat(input.value) || 0)
                    : 0;
            });
        }

        const inputDespacho = fila.querySelector('.proc-des');
        values.des = inputDespacho
            ? (Number.parseFloat(inputDespacho.value) || 0)
            : 0;

        const inputOperario = fila.querySelector('.input-operario');
        const selectEstado = fila.querySelector('.select-estado-suministro');

        componentes.push({
            marca: fila.cells[1].innerText.trim(),
            cantidad: Number.parseInt(fila.dataset.cant, 10) || 0,
            descripcion: fila.cells[3].innerText.trim(),
            longitud: fila.cells[4].innerText.trim(),
            hab: values.hab || 0,
            arm: values.arm || 0,
            sol: values.sol || 0,
            lim: values.lim || 0,
            lib: values.lib || 0,
            gal: values.gal || 0,
            are: values.are || 0,
            pin: values.pin || 0,
            des: values.des || 0,
            alerta: fila.classList.contains('row-alert'),
            tipo: tipoRow,
            estado_suministro: selectEstado
                ? selectEstado.value
                : 'No requerido',
            operario: inputOperario
                ? inputOperario.value.trim()
                : ''
        });
    });

    const currentFingerprint = stableComponentsFingerprint(componentes);
    if (!hasPendingImport && loadedComponentsFingerprint === currentFingerprint) {
        mostrarAlerta('No hay cambios pendientes por guardar.', 'info');
        return;
    }

    const confirmed = await solicitarConfirmacionGuardado(currentPlName, componentes.length);
    if (!confirmed) return;

    setImportBusy(true);
    try {
        const res = await fetch('/api/produccion/importar', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify({
                pl_id: currentPlId,
                expected_version: Number(currentPlVersion),
                componentes
            })
        });
        const data = await readJsonResponse(res);

        if (res.status === 409) {
            if (Number.isFinite(Number(data.current_version))) {
                currentPlVersion = Number(data.current_version);
                currentPlEtag = null;
            }

            const reload = confirm(
                `${responseError(data, "Otra persona modificó esta packing list.")}\n\n` +
                `¿Deseas recargar la información actual?\n` +
                `Los datos del Excel que aún no guardaste se descartarán.`
            );
            if (reload) {
                setPendingImport(false);
                await cargarComponentesTab({ force: true });
            }
            return;
        }

        if (!res.ok || !data.success) {
            throw new Error(responseError(data, "No se pudo guardar la packing list."));
        }

        updatePackingListVersion(res, data);
        loadedComponentsFingerprint = currentFingerprint;
        setPendingImport(false);
        mostrarAlerta(
            `Guardado: ${data.imported_count ?? componentes.length} elementos.`,
            "exito"
        );
        await cargarComponentesTab({ force: true });
    } catch (error) {
        mostrarAlerta(error.message || "Error de conexión al guardar.", "error");
    } finally {
        setImportBusy(false);
    }
}

function renderizarTabla(componentes, isFromDB) {
    const tbody = document.getElementById('matriz-body');
    if(!tbody) return;

    tbody.innerHTML = '';
    let piezas = 0;

    if (componentes.length === 0) {
        const emptyMessage = canEdit
            ? 'Usa "Subir Excel" para cargar la data de esta pestaña.'
            : 'Esta lista todavía no tiene elementos registrados.';
        tbody.innerHTML = `<tr><td colspan="40" class="px-4 py-20 text-center bg-white"><div class="flex flex-col items-center justify-center"><span class="material-symbols-rounded text-[36px] text-slate-200 mb-2 block">grid_on</span><h4 class="text-[13px] font-bold text-slate-600 mb-0.5">Matriz Vacía</h4><p class="text-[11px] text-slate-400 font-medium">${emptyMessage}</p></div></td></tr>`;
        document.getElementById('contador-piezas').innerText = '0 Regs';
        recalcularMatriz();
        window.requestAnimationFrame(ajustarAlturaMatriz);
        return;
    }

    const ordenGrupos = ['MATERIALES DE FABRICACIÓN', 'PERNERÍA TEMPLATE', 'PERNERÍA TORRE', 'CABLE DE VIDA', 'SISTEMA DE VIENTOS', 'OTROS SUMINISTROS'];
    const grupos = {}; ordenGrupos.forEach(g => grupos[g] = []);

    componentes.forEach(comp => {
        let catNombre = nombresTipos[comp.tipo] || 'MATERIALES DE FABRICACIÓN';
        if (!grupos[catNombre]) grupos[catNombre] = [];
        grupos[catNombre].push(comp);
    });

    let totalCols = 9;
    procesosProd.forEach(p => { if (p !== 'des' && activeProcs[p]) totalCols += 3; });

    ordenGrupos.forEach(categoria => {
        const items = grupos[categoria];
        if (!items || items.length === 0) return;


        const trHeader = document.createElement('tr');
        trHeader.innerHTML = `<td colspan="${totalCols}" class="sticky left-0 z-10 border-y border-slate-200 bg-slate-50 px-4 py-3">
            <div class="flex items-center gap-2">
                <span class="text-slate-700 font-black text-[11px] uppercase tracking-widest">${escapeHtml(categoria)}</span>
                <span class="text-slate-500 font-bold ml-1 text-[10px] bg-white border border-slate-200 px-1.5 py-0.5 rounded shadow-sm">${items.length} regs</span>
            </div>
        </td>`;
        tbody.appendChild(trHeader);

        items.forEach(comp => {
            const marca = comp.marca || 'S/M';
            const cant = parseFloat(comp.cantidad) || 0;
            const desc = comp.descripcion || '';
            const long = comp.longitud || '0.0';
            const dbId = isFromDB ? comp.id : null;
            const tipo = comp.tipo || 'fab';
            const isSuministro = tipo !== 'fab' && tipo !== 'fabricacion';
            const operario = comp.operario || '';
            const estadoSuministro = comp.estado_suministro || 'No requerido';

            const safeMarca = escapeHtml(marca);
            const safeDescription = escapeHtml(desc);
            const safeLength = escapeHtml(long);
            const safeOperator = escapeHtml(operario);

            const v = { hab: isFromDB ? comp.hab_real : 0, arm: isFromDB ? comp.arm_real : 0, sol: isFromDB ? comp.sol_real : 0, lim: isFromDB ? comp.lim_real : 0, lib: isFromDB ? comp.lib_real : 0, gal: isFromDB ? comp.gal_real : 0, are: isFromDB ? comp.are_real : 0, pin: isFromDB ? comp.pin_real : 0, des: isFromDB ? comp.des_real : 0 };
            const alerta = isFromDB ? comp.alerta : false; const alertClass = alerta ? 'row-alert' : ''; const alertIcon = alerta ? '<span class="material-symbols-rounded text-[18px] text-red-500">warning</span>' : '<span class="material-symbols-rounded text-[18px] text-slate-300 hover:text-slate-500 transition-colors">emoji_flags</span>';
            const alertControl = canEdit
                ? `<button onclick="toggleAlertaFila(this)" class="w-6 h-6 rounded flex items-center justify-center transition mx-auto" title="Reportar incidencia">${alertIcon}</button>`
                : `<span class="flex h-6 w-6 items-center justify-center mx-auto" title="${alerta ? 'Elemento con incidencia' : 'Sin incidencia'}">${alertIcon}</span>`;

            const tr = document.createElement('tr');
            tr.className = `hover:bg-slate-50 bg-white transition-colors group border-b border-slate-100 ${alertClass}`;
            tr.dataset.cant = cant; tr.dataset.tipo = tipo;
            if (dbId) tr.dataset.id = dbId;

            let html = `<td class="px-1 py-1.5 border-r border-slate-100 sticky-c-alert bg-white text-center align-middle group-hover:bg-slate-50 transition-colors">${alertControl}</td>
                <td class="px-2 py-1.5 font-black text-slate-800 text-center border-r border-slate-100 sticky-c1 bg-white align-middle group-hover:bg-slate-50 transition-colors">${safeMarca}</td>
                <td class="px-1 py-1.5 text-center font-black text-blue-700 border-r border-slate-100 sticky-c2 bg-white align-middle group-hover:bg-slate-50 transition-colors">${cant}</td>
                <td class="px-3 py-1.5 text-left truncate text-[11px] border-r border-slate-100 sticky-c3 bg-white align-middle group-hover:bg-slate-50 transition-colors" title="${safeDescription}">${safeDescription}</td>
                <td class="px-1 py-1.5 text-center text-slate-500 border-r border-slate-100 text-[11px] sticky-c4 bg-white align-middle group-hover:bg-slate-50 transition-colors">${safeLength}</td>
                <td class="px-1 py-1.5 border-r border-slate-200 sticky-c5 bg-white shadow-right align-middle text-center group-hover:bg-slate-50 transition-colors">
                    <input type="hidden" class="input-operario" value="${safeOperator}">
                    <button type="button" class="btn-detalle text-slate-400 transition-colors" title="${canEdit ? 'Abrir ficha y gestionar procesos' : 'Abrir ficha del elemento'}" aria-label="Abrir ficha del elemento ${safeMarca}">
                        <span class="material-symbols-rounded text-[18px] block">more_horiz</span>
                    </button>
                </td>`;

            if (isSuministro) {
                let numColumnasProceso = 0;
                procesosProd.forEach(proc => { if (proc !== 'des' && activeProcs[proc]) numColumnasProceso += 3; });

                let bgEstado = '';
                if (estadoSuministro === 'No requerido') bgEstado = 'text-slate-500 border-slate-300 bg-white';
                else if (estadoSuministro === 'En compra') bgEstado = 'text-blue-600 border-blue-400 bg-white';
                else if (estadoSuministro === 'Comprado') bgEstado = 'text-teal-600 border-teal-400 bg-white';
                else if (estadoSuministro === 'En almacén') bgEstado = 'text-indigo-600 border-indigo-400 bg-white';
                else if (estadoSuministro === 'Despachado') bgEstado = 'text-emerald-700 border-emerald-400 bg-white';

                html += `<td colspan="${numColumnasProceso}" class="px-4 py-1.5 border-r border-slate-200 text-center align-middle bg-slate-50/30">
                    <div class="flex items-center justify-center w-full">
                        <select class="text-[11px] font-bold outline-none rounded-md px-2 py-1 border transition-colors w-[120px] text-center select-estado-suministro ${bgEstado} ${canEdit ? 'cursor-pointer' : 'cursor-default opacity-80'}" ${canEdit ? 'onchange="actualizarEstadoSuministro(this)"' : 'disabled aria-readonly="true"'}>
                            <option value="No requerido" ${estadoSuministro === 'No requerido' ? 'selected' : ''}>No requerido</option>
                            <option value="En compra" ${estadoSuministro === 'En compra' ? 'selected' : ''}>En compra</option>
                            <option value="Comprado" ${estadoSuministro === 'Comprado' ? 'selected' : ''}>Comprado</option>
                            <option value="En almacén" ${estadoSuministro === 'En almacén' ? 'selected' : ''}>En almacén</option>
                            <option value="Despachado" ${estadoSuministro === 'Despachado' ? 'selected' : ''}>Despachado</option>
                        </select>
                    </div>
                </td>`;
            } else {
                procesosProd.forEach(proc => {
                    if (proc === 'des') return;
                    const isHidden = !activeProcs[proc] ? 'display: none;' : '';
                    const isNA = v[proc] === -1;

                    html += `<td class="px-1 py-1.5 text-center border-r border-slate-100 font-bold text-slate-400 col-${proc} align-middle" style="${isHidden}">${isNA ? '-' : cant}</td>
                        <td class="px-1 py-1.5 border-r border-slate-100 col-${proc} align-middle" style="${isHidden}"><input type="number" value="${v[proc]}" min="-1" max="${cant}" ${canEdit ? `oninput="validarYCalcular(this, ${cant}, '${proc}')"` : 'disabled aria-readonly="true"'} class="cell-input proc-${proc} ${isNA ? 'text-slate-300' : ''} ${canEdit ? '' : 'cursor-default bg-slate-50'}"></td>
                        <td class="px-1 py-1.5 text-center font-medium text-slate-400 bg-white border-r border-slate-200 pct-${proc} col-${proc} align-middle group-hover:bg-slate-50 transition-colors" style="${isHidden}">${isNA ? 'N/A' : '0.0%'}</td>`;
                });
            }

            html += `<td class="px-2 py-1.5 border-l border-r border-slate-200 sticky-r3 bg-white shadow-left align-middle group-hover:bg-slate-50 transition-colors"><input type="number" value="${v.des}" min="0" max="${cant}" ${canEdit ? `oninput="validarYCalcular(this, ${cant}, 'des')"` : 'disabled aria-readonly="true"'} class="cell-input proc-des ${canEdit ? '' : 'cursor-default bg-slate-50'}"></td>
                <td class="px-1 py-1.5 text-center bg-slate-50 border-r border-slate-200 sticky-r2 pct-des text-slate-400 font-medium align-middle">-</td>
                <td class="px-2 py-1.5 text-center font-black text-white bg-slate-900 sticky-r1 shadow-left row-total-percentage align-middle">0.0%</td>`;

            tr.innerHTML = html;
            const detailButton = tr.querySelector('.btn-detalle');
            if (detailButton) {
                detailButton.addEventListener('click', () => {
                    abrirDetalle(detailButton, marca, long, cant, desc, tipo);
                });
            }
            tbody.appendChild(tr); piezas++;

            if(!isSuministro) {
                procesosProd.forEach(proc => { if(proc !== 'des') { const inp = tr.querySelector(`.proc-${proc}`); if (inp && inp.value !== 0 && inp.value !== "0") validarYCalcular(inp, cant, proc, true); }});
            }
            const inpDes = tr.querySelector('.proc-des');
            if(inpDes && inpDes.value > 0) validarYCalcular(inpDes, cant, 'des', true);
        });
    });

    const lbl = document.getElementById('contador-piezas');
    if(lbl) lbl.innerText = `${piezas} Regs`;
    recalcularMatriz();
    window.requestAnimationFrame(ajustarAlturaMatriz);
}

function importarPackingList(event) {
    if (!canEdit || !currentPlId) return;
    const file = event.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = function(loadEvent) {
        try {
            const data = new Uint8Array(loadEvent.target.result);
            const workbook = XLSX.read(data, { type: 'array' });
            const firstSheet = workbook.Sheets[workbook.SheetNames[0]];
            const json = XLSX.utils.sheet_to_json(firstSheet, {
                header: 1,
                defval: ""
            });

            let headerRowIdx = -1;
            for (let index = 0; index < Math.min(json.length, 30); index++) {
                const row = json[index];
                if (!row || !Array.isArray(row)) continue;
                const isHeader = row.some(cell => {
                    if (typeof cell !== 'string') return false;
                    const text = cell.toUpperCase();
                    return (
                        text.includes('MARCA')
                        || text.includes('CÓDIGO')
                        || text.includes('CODIGO')
                        || text === 'X3'
                    );
                });
                if (isHeader) {
                    headerRowIdx = index;
                    break;
                }
            }

            if (headerRowIdx === -1) {
                mostrarAlerta(
                    "No se detectó el formato del Packing List.",
                    "error"
                );
                return;
            }

            const headers = json[headerRowIdx].map(header => (
                typeof header === 'string'
                    ? header.toUpperCase().trim()
                    : ""
            ));
            const idxMarca = headers.findIndex(header => (
                header.includes('MARCA')
                || header.includes('CÓDIGO')
                || header.includes('CODIGO')
                || header === 'X3'
            ));
            const idxCant = headers.findIndex(header => (
                header.includes('CANT')
                || header === 'CANT T.'
            ));
            const idxDesc = headers.findIndex(header => header.includes('DESCRIP'));
            const idxLong = headers.findIndex(header => header.includes('LONGITUD'));

            if (idxMarca === -1 || idxCant === -1) {
                mostrarAlerta(
                    "El Excel debe incluir las columnas Marca/Código y Cantidad.",
                    "error"
                );
                return;
            }

            const componentes = [];
            let currentTipo = 'fab';

            for (let index = headerRowIdx + 1; index < json.length; index++) {
                const row = json[index];
                if (!row || row.length === 0) continue;

                const rowText = row.join(" ").toUpperCase();
                if (
                    rowText.includes('PERNERIA TEMPLATE')
                    || rowText.includes('PERNERÍA TEMPLATE')
                ) {
                    currentTipo = 'p_template';
                    continue;
                }
                if (
                    rowText.includes('PERNERIA TORRE')
                    || rowText.includes('PERNERÍA TORRE')
                ) {
                    currentTipo = 'p_torre';
                    continue;
                }
                if (rowText.includes('SISTEMA DE VIENTOS')) {
                    currentTipo = 'vientos';
                    continue;
                }
                if (rowText.includes('CABLE DE VIDA')) {
                    currentTipo = 'c_vida';
                    continue;
                }

                const rawMarca = row[idxMarca];
                const rawCantidad = row[idxCant];
                if (
                    typeof rawMarca === 'string'
                    && rawMarca.toUpperCase() === 'X3'
                ) continue;
                if (
                    typeof rawCantidad === 'string'
                    && rawCantidad.toUpperCase().includes('CANT')
                ) continue;

                const marca = String(rawMarca || '').trim();
                const cantidad = Number.parseFloat(rawCantidad);
                if (!marca || !Number.isFinite(cantidad) || cantidad <= 0) continue;

                const descripcion = (
                    idxDesc !== -1 && row[idxDesc]
                        ? String(row[idxDesc]).toUpperCase().trim()
                        : ''
                );
                const rawLongitud = idxLong !== -1
                    ? Number.parseFloat(row[idxLong])
                    : Number.NaN;

                componentes.push({
                    marca,
                    cantidad,
                    descripcion,
                    longitud: Number.isFinite(rawLongitud)
                        ? rawLongitud.toFixed(1)
                        : '0.0',
                    tipo: currentTipo,
                    estado_suministro: 'No requerido',
                    operario: ''
                });
            }

            if (componentes.length === 0) {
                mostrarAlerta(
                    "El Excel no contiene elementos válidos para importar.",
                    "error"
                );
                return;
            }

            renderizarTabla(componentes, false);
            setPendingImport(true);
            mostrarAlerta(
                `Excel cargado: ${componentes.length} elementos pendientes de guardar.`,
                "info"
            );
        } catch (error) {
            console.error("Error leyendo Excel:", error);
            mostrarAlerta("Error de formato en archivo Excel.", "error");
        }
    };

    reader.onerror = () => {
        mostrarAlerta("No se pudo leer el archivo Excel.", "error");
    };
    reader.readAsArrayBuffer(file);
    event.target.value = '';
}

async function actualizarCampoSimple(inputElement, campoName) {
    if (!canEdit) return false;
    const row = inputElement.closest('tr');
    if (!row || !row.dataset.id) return false;

    return guardarCampoComponente(
        row.dataset.id,
        campoName,
        inputElement.value
    );
}

function actualizarEstadoUI(selectElement) {
    const val = selectElement.value;
    let bg = '';
    if (val === 'No requerido') bg = 'text-slate-500 border-slate-300 bg-white';
    else if (val === 'En compra') bg = 'text-blue-600 border-blue-400 bg-white';
    else if (val === 'Comprado') bg = 'text-teal-600 border-teal-400 bg-white';
    else if (val === 'En almacén') bg = 'text-indigo-600 border-indigo-400 bg-white';
    else if (val === 'Despachado') bg = 'text-emerald-700 border-emerald-400 bg-white';

    selectElement.className = `text-[12px] font-bold outline-none rounded-md px-2 py-1 border transition-colors cursor-pointer w-[120px] text-center select-estado-suministro ${bg}`;
}

function actualizarEstadoSuministro(selectElement) {
    if (!canEdit) return;
    actualizarEstadoUI(selectElement);
    actualizarCampoSimple(selectElement, 'estado_suministro');
    recalcularMatriz();
}

function validarYCalcular(input, maxCant, procKey, skipSave = false) {
    if (!canEdit && !skipSave) return;

    const row = input.closest('tr');
    if (!row) return;

    const valueText = input.value.trim();
    if (valueText === '') {
        const percentageCell = row.querySelector(`.pct-${procKey}`);
        if (percentageCell) percentageCell.innerText = '-';
        recalcularMatriz();
        return;
    }

    let value = Number.parseFloat(valueText);
    if (!Number.isFinite(value)) value = 0;
    if (value > maxCant) value = maxCant;

    if (procKey === 'des') {
        if (value < 0) value = 0;
        input.value = value;
        const dateCell = row.querySelector('.pct-des');

        if (dateCell) {
            if (value > 0) {
                const date = new Date().toLocaleDateString('es-PE', {
                    day: '2-digit',
                    month: 'short'
                }).toUpperCase();
                dateCell.innerHTML = `<span class="font-black text-slate-800">${date}</span>`;
                dateCell.className = 'px-1 py-1.5 text-center bg-slate-200 border-l border-slate-300 sticky-r2 pct-des';
            } else {
                dateCell.innerHTML = '-';
                dateCell.className = 'px-1 py-1.5 text-center bg-slate-50 border-l border-slate-200 sticky-r2 pct-des text-slate-400 font-medium';
            }
        }
    } else {
        if (value < -1) value = -1;
        input.value = value;
        const percentageCell = row.querySelector(`.pct-${procKey}`);

        if (value === -1) {
            if (percentageCell) {
                percentageCell.innerText = 'N/A';
                percentageCell.className = `px-1 py-1 text-center w-[45px] font-bold text-slate-400 bg-slate-100 border-r border-slate-200 pct-${procKey} col-${procKey}`;
            }
            input.classList.add('text-slate-300');
            const programmedCell = input.parentElement.previousElementSibling;
            if (programmedCell) programmedCell.innerText = '-';
        } else {
            input.classList.remove('text-slate-300');
            const programmedCell = input.parentElement.previousElementSibling;
            if (programmedCell) programmedCell.innerText = maxCant;

            const localPercentage = maxCant > 0
                ? (value / maxCant) * 100
                : 0;
            if (percentageCell) {
                percentageCell.innerText = localPercentage.toFixed(1) + '%';
                if (localPercentage === 100) {
                    percentageCell.className = `px-1 py-1 text-center w-[45px] font-black text-emerald-600 bg-emerald-50 border-r border-slate-200 pct-${procKey} col-${procKey}`;
                } else if (localPercentage > 0) {
                    percentageCell.className = `px-1 py-1 text-center w-[45px] font-bold text-blue-600 bg-blue-50/50 border-r border-slate-200 pct-${procKey} col-${procKey}`;
                } else {
                    percentageCell.className = `px-1 py-1 text-center w-[45px] font-medium text-slate-400 bg-white border-r border-slate-200 pct-${procKey} col-${procKey}`;
                }
            }
        }
    }

    if (!skipSave && row.dataset.id) {
        programarGuardadoCelda(
            row.dataset.id,
            procKey + '_real',
            value
        );
    }
    recalcularMatriz();
}

async function toggleAlertaFila(button) {
    if (!canEdit) return;
    const row = button.closest('tr');
    if (!row) return;

    const previousState = row.classList.contains('row-alert');
    const nextState = !previousState;
    row.classList.toggle('row-alert', nextState);
    button.innerHTML = nextState
        ? `<span class="material-symbols-rounded text-[18px] text-red-500">warning</span>`
        : `<span class="material-symbols-rounded text-[18px] text-slate-300 hover:text-slate-500 transition-colors">emoji_flags</span>`;

    if (!row.dataset.id) return;
    const saved = await guardarCampoComponente(
        row.dataset.id,
        'alerta',
        nextState
    );
    if (!saved) {
        row.classList.toggle('row-alert', previousState);
        button.innerHTML = previousState
            ? `<span class="material-symbols-rounded text-[18px] text-red-500">warning</span>`
            : `<span class="material-symbols-rounded text-[18px] text-slate-300 hover:text-slate-500 transition-colors">emoji_flags</span>`;
    }
}

function recalcularMatriz() {
    const filas = document.querySelectorAll('#matriz-body tr[data-cant]');
    if(filas.length === 0) return;

    let sumasProcesos = { hab: 0, arm: 0, sol: 0, lim: 0, lib: 0, gal: 0, are: 0, pin: 0 };
    let conteoFilasValidas = { hab: 0, arm: 0, sol: 0, lim: 0, lib: 0, gal: 0, are: 0, pin: 0 };

    let sumaAvancesTotales = 0; let unidadesFab = 0;
    let sumaAvancesABA = 0; let unidadesABA = 0;

    filas.forEach(fila => {
        const tipoRow = fila.dataset.tipo;
        const isSuministro = tipoRow !== 'fab' && tipoRow !== 'fabricacion';
        const cantT = Math.max(parseFloat(fila.dataset.cant) || 0, 0);
        let porcFilaFinal = 0;

        if (isSuministro) {
            const inputDes = fila.querySelector('.proc-des');


            const valDes = inputDes ? (parseFloat(inputDes.value) || 0) : 0;
            porcFilaFinal = cantT > 0 ? (valDes / cantT) * 100 : 0;
            if (porcFilaFinal > 100) porcFilaFinal = 100;


            if (cantT > 0) {
                sumaAvancesABA += porcFilaFinal * cantT;
                unidadesABA += cantT;
            }

        } else {
            let avanceFilaPonderado = 0; let pesoFilaTotal = 0;
            procesosProd.forEach(key => {
                if(key === 'des') return; if(!activeProcs[key]) return;
                const input = fila.querySelector(`.proc-${key}`); if (!input) return;
                const valStr = input.value.trim();
                const valNum = parseFloat(valStr);

                if(!isNaN(valNum) && valNum !== -1) {
                    const porc = valNum / cantT;
                    avanceFilaPonderado += (porc * pesos[key]);
                    pesoFilaTotal += pesos[key];
                    if (cantT > 0) {
                        sumasProcesos[key] += porc * cantT;
                        conteoFilasValidas[key] += cantT;
                    }
                }
            });
            porcFilaFinal = pesoFilaTotal > 0 ? (avanceFilaPonderado / pesoFilaTotal) * 100 : 0;
            if (cantT > 0) {
                sumaAvancesTotales += porcFilaFinal * cantT;
                unidadesFab += cantT;
            }
        }

        const tdTotal = fila.querySelector('.row-total-percentage');
        if (tdTotal) {
            fila.dataset.porcentaje = porcFilaFinal;
            tdTotal.innerText = `${porcFilaFinal.toFixed(1)}%`;
            if (porcFilaFinal === 100) { tdTotal.className = "px-2 py-1 text-center font-black text-emerald-400 bg-slate-900 sticky-r1 shadow-left row-total-percentage align-middle"; }
            else { tdTotal.className = "px-2 py-1 text-center font-black text-white bg-slate-900 sticky-r1 shadow-left row-total-percentage align-middle"; }
        }
    });

    const elGlobal = document.getElementById('global-avance-total');
    if (elGlobal) elGlobal.innerText = `${(unidadesFab > 0 ? (sumaAvancesTotales / unidadesFab) : 0).toFixed(1)}%`;

    const elABA = document.getElementById('global-avance-aba');
    if (elABA) elABA.innerText = `${(unidadesABA > 0 ? (sumaAvancesABA / unidadesABA) : 0).toFixed(1)}%`;

    procesosProd.forEach(p => {
        if(p === 'des') return; const el = document.getElementById(`box-${p}`);
        if (el) { const promedio = conteoFilasValidas[p] > 0 ? (sumasProcesos[p] / conteoFilasValidas[p]) * 100 : 0; el.innerText = `${promedio.toFixed(1)}%`; }
    });
}


function abrirDetalle(btnEl, marca, long, cant, desc, tipo) {
    if (!btnEl) return;
    currentDetalleRow = btnEl.closest('tr');
    if (!currentDetalleRow) return;
    lastDetalleTrigger = btnEl;
    const isSuministro = tipo !== 'fab' && tipo !== 'fabricacion';

    document.getElementById('det-marca').innerText = marca;
    document.getElementById('det-desc').innerText = desc;
    document.getElementById('det-long').innerText = long + ' mm';
    document.getElementById('det-cant').innerText = cant;

    // Obtenemos los operarios
    const hiddenOperario = currentDetalleRow.querySelector('.input-operario');
    let opDict = parseOperarios(hiddenOperario ? hiddenOperario.value : '');

    let porcTotal = parseFloat(currentDetalleRow.dataset.porcentaje) || 0;
    const txtPorc = document.getElementById('det-porcentaje-txt');
    if(txtPorc) txtPorc.innerText = porcTotal.toFixed(1) + '%';
    const barPorc = document.getElementById('det-porcentaje-bar');
    if(barPorc) barPorc.style.width = porcTotal + '%';
    const progressTrack = document.getElementById('det-porcentaje-track');
    if(progressTrack) progressTrack.setAttribute('aria-valuenow', String(Math.max(0, Math.min(100, porcTotal))));

    const badge = document.getElementById('det-estado-badge');
    if(badge) {
        if(porcTotal >= 99.95) { badge.innerText = "COMPLETADO"; badge.className = "production-detail-state is-complete"; }
        else if(porcTotal > 0) { badge.innerText = "EN PROCESO"; badge.className = "production-detail-state is-progress"; }
        else { badge.innerText = "PENDIENTE"; badge.className = "production-detail-state"; }
    }

    const tablaContainer = document.getElementById('det-tabla-procesos');
    const cardsContainer = document.getElementById('det-cards-procesos');
    if(tablaContainer) tablaContainer.innerHTML = '';
    if(cardsContainer) cardsContainer.innerHTML = '';

    const nombresProcObj = {hab: 'Habilitado', arm: 'Armado', sol: 'Soldado', lim: 'Limpieza', lib: 'Liberación', gal: 'Galvanizado', are: 'Arenado', pin: 'Pintado'};

    if (isSuministro) {
        const selectEstado = currentDetalleRow.querySelector('.select-estado-suministro');
        const estActual = selectEstado ? selectEstado.value : 'No requerido';

        const supplyStatusClass = estActual === 'Entregado' || estActual === 'Despachado'
            ? 'is-complete'
            : (estActual !== 'No requerido' ? 'is-progress' : '');

        if(tablaContainer) tablaContainer.innerHTML = `<tr>
            <td>Abastecimiento</td>
            <td><span class="production-detail-process-status ${supplyStatusClass}"><i></i>${escapeHtml(estActual)}</span></td>
            <td>-</td><td>-</td><td>${porcTotal.toFixed(1)}%</td>
        </tr>`;

        if(cardsContainer) cardsContainer.innerHTML = `<div class="production-detail-supply">
            <strong>Estado de abastecimiento</strong>
            <span>${escapeHtml(estActual)}</span>
        </div>`;
    } else {
        procesosProd.forEach(p => {
            if (p === 'des' || !activeProcs[p]) return;
            const input = currentDetalleRow.querySelector(`.proc-${p}`);
            if (input) {
                const val = parseFloat(input.value) || 0;
                const isNA = val === -1;

                let txtEstado = 'Pendiente';
                let statusClass = '';
                if(isNA) { txtEstado = 'No aplica'; }
                else if(val >= cant && cant > 0) { txtEstado = 'Completado'; statusClass = 'is-complete'; }
                else if(val > 0) { txtEstado = 'En proceso'; statusClass = 'is-progress'; }

                const porcentajeLocal = isNA ? 'N/A' : (cant > 0 ? ((val / cant) * 100).toFixed(1) : '0.0') + '%';
                const operatorName = opDict[p] || '';
                const processControls = canEdit ? `
                        <label class="production-detail-apply-toggle">
                            <input type="checkbox" ${!isNA ? 'checked' : ''} onchange="toggleNA('${p}', !this.checked, ${cant})">
                            <span aria-hidden="true"></span>
                            <b>Aplica al elemento</b>
                        </label>
                        ${!isNA ? `
                        <label class="production-detail-operator">
                            <span>Operarios</span>
                            <textarea placeholder="Ej.: Ana, Luis, Carlos" onblur="guardarOpProceso('${p}', this.value)" maxlength="450" autocomplete="off">${escapeHtml(operatorName)}</textarea>
                            <small>Separa varios nombres con coma.</small>
                        </label>
                        ` : `
                        <div class="production-detail-readonly"><span>Asignación</span><strong>Proceso omitido</strong></div>
                        `}`
                    : `<div class="production-detail-readonly"><span>Operario</span>
                        <strong>${isNA ? 'No aplica' : (operatorName ? escapeHtml(operatorName) : 'Sin operarios asignados')}</strong>
                    </div>`;

                if(tablaContainer) tablaContainer.innerHTML += `<tr>
                    <td>${nombresProcObj[p]}</td>
                    <td><span class="production-detail-process-status ${statusClass}"><i></i>${txtEstado}</span></td>
                    <td>${isNA ? '-' : cant}</td>
                    <td>${isNA ? '-' : val}</td>
                    <td>${porcentajeLocal}</td>
                </tr>`;

                if(cardsContainer) cardsContainer.innerHTML += `<article class="production-detail-assignment ${isNA ? 'is-disabled' : ''}">
                    <div class="production-detail-assignment-heading">
                        <strong>${nombresProcObj[p]}</strong>
                        <span>${txtEstado} · ${porcentajeLocal}</span>
                    </div>
                    <div class="production-detail-assignment-controls">
                        ${processControls}
                    </div>
                </article>`;
            }
        });
    }

    const overlay = document.getElementById('detalle-overlay'); const box = document.getElementById('detalle-modal-box');
    if(overlay && box) {
        overlay.classList.remove('hidden');
        overlay.setAttribute('aria-hidden', 'false');
        document.body.classList.add('production-detail-open');
        window.requestAnimationFrame(() => {
            overlay.classList.remove('opacity-0');
            box.classList.remove('scale-95');
            box.focus({ preventScroll: true });
        });
    }
}

function cerrarDetalle() {
    const overlay = document.getElementById('detalle-overlay'); const box = document.getElementById('detalle-modal-box');
    if(overlay && box && !overlay.classList.contains('hidden')) {
        overlay.classList.add('opacity-0'); box.classList.add('scale-95');
        overlay.setAttribute('aria-hidden', 'true');
        document.body.classList.remove('production-detail-open');
        setTimeout(() => {
            overlay.classList.add('hidden');
            currentDetalleRow = null;
            if (lastDetalleTrigger instanceof HTMLElement && document.contains(lastDetalleTrigger)) {
                lastDetalleTrigger.focus({ preventScroll: true });
            }
            lastDetalleTrigger = null;
        }, 190);
    }
}


function toggleNA(proc, isChecked, cant) {
    if (!canEdit) return;
    if(!currentDetalleRow) return;
    const input = currentDetalleRow.querySelector(`.proc-${proc}`);
    if(input) {
        input.value = isChecked ? -1 : 0;
        validarYCalcular(input, cant, proc, false);
        // Recargar Modal
        abrirDetalle(currentDetalleRow.querySelector('.btn-detalle'), document.getElementById('det-marca').innerText, document.getElementById('det-long').innerText.replace(' mm',''), cant, document.getElementById('det-desc').innerText, currentDetalleRow.dataset.tipo);
    }
}

async function guardarOpProceso(proc, nombre) {
    if (!canEdit || !currentDetalleRow) return;
    const hiddenOperator = currentDetalleRow.querySelector('.input-operario');
    if (!hiddenOperator) return;

    const operatorMap = parseOperarios(hiddenOperator.value);
    operatorMap[proc] = normalizeOperatorNames(nombre);
    const previousValue = hiddenOperator.value;
    hiddenOperator.value = stringifyOperarios(operatorMap);

    const saved = await actualizarCampoSimple(hiddenOperator, 'operario');
    if (saved) {
        mostrarAlerta('Operarios actualizados.', 'exito');
    } else {
        hiddenOperator.value = previousValue;
    }
}


function toggleChat() {
    const drawer = document.getElementById('chat-drawer');
    const overlay = document.getElementById('chat-overlay');
    if (!drawer || !overlay) return;

    const opening = drawer.classList.contains('translate-x-full');
    if (opening) {
        drawer.classList.remove('translate-x-full');
        overlay.classList.add('overlay-open');
        cargarMensajes();
        const chatInput = document.getElementById('chat-input');
        if (chatInput) chatInput.focus();
    } else {
        drawer.classList.add('translate-x-full');
        overlay.classList.remove('overlay-open');
    }
}

async function cargarMensajes() {
    if (messagesRequestInFlight) return;
    messagesRequestInFlight = true;

    try {
        const res = await fetch(`/api/mensajes/${otId}`, {
            headers: { 'Accept': 'application/json' }
        });
        const data = await readJsonResponse(res);
        if (!res.ok) {
            throw new Error(responseError(data, "No se pudieron cargar los mensajes."));
        }
        if (!Array.isArray(data)) {
            throw new Error("La respuesta de mensajes no es válida.");
        }

        const history = document.getElementById('chat-history');
        if (history) {
            history.innerHTML = `<div class="flex flex-col items-center my-3"><span class="bg-slate-200 text-slate-600 text-[10px] font-bold px-3 py-1 rounded-full shadow-sm">Inicio de Mensajería - OT ${escapeHtml(window.ProduccionConfig.otOt)}</span></div>`;
            data.forEach(message => agregarMensajeAlDOM(message));
        }
        lastMessageSyncAt = Date.now();
    } catch (error) {
        console.error("Error cargando mensajes:", error);
        if (isChatOpen()) {
            mostrarAlerta(error.message || "No se pudieron cargar los mensajes.", "error");
        }
    } finally {
        messagesRequestInFlight = false;
    }
}

async function enviarMensaje() {
    if (!canEdit) return;
    const input = document.getElementById('chat-input');
    const message = input?.value.trim();
    if (!input || !message) return;

    input.disabled = true;
    try {
        const res = await fetch('/api/mensajes/enviar', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify({
                ot_id: otId,
                mensaje: message,
                tipo: 'manual'
            })
        });
        const data = await readJsonResponse(res);
        if (!res.ok || !data.success) {
            throw new Error(responseError(data, "No se pudo enviar el mensaje."));
        }

        agregarMensajeAlDOM(data.mensaje);
        input.value = '';
        input.style.height = 'auto';
        lastMessageSyncAt = Date.now();
    } catch (error) {
        mostrarAlerta(error.message || "No se pudo enviar el mensaje.", "error");
    } finally {
        input.disabled = false;
        input.focus();
    }
}

function agregarMensajeAlDOM(msg) {
    const history = document.getElementById('chat-history'); const esMio = (msg.usuario_id && msg.usuario_id.toString() === currentUserId.toString());
    const alignClass = esMio ? 'items-end' : 'items-start'; const bgClass = esMio ? 'bg-blue-600 text-white rounded-tr-none' : 'bg-white border border-slate-200 text-slate-700 rounded-tl-none'; const nameText = esMio ? 'Tú' : (msg.usuario_nombre || 'Usuario');
    const fechaMostrar = msg.fecha && !msg.fecha.includes('Invalid') ? msg.fecha : 'Recién';
    if (!history) return;

    const wrapper = document.createElement('div');
    wrapper.className = `flex flex-col ${alignClass} w-full animate-fade-in my-1.5`;

    const metadata = document.createElement('span');
    metadata.className = 'text-[9px] text-slate-500 font-bold px-1';
    metadata.append(document.createTextNode(String(nameText)));

    const date = document.createElement('span');
    date.className = 'text-slate-400 font-semibold ml-1';
    date.textContent = `• ${fechaMostrar}`;
    metadata.append(document.createTextNode(' '), date);

    const messageRow = document.createElement('div');
    messageRow.className = `flex items-center ${esMio ? 'justify-end' : 'justify-start'} w-full gap-1 mt-0.5`;

    const bubble = document.createElement('div');
    bubble.className = `${bgClass} rounded-xl px-3 py-2 text-[12px] shadow-sm max-w-[85%] leading-snug break-words`;
    bubble.textContent = String(msg.mensaje ?? '');

    let deleteButton = null;
    if (isAdmin) {
        deleteButton = document.createElement('button');
        deleteButton.type = 'button';
        deleteButton.className = 'text-slate-300 hover:text-red-500 transition-colors px-1';
        deleteButton.title = 'Borrar (Solo Admin)';
        const deleteIcon = document.createElement('span');
        deleteIcon.className = 'material-symbols-rounded text-[14px]';
        deleteIcon.textContent = 'delete';
        deleteButton.appendChild(deleteIcon);
        deleteButton.addEventListener('click', () => eliminarMensaje(msg.id, deleteButton));
    }

    if (esMio && deleteButton) messageRow.appendChild(deleteButton);
    messageRow.appendChild(bubble);
    if (!esMio && deleteButton) messageRow.appendChild(deleteButton);

    wrapper.append(metadata, messageRow);
    history.appendChild(wrapper);
    history.scrollTop = history.scrollHeight;
}

async function eliminarMensaje(msgId, buttonElement) {
    if (!confirm("¿Seguro que deseas borrar este mensaje?")) return;

    try {
        const res = await fetch(`/api/mensajes/eliminar/${msgId}`, {
            method: 'DELETE',
            headers: { 'X-CSRFToken': getCsrfToken() }
        });
        const data = await readJsonResponse(res);
        if (!res.ok || !data.success) {
            throw new Error(responseError(data, "No se pudo eliminar el mensaje."));
        }
        buttonElement.closest('.flex-col')?.remove();
    } catch (error) {
        mostrarAlerta(error.message || "No se pudo eliminar el mensaje.", "error");
    }
}

function actualizarColorFecha() {
    const inputFecha = document.getElementById('fecha-entrega'); const badge = document.getElementById('urgencia-badge'); const textDisplay = document.getElementById('fecha-display-text'); if(!inputFecha || !badge || !textDisplay || !inputFecha.value) return;
    const partesFecha = inputFecha.value.split('-'); const fechaSeleccionada = new Date(partesFecha[0], partesFecha[1] - 1, partesFecha[2]);
    const hoy = new Date(); hoy.setHours(0,0,0,0); const diffDays = Math.ceil((fechaSeleccionada - hoy) / (1000 * 60 * 60 * 24));
    textDisplay.innerText = fechaSeleccionada.toLocaleDateString('es-PE', { day:'2-digit', month:'2-digit', year:'numeric' });
    badge.className = "flex items-center justify-end gap-1.5 px-2 py-1 rounded-md text-[11px] font-black tracking-wide transition-colors border border-transparent";
    if (diffDays > 7) { badge.classList.add('bg-slate-100', 'text-slate-600'); badge.innerHTML = `<span class="material-symbols-rounded text-[14px]">calendar_today</span> Quedan ${diffDays} días`; }
    else if (diffDays <= 7 && diffDays > 3) { badge.classList.add('bg-amber-100', 'text-amber-700'); badge.innerHTML = `<span class="material-symbols-rounded text-[14px]">schedule</span> Quedan ${diffDays} días`; }
    else if (diffDays <= 3 && diffDays > 0) { badge.classList.add('bg-orange-100', 'text-orange-700'); badge.innerHTML = `<span class="relative flex h-2 w-2 mr-1"><span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-orange-400 opacity-75"></span><span class="relative inline-flex rounded-full h-2 w-2 bg-orange-500"></span></span> URGENTE: ${diffDays} DÍAS`; }
    else if (diffDays === 0) { badge.classList.add('bg-red-100', 'text-red-700'); badge.innerHTML = `<span class="relative flex h-2 w-2 mr-1"><span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75"></span><span class="relative inline-flex rounded-full h-2 w-2 bg-red-600"></span></span> VENCE HOY`; }
    else { badge.classList.add('bg-red-600', 'text-white'); badge.innerHTML = `<span class="material-symbols-rounded text-[14px]">warning</span> RETRASO (${Math.abs(diffDays)} d)`; }
}

function aplicarConfiguracionProcesosUI() {
    procesosProd.forEach(procKey => {
        const enabled = activeProcs[procKey] !== false;
        document.querySelectorAll(`.col-${procKey}`).forEach(col => {
            col.style.display = enabled ? '' : 'none';
        });
        const card = document.getElementById(`card-${procKey}`);
        if (card) {
            card.classList.toggle('active', enabled);
            card.classList.toggle('inactive', !enabled);
            const checkbox = card.querySelector('input[type="checkbox"]');
            if (checkbox) checkbox.checked = enabled;
        }
        const weightText = document.getElementById(`peso-text-${procKey}`);
        if (weightText) weightText.innerText = Number(pesos[procKey] || 0);
    });
}

async function guardarConfiguracionProcesos() {
    const save = async () => {
        const response = await fetch(`/api/produccion/ot/${otId}/configuracion-procesos`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken()},
            body: JSON.stringify({
                expected_version: currentOtVersion,
                weights: pesos,
                active_processes: activeProcs
            })
        });
        const data = await readJsonResponse(response);
        if (!response.ok || !data.success) {
            if (Number.isFinite(Number(data.current_version))) {
                currentOtVersion = Number(data.current_version);
            }
            throw new Error(responseError(data, 'No se pudo guardar la configuración.'));
        }
        currentOtVersion = Number(data.version || currentOtVersion);
        pesos = {...pesos, ...(data.weights || {})};
        activeProcs = {...activeProcs, ...(data.active_processes || {})};
        return true;
    };
    processConfigSaveQueue = processConfigSaveQueue.then(save, save);
    try {
        return await processConfigSaveQueue;
    } catch (error) {
        mostrarAlerta(error.message || 'No se pudo guardar la configuración.', 'error');
        return false;
    }
}

async function toggleProcess(procKey) {
    if (!canEdit) return;
    const previous = activeProcs[procKey];
    activeProcs[procKey] = !previous;
    aplicarConfiguracionProcesosUI();
    recalcularMatriz();
    if (await guardarConfiguracionProcesos()) {
        mostrarAlerta('Configuración de procesos guardada.', 'exito');
    } else {
        activeProcs[procKey] = previous;
        aplicarConfiguracionProcesosUI();
        recalcularMatriz();
    }
}

function editarPeso(containerSpan, procId) {
    if (!canEdit) return;
    let spanNumerico = document.getElementById(`peso-text-${procId}`); if(!spanNumerico) return;
    let valorActual = pesos[procId]; let input = document.createElement('input'); input.type = 'number'; input.value = valorActual; input.min = 0; input.max = 100;
    input.className = 'w-8 h-4 text-[9px] font-bold text-center border border-blue-400 rounded outline-none text-blue-700 bg-blue-50/50';
    input.onblur = function() { guardarPeso(this, spanNumerico, procId); }; input.onkeydown = function(e) { if(e.key === 'Enter') this.blur(); };
    spanNumerico.parentNode.replaceChild(input, spanNumerico); input.focus(); input.select();
}

async function guardarPeso(input, originalSpan, procId) {
    const previous = pesos[procId];
    let val = parseFloat(input.value); if (isNaN(val) || val < 0) val = 0; pesos[procId] = Math.min(val, 100); originalSpan.innerText = pesos[procId];
    input.parentNode.replaceChild(originalSpan, input); recalcularMatriz();
    if (await guardarConfiguracionProcesos()) {
        mostrarAlerta(`Peso actualizado a ${pesos[procId]}%`, "exito");
    } else {
        pesos[procId] = previous;
        originalSpan.innerText = previous;
        recalcularMatriz();
    }
}
function filtrarMatriz() {
    const input = document.getElementById('searchMatriz').value.toLowerCase();
    document.querySelectorAll('#matriz-body tr').forEach(fila => {
        if (fila.children.length === 1) {
            fila.style.display = fila.innerText.toLowerCase().includes(input) || input === '' ? '' : 'none';
        } else if (fila.dataset.cant) {
            const marca = fila.cells[1] ? fila.cells[1].innerText.toLowerCase() : '';
            const desc = fila.cells[3] ? fila.cells[3].innerText.toLowerCase() : '';
            const operarioInput = fila.querySelector('.input-operario');
            const operario = operarioInput ? operarioInput.value.toLowerCase() : '';
            fila.style.display = (marca.includes(input) || desc.includes(input) || operario.includes(input)) ? '' : 'none';
        }
    });
}

function toggleFullscreen() {
    const tableModule = document.getElementById('table-module'); const btnIcon = document.getElementById('icon-fullscreen'); const kpiSection = document.getElementById('kpi-section'); const wrapper = document.querySelector('.matrix-wrapper');
    if (!tableModule.classList.contains('table-maximized')) {
        tableModule.classList.add('table-maximized'); kpiSection.style.display = 'none'; document.body.style.overflow = 'hidden'; btnIcon.innerText = 'close_fullscreen';
        if (wrapper) { wrapper.style.removeProperty('height'); wrapper.style.removeProperty('max-height'); }
    }
    else {
        tableModule.classList.remove('table-maximized'); kpiSection.style.display = 'flex'; document.body.style.overflow = ''; btnIcon.innerText = 'fullscreen';
        window.requestAnimationFrame(ajustarAlturaMatriz);
    }
}
