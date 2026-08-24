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
let currentPlSite = "";
let currentPlVersion = null;
let currentPlEtag = null;
let autoSyncInterval = null;
let currentDetalleRow = null;
let lastDetalleTrigger = null;
let personnelCatalog = [];
let personnelCatalogLoaded = false;
let personnelCatalogRequest = null;
let personnelSelectorProcess = null;
let reopenSelectorAfterPersonnel = false;

let hasPendingImport = false;
let tabsRequestInFlight = false;
let componentsRequestInFlight = false;
let messagesRequestInFlight = false;
let importSaveInFlight = false;
let cellSaveInFlight = false;
let lastMessageSyncAt = 0;
let loadedComponentsFingerprint = null;
let pendingSaveConfirmation = null;
let pendingImportMeta = null;
let productionRoutes = [];
let allowConfirmedNavigation = false;

const cellSaveTimers = new Map();
let cellSaveQueue = Promise.resolve();
let processConfigSaveQueue = Promise.resolve();
const AUTO_SYNC_INTERVAL_MS = 30000;
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

function isProductionDialogOpen() {
    return [
        'detalle-overlay',
        'personnel-selector-overlay',
        'personal-master-overlay',
    ].some(id => {
        const element = document.getElementById(id);
        return element && !element.classList.contains('hidden');
    });
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

function optionalProgressNumber(value) {
    if (value === null || value === undefined || value === '' || Number(value) === -1) return null;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
}

function hasUnsavedProductionChanges() {
    return hasPendingImport || importSaveInFlight || hayGuardadosCeldaPendientes();
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
        categoria: String(component.categoria || 'FABRICACION'),
        subcategoria: String(component.subcategoria || ''),
        unidad: String(component.unidad || 'UND'),
        ubicacion: String(component.ubicacion || ''),
        perfil: String(component.perfil || ''),
        material: String(component.material || ''),
        longitud_mm: Number(component.longitud_mm || 0),
        area_unitaria_m2: Number(component.area_unitaria_m2 || 0),
        area_total_m2: Number(component.area_total_m2 || 0),
        peso_unitario_kg: Number(component.peso_unitario_kg || 0),
        peso_total_kg: Number(component.peso_total_kg || 0),
        fila_origen: Number(component.fila_origen || 0),
        ruta_codigo: String(component.ruta_codigo || ''),
        hab: optionalProgressNumber(component.hab ?? component.hab_real),
        arm: optionalProgressNumber(component.arm ?? component.arm_real),
        sol: optionalProgressNumber(component.sol ?? component.sol_real),
        lim: optionalProgressNumber(component.lim ?? component.lim_real),
        lib: optionalProgressNumber(component.lib ?? component.lib_real),
        gal: optionalProgressNumber(component.gal ?? component.gal_real),
        are: optionalProgressNumber(component.are ?? component.are_real),
        pin: optionalProgressNumber(component.pin ?? component.pin_real),
        des: Number(component.des ?? component.des_real ?? 0),
        alerta: Boolean(component.alerta),
        estado_suministro: String(component.estado_suministro || 'No requerido'),
        operario: String(component.operario || '').trim(),
        fecha_inicio_real: String(component.fecha_inicio_real || ''),
        fecha_termino_real: String(component.fecha_termino_real || component.fecha_realizacion || '')
    })));
}

function solicitarConfirmacionProduccion(options) {
    const overlay = document.getElementById('save-confirm-overlay');
    if (!overlay) return Promise.resolve(window.confirm(options.fallback));
    document.getElementById('save-confirm-icon').textContent = options.icon;
    document.getElementById('save-confirm-kicker').textContent = options.kicker;
    document.getElementById('save-confirm-title').textContent = options.title;
    document.getElementById('save-confirm-description').textContent = options.description;
    document.getElementById('save-confirm-summary-label').textContent = options.summaryLabel;
    document.getElementById('save-confirm-count').textContent = String(options.summaryValue);
    document.getElementById('save-confirm-note').textContent = options.note;
    document.getElementById('save-confirm-accept-label').textContent = options.acceptLabel;
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
        configurarSelectorRutaImportacion();
        cargarTabs();
        cargarRutasProduccion();
        iniciarAutoSync();
        configurarDetalleElemento();
        configurarNavegacionSegura();
        configurarMatrizDesplazable();
        const endDateInput = document.getElementById('fecha-termino-input');
        if (endDateInput) endDateInput.dataset.previous = endDateInput.value;
        window.addEventListener('resize', programarAjusteAlturaMatriz);
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) return;
            if (currentPlId && !isProductionDialogOpen() && !hasPendingImport && !hayGuardadosCeldaPendientes()) sincronizarComponentesBD();
            if (isChatOpen()) cargarMensajes();
        });
        window.addEventListener('pagehide', () => {
            if (autoSyncInterval) clearInterval(autoSyncInterval);
            cellSaveTimers.forEach(timerId => clearTimeout(timerId));
            cellSaveTimers.clear();
            if (matrixHeaderObserver) matrixHeaderObserver.disconnect();
            if (matrixScrollFrame) window.cancelAnimationFrame(matrixScrollFrame);
        });
        window.setTimeout(ajustarAlturaMatriz, 250);
    } catch (e) {
        console.error("Error inicializando Producción:", e);
        mostrarAlerta("No fue posible inicializar la pantalla de Producción.", "error");
    }
});


let matrixResizeTimer = null;
let matrixScrollFrame = null;
let matrixHeaderObserver = null;

function programarAjusteAlturaMatriz() {
    window.clearTimeout(matrixResizeTimer);
    matrixResizeTimer = window.setTimeout(ajustarAlturaMatriz, 100);
}

function actualizarGeometriaMatriz(wrapper) {
    if (!wrapper) return;
    const firstHeaderRow = wrapper.querySelector('.sticky-top-1');
    if (firstHeaderRow) {
        const firstRowHeight = Math.max(1, Math.round(firstHeaderRow.getBoundingClientRect().height));
        wrapper.style.setProperty('--matrix-header-first-row', `${firstRowHeight}px`);
    }

    const maxScrollLeft = Math.max(0, wrapper.scrollWidth - wrapper.clientWidth);
    wrapper.classList.toggle('is-scrolled-x', wrapper.scrollLeft > 2);
    wrapper.classList.toggle('is-at-horizontal-end', maxScrollLeft - wrapper.scrollLeft < 2);
}

function configurarMatrizDesplazable() {
    const wrapper = document.querySelector('[data-matrix-scroll]');
    if (!wrapper || wrapper.dataset.scrollConfigured === 'true') return;
    wrapper.dataset.scrollConfigured = 'true';

    const scheduleUpdate = () => {
        if (matrixScrollFrame) return;
        matrixScrollFrame = window.requestAnimationFrame(() => {
            matrixScrollFrame = null;
            actualizarGeometriaMatriz(wrapper);
        });
    };

    wrapper.addEventListener('scroll', scheduleUpdate, { passive: true });
    if ('ResizeObserver' in window) {
        matrixHeaderObserver = new ResizeObserver(scheduleUpdate);
        matrixHeaderObserver.observe(wrapper);
        const firstHeaderRow = wrapper.querySelector('.sticky-top-1');
        if (firstHeaderRow) matrixHeaderObserver.observe(firstHeaderRow);
    }
    scheduleUpdate();
}

function configurarDetalleElemento() {
    const overlay = document.getElementById('detalle-overlay');
    if (!overlay) return;

    const personnelSelector = document.getElementById('personnel-selector-overlay');
    const personnelMaster = document.getElementById('personal-master-overlay');

    overlay.addEventListener('click', (event) => {
        if (event.target === overlay) cerrarDetalle();
    });
    personnelSelector?.addEventListener('click', event => {
        if (event.target === personnelSelector) cerrarSelectorPersonal();
    });
    personnelMaster?.addEventListener('click', event => {
        if (event.target === personnelMaster) cerrarDirectorioPersonal();
    });

    document.addEventListener('keydown', (event) => {
        if (event.key !== 'Escape') return;
        if (personnelSelector && !personnelSelector.classList.contains('hidden')) {
            cerrarSelectorPersonal();
            return;
        }
        if (personnelMaster && !personnelMaster.classList.contains('hidden')) {
            cerrarDirectorioPersonal();
            return;
        }
        if (!overlay.classList.contains('hidden')) cerrarDetalle();
    });
}

function solicitarConfirmacionGuardado(nombre, cantidad) {
    return solicitarConfirmacionProduccion({
        icon: 'save',
        kicker: 'Confirmar guardado',
        title: 'Reemplazar información del lote',
        description: `Se reemplazará la información almacenada de “${nombre}”.`,
        summaryLabel: 'Elementos de la lista',
        summaryValue: cantidad,
        note: 'Si otra persona modificó esta lista, el sistema bloqueará el reemplazo.',
        acceptLabel: 'Guardar cambios',
        fallback: `¿Guardar ${cantidad} elementos en "${nombre}"?`
    });
}

function solicitarConfirmacionDiferenciaOt(expectedCode, detectedCode) {
    return solicitarConfirmacionProduccion({
        icon: 'warning',
        kicker: 'Revisar referencia',
        title: 'El encabezado conserva otra OT',
        description: `El nombre del archivo corresponde a ${expectedCode}, pero el encabezado interno indica ${detectedCode}.`,
        summaryLabel: 'OT de destino',
        summaryValue: expectedCode,
        note: 'Continúa solo si verificaste que los elementos pertenecen a la OT abierta.',
        acceptLabel: 'Importar de todas formas',
        fallback: `El encabezado indica ${detectedCode}, pero el archivo y la pantalla corresponden a ${expectedCode}. ¿Deseas continuar?`
    });
}

function ajustarAlturaMatriz() {
    const wrapper = document.querySelector('.matrix-wrapper');
    const tableModule = document.getElementById('table-module');
    if (!wrapper || !tableModule || tableModule.classList.contains('table-maximized')) return;

    actualizarGeometriaMatriz(wrapper);

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
            currentPlSite = "";
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
                currentPlSite = String(pl.site || '');
                const siteInput = document.getElementById('import-site-input');
                if (siteInput) siteInput.value = currentPlSite;
                const listedVersion = Number(pl.version || 1);
                if (Number(previousId) !== plId) currentPlEtag = null;
                currentPlVersion = Number.isFinite(listedVersion) ? listedVersion : 1;
            }

            const dragAttributes = canEdit
                ? 'draggable="true" ondragstart="handleDragStart(event)" ondragover="handleDragOver(event)" ondragenter="handleDragEnter(event)" ondragleave="handleDragLeave(event)" ondrop="handleDrop(event)" ondragend="handleDragEnd(event)"'
                : 'draggable="false"';

            html += `<button ${dragAttributes} data-id="${plId}" data-version="${Number(pl.version || 1)}" onclick="seleccionarTab(${plId})" class="tab-item ${isActive ? 'is-active' : ''}"><span><strong>${escapeHtml(pl.nombre)}</strong><small>${escapeHtml(pl.site || 'Sin site')}</small></span><i class="material-symbols-rounded">chevron_right</i></button>`;
        });

        if (canEdit) {
            html += `<button onclick="abrirModalPL('modal-nuevo-pl', 'box-nuevo-pl', 'input-nuevo-pl')" class="production-add-pl"><span class="material-symbols-rounded">add</span>Agregar Packing List</button>`;
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
    pendingImportMeta = null;
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
            body: JSON.stringify({
                ot_id: otId,
                nombre
            })
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
        const separatorIndex = pair.indexOf(':');
        if (separatorIndex <= 0) return;
        const processKey = pair.slice(0, separatorIndex).trim();
        const names = pair.slice(separatorIndex + 1).trim();
        if (processKey) op[processKey] = names;
    });
    return op;
}
function stringifyOperarios(op) {
    return Object.entries(op).filter(([k,v]) => v.trim() !== '').map(([k,v]) => `${k}:${v}`).join('|');
}


async function cargarPersonalProduccion({ force = false } = {}) {
    if (personnelCatalogLoaded && !force) return personnelCatalog;
    if (personnelCatalogRequest) return personnelCatalogRequest;

    personnelCatalogRequest = (async () => {
        try {
            const response = await fetch('/api/produccion/personal', {
                headers: { 'Accept': 'application/json' }
            });
            const data = await readJsonResponse(response);
            if (!response.ok || !data.success || !Array.isArray(data.personal)) {
                throw new Error(responseError(data, 'No se pudo cargar el personal registrado.'));
            }
            personnelCatalog = data.personal;
            personnelCatalogLoaded = true;
            renderizarDirectorioPersonal();
            if (personnelSelectorProcess) renderizarOpcionesPersonal();
            return personnelCatalog;
        } catch (error) {
            console.error('Error al cargar personal:', error);
            personnelCatalog = [];
            personnelCatalogLoaded = false;
            renderizarDirectorioPersonal();
            throw error;
        } finally {
            personnelCatalogRequest = null;
        }
    })();

    return personnelCatalogRequest;
}

function renderizarDirectorioPersonal() {
    const container = document.getElementById('personal-master-list');
    const count = document.getElementById('personal-master-count');
    if (count) count.textContent = `${personnelCatalog.length} ${personnelCatalog.length === 1 ? 'persona' : 'personas'}`;
    if (!container) return;
    if (!personnelCatalogLoaded) {
        container.innerHTML = '<div class="production-personnel-directory-empty"><strong>Cargando personal…</strong><span>La lista aparecerá en un momento.</span></div>';
        return;
    }
    if (!personnelCatalog.length) {
        container.innerHTML = '<div class="production-personnel-directory-empty"><strong>Aún no hay personal registrado</strong><span>Agrega al equipo antes de asignarlo a los procesos.</span></div>';
        return;
    }
    container.innerHTML = personnelCatalog.map(person => `
        <article>
            <span aria-hidden="true">${escapeHtml(String(person.nombre || '').trim().charAt(0).toUpperCase() || 'P')}</span>
            <strong>${escapeHtml(person.nombre)}</strong>
        </article>
    `).join('');
}

async function abrirDirectorioPersonal() {
    if (!canEdit) return;
    const overlay = document.getElementById('personal-master-overlay');
    const dialog = document.getElementById('personal-master-dialog');
    if (!overlay || !dialog) return;
    renderizarDirectorioPersonal();
    overlay.classList.remove('hidden');
    overlay.setAttribute('aria-hidden', 'false');
    requestAnimationFrame(() => {
        overlay.classList.remove('opacity-0');
        dialog.classList.remove('scale-95');
        document.getElementById('personal-master-name')?.focus({ preventScroll: true });
    });
    try {
        await cargarPersonalProduccion();
    } catch (error) {
        mostrarAlerta(error.message || 'No se pudo cargar el personal.', 'error');
    }
}

function cerrarDirectorioPersonal() {
    const overlay = document.getElementById('personal-master-overlay');
    const dialog = document.getElementById('personal-master-dialog');
    if (!overlay || !dialog) return;
    overlay.classList.add('opacity-0');
    dialog.classList.add('scale-95');
    overlay.setAttribute('aria-hidden', 'true');
    window.setTimeout(() => {
        overlay.classList.add('hidden');
        if (reopenSelectorAfterPersonnel && personnelSelectorProcess) {
            reopenSelectorAfterPersonnel = false;
            abrirSelectorPersonal(personnelSelectorProcess);
        }
    }, 180);
}

async function registrarPersonal(event) {
    event.preventDefault();
    if (!canEdit) return;
    const input = document.getElementById('personal-master-name');
    const name = input?.value.trim() || '';
    if (!name) {
        input?.focus();
        return;
    }
    try {
        const response = await fetch('/api/produccion/personal', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify({ nombre: name })
        });
        const data = await readJsonResponse(response);
        if (!response.ok || !data.success) {
            throw new Error(responseError(data, 'No se pudo registrar a la persona.'));
        }
        if (input) input.value = '';
        const person = data.person;
        if (person?.id) {
            const existingIndex = personnelCatalog.findIndex(item => Number(item.id) === Number(person.id));
            if (existingIndex === -1) personnelCatalog.push(person);
            else personnelCatalog[existingIndex] = person;
            personnelCatalog.sort((left, right) => String(left.nombre).localeCompare(String(right.nombre), 'es', { sensitivity: 'base' }));
            personnelCatalogLoaded = true;
            renderizarDirectorioPersonal();
        }
        mostrarAlerta(data.created ? 'Persona registrada.' : 'Esa persona ya estaba registrada.', data.created ? 'exito' : 'info');
        input?.focus();
    } catch (error) {
        mostrarAlerta(error.message || 'No se pudo registrar a la persona.', 'error');
    }
}

async function abrirSelectorPersonal(processKey) {
    if (!canEdit || !currentDetalleRow) return;
    personnelSelectorProcess = processKey;
    const processNames = {hab:'Habilitado',arm:'Armado',sol:'Soldado',lim:'Limpieza',lib:'Liberación',gal:'Galvanizado',are:'Arenado',pin:'Pintado'};
    const overlay = document.getElementById('personnel-selector-overlay');
    const dialog = document.getElementById('personnel-selector-dialog');
    const context = document.getElementById('personnel-selector-context');
    const search = document.getElementById('personnel-selector-search');
    if (!overlay || !dialog) return;
    if (context) context.textContent = `${processNames[processKey] || processKey} · ${document.getElementById('det-marca')?.textContent || ''}`;
    if (search) search.value = '';
    renderizarOpcionesPersonal();
    overlay.classList.remove('hidden');
    overlay.setAttribute('aria-hidden', 'false');
    requestAnimationFrame(() => {
        overlay.classList.remove('opacity-0');
        dialog.classList.remove('scale-95');
        search?.focus({ preventScroll: true });
    });
    if (!personnelCatalogLoaded) {
        try {
            await cargarPersonalProduccion();
        } catch (error) {
            mostrarAlerta(error.message || 'No se pudo cargar el personal.', 'error');
        }
    }
}

function cerrarSelectorPersonal() {
    const overlay = document.getElementById('personnel-selector-overlay');
    const dialog = document.getElementById('personnel-selector-dialog');
    if (!overlay || !dialog) return;
    overlay.classList.add('opacity-0');
    dialog.classList.add('scale-95');
    overlay.setAttribute('aria-hidden', 'true');
    window.setTimeout(() => overlay.classList.add('hidden'), 180);
}

function renderizarOpcionesPersonal() {
    const container = document.getElementById('personnel-selector-options');
    const empty = document.getElementById('personnel-selector-empty');
    if (!container || !empty || !currentDetalleRow || !personnelSelectorProcess) return;
    const hidden = currentDetalleRow.querySelector('.input-operario');
    if (!personnelCatalogLoaded) {
        empty.hidden = true;
        container.hidden = false;
        container.innerHTML = '<div class="production-personnel-directory-empty"><strong>Cargando personal…</strong></div>';
        return;
    }
    const assignments = parseOperarios(hidden?.value || '');
    const selectedKeys = new Set(
        normalizeOperatorNames(assignments[personnelSelectorProcess] || '')
            .split(',')
            .map(name => name.trim().toLocaleLowerCase())
            .filter(Boolean)
    );
    empty.hidden = personnelCatalog.length > 0;
    container.hidden = personnelCatalog.length === 0;
    container.innerHTML = personnelCatalog.map(person => {
        const checked = selectedKeys.has(String(person.nombre || '').toLocaleLowerCase());
        return `<label data-personnel-option data-search="${escapeHtml(String(person.nombre || '').toLocaleLowerCase())}">
            <input type="checkbox" value="${escapeHtml(person.nombre)}" ${checked ? 'checked' : ''}>
            <span aria-hidden="true"></span><strong>${escapeHtml(person.nombre)}</strong>
        </label>`;
    }).join('');
}

function filtrarSelectorPersonal() {
    const search = document.getElementById('personnel-selector-search')?.value.trim().toLocaleLowerCase() || '';
    document.querySelectorAll('[data-personnel-option]').forEach(option => {
        option.hidden = search && !String(option.dataset.search || '').includes(search);
    });
}

function abrirDirectorioDesdeSelector() {
    reopenSelectorAfterPersonnel = true;
    cerrarSelectorPersonal();
    window.setTimeout(abrirDirectorioPersonal, 190);
}

async function guardarSeleccionPersonal() {
    if (!personnelSelectorProcess) return;
    const names = Array.from(document.querySelectorAll('#personnel-selector-options input:checked'))
        .map(input => input.value);
    const saved = await guardarOpProceso(personnelSelectorProcess, names.join(', '));
    if (saved) cerrarSelectorPersonal();
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

        if (currentPlId && !isProductionDialogOpen() && !hasPendingImport && !hayGuardadosCeldaPendientes()) {
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

        let matrixChanged = false;
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
                    const rawRemoteValue = bdComp[`${proc}_real`];
                    const remoteValue = rawRemoteValue === null || rawRemoteValue === undefined
                        ? ''
                        : String(rawRemoteValue);
                    if (
                        input
                        && document.activeElement !== input
                        && input.value !== remoteValue
                    ) {
                        input.value = remoteValue;
                        validarYCalcular(input, cant, proc, true, true);
                        matrixChanged = true;
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
                validarYCalcular(inputDespacho, cant, 'des', true, true);
                matrixChanged = true;
            }

            tr.dataset.fechaInicioReal = String(bdComp.fecha_inicio_real || '');
            tr.dataset.fechaTerminoReal = String(
                bdComp.fecha_termino_real || bdComp.fecha_realizacion || ''
            );

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
        if (matrixChanged) recalcularMatriz();
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
            keepalive: true,
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
        const row = document.querySelector(`#matriz-body tr[data-id="${CSS.escape(String(componentId))}"]`);
        Object.entries(data.adjusted_fields || {}).forEach(([fieldName, adjustedValue]) => {
            const processKey = fieldName.replace(/_real$/, '');
            const adjustedInput = row?.querySelector(`.proc-${processKey}`);
            if (!adjustedInput) return;
            adjustedInput.value = String(adjustedValue);
            adjustedInput.dataset.lastValidValue = String(adjustedValue);
            paintProcessCell(row, processKey, Number(adjustedValue), Number(row.dataset.cant || 0));
        });
        return true;
    } catch (error) {
        mostrarAlerta(error.message || "No se pudo guardar el cambio.", "error");
        window.setTimeout(() => sincronizarComponentesBD(), 500);
        return false;
    } finally {
        cellSaveInFlight = false;
    }
}

function encolarGuardadoComponente(componentId, campo, valor) {
    const pendingSave = cellSaveQueue.then(
        () => guardarCampoComponente(componentId, campo, valor),
    );
    cellSaveQueue = pendingSave.catch(() => false);
    return pendingSave;
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
        encolarGuardadoComponente(componentId, campo, valor);
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
        const categoriaRow = fila.dataset.categoria || (
            tipoRow === 'fab' || tipoRow === 'fabricacion'
                ? 'FABRICACION'
                : 'SUMINISTRO'
        );
        const isSuministro = categoriaRow !== 'FABRICACION';
        const values = {};

        if (!isSuministro) {
            procesosProd.forEach(process => {
                if (process === 'des') return;
                const input = fila.querySelector(`.proc-${process}`);
                values[process] = input
                    ? optionalProgressNumber(input.value)
                    : null;
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
            categoria: categoriaRow,
            subcategoria: fila.dataset.subcategoria || null,
            unidad: fila.dataset.unidad || 'UND',
            ubicacion: fila.dataset.ubicacion || '',
            perfil: fila.dataset.perfil || '',
            material: fila.dataset.material || '',
            longitud_mm: fila.dataset.longitudMm || null,
            area_unitaria_m2: fila.dataset.areaUnitariaM2 || null,
            area_total_m2: fila.dataset.areaTotalM2 || null,
            peso_unitario_kg: fila.dataset.pesoUnitarioKg || null,
            peso_total_kg: fila.dataset.pesoTotalKg || null,
            fila_origen: fila.dataset.filaOrigen || null,
            ruta_codigo: fila.dataset.rutaCodigo || null,
            hab: values.hab ?? null,
            arm: values.arm ?? null,
            sol: values.sol ?? null,
            lim: values.lim ?? null,
            lib: values.lib ?? null,
            gal: values.gal ?? null,
            are: values.are ?? null,
            pin: values.pin ?? null,
            des: values.des || 0,
            alerta: fila.classList.contains('row-alert'),
            tipo: tipoRow,
            estado_suministro: selectEstado
                ? selectEstado.value
                : 'No requerido',
            operario: inputOperario
                ? inputOperario.value.trim()
                : '',
            fecha_realizacion: fila.dataset.fechaTerminoReal || null,
            fecha_inicio_real: fila.dataset.fechaInicioReal || null,
            fecha_termino_real: fila.dataset.fechaTerminoReal || null
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
        const importMetadata = pendingImportMeta
            ? {
                ...pendingImportMeta,
                site: document.getElementById('import-site-input')?.value.trim() || '',
                ruta_codigo: document.getElementById('import-route-select')?.value || ''
            }
            : { schema_version: 1 };
        const res = await fetch('/api/produccion/importar', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify({
                pl_id: currentPlId,
                expected_version: Number(currentPlVersion),
                componentes,
                import_meta: importMetadata
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
        pendingImportMeta = null;
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
        actualizarResumenElementos([]);
        recalcularMatriz();
        window.requestAnimationFrame(ajustarAlturaMatriz);
        return;
    }

    const tableFragment = document.createDocumentFragment();

    const ordenGrupos = ['MATERIALES DE FABRICACIÓN', 'PERNERÍA TEMPLATE', 'PERNERÍA TORRE', 'CABLE DE VIDA', 'SISTEMA DE VIENTOS', 'OTROS SUMINISTROS'];
    const grupos = {}; ordenGrupos.forEach(g => grupos[g] = []);

    componentes.forEach(comp => {
        let catNombre = nombresTipos[comp.tipo] || 'MATERIALES DE FABRICACIÓN';
        if (!grupos[catNombre]) grupos[catNombre] = [];
        grupos[catNombre].push(comp);
    });

    let totalCols = 11;
    procesosProd.forEach(p => { if (p !== 'des' && activeProcs[p]) totalCols += 3; });

    ordenGrupos.forEach(categoria => {
        const items = grupos[categoria];
        if (!items || items.length === 0) return;


        const trHeader = document.createElement('tr');
        const isFabricationGroup = categoria === 'MATERIALES DE FABRICACIÓN';
        trHeader.className = `production-group-row ${isFabricationGroup ? 'is-fabrication' : 'is-supply'}`;
        trHeader.innerHTML = `<td colspan="${totalCols}" class="sticky left-0 z-10 border-y border-slate-200 px-4 py-3">
            <div class="flex items-center gap-2">
                <span class="production-group-scope">${isFabricationGroup ? 'Producción' : 'Abastecimiento'}</span>
                <span class="text-slate-700 font-black text-[11px] uppercase tracking-widest">${escapeHtml(categoria)}</span>
                <span class="text-slate-500 font-bold ml-1 text-[10px] bg-white border border-slate-200 px-1.5 py-0.5 rounded shadow-sm">${items.length} regs</span>
            </div>
        </td>`;
        tableFragment.appendChild(trHeader);

        items.forEach(comp => {
            const marca = comp.marca || 'S/M';
            const cant = parseFloat(comp.cantidad) || 0;
            const desc = comp.descripcion || '';
            const long = comp.longitud || '0.0';
            const dbId = isFromDB ? comp.id : null;
            const tipo = comp.tipo || 'fab';
            const categoria = comp.categoria || (
                tipo === 'fab' || tipo === 'fabricacion'
                    ? 'FABRICACION'
                    : (tipo === 'p_template' || tipo === 'p_torre' || tipo === 'perneria'
                        ? 'PERNERIA'
                        : 'SUMINISTRO')
            );
            const isSuministro = categoria !== 'FABRICACION';
            const operario = comp.operario || '';
            const fechaInicioReal = comp.fecha_inicio_real || '';
            const fechaTerminoReal = comp.fecha_termino_real || comp.fecha_realizacion || '';
            const estadoSuministro = comp.estado_suministro || 'No requerido';

            const safeMarca = escapeHtml(marca);
            const safeDescription = escapeHtml(desc);
            const safeLength = escapeHtml(long);
            const safeOperator = escapeHtml(operario);
            const weightUnit = Number(comp.peso_unitario_kg || 0);
            const weightTotal = Number(comp.peso_total_kg || 0);
            const safeWeightUnit = formatearPesoKg(weightUnit, false);
            const safeWeightTotal = formatearPesoKg(weightTotal, false);

            const v = {
                hab: optionalProgressNumber(comp.hab ?? comp.hab_real),
                arm: optionalProgressNumber(comp.arm ?? comp.arm_real),
                sol: optionalProgressNumber(comp.sol ?? comp.sol_real),
                lim: optionalProgressNumber(comp.lim ?? comp.lim_real),
                lib: optionalProgressNumber(comp.lib ?? comp.lib_real),
                gal: optionalProgressNumber(comp.gal ?? comp.gal_real),
                are: optionalProgressNumber(comp.are ?? comp.are_real),
                pin: optionalProgressNumber(comp.pin ?? comp.pin_real),
                des: optionalProgressNumber(comp.des ?? comp.des_real) ?? 0
            };
            const alerta = isFromDB ? comp.alerta : false; const alertClass = alerta ? 'row-alert' : ''; const alertIcon = alerta ? '<span class="material-symbols-rounded text-[18px] text-red-500">warning</span>' : '<span class="material-symbols-rounded text-[18px] text-slate-300 hover:text-slate-500 transition-colors">emoji_flags</span>';
            const alertControl = canEdit
                ? `<button onclick="toggleAlertaFila(this)" class="w-6 h-6 rounded flex items-center justify-center transition mx-auto" title="Reportar incidencia">${alertIcon}</button>`
                : `<span class="flex h-6 w-6 items-center justify-center mx-auto" title="${alerta ? 'Elemento con incidencia' : 'Sin incidencia'}">${alertIcon}</span>`;

            const tr = document.createElement('tr');
            tr.className = `hover:bg-slate-50 bg-white transition-colors group border-b border-slate-100 ${alertClass}`;
            tr.dataset.cant = cant; tr.dataset.tipo = tipo;
            tr.dataset.categoria = categoria;
            tr.dataset.subcategoria = comp.subcategoria || '';
            tr.dataset.unidad = comp.unidad || 'UND';
            tr.dataset.ubicacion = comp.ubicacion || '';
            tr.dataset.perfil = comp.perfil || '';
            tr.dataset.material = comp.material || '';
            tr.dataset.longitudMm = comp.longitud_mm ?? '';
            tr.dataset.areaUnitariaM2 = comp.area_unitaria_m2 ?? '';
            tr.dataset.areaTotalM2 = comp.area_total_m2 ?? '';
            tr.dataset.pesoUnitarioKg = comp.peso_unitario_kg ?? '';
            tr.dataset.pesoTotalKg = comp.peso_total_kg ?? '';
            tr.dataset.filaOrigen = comp.fila_origen ?? '';
            tr.dataset.rutaCodigo = comp.ruta_codigo || '';
            tr.dataset.fechaInicioReal = fechaInicioReal;
            tr.dataset.fechaTerminoReal = fechaTerminoReal;
            if (dbId) tr.dataset.id = dbId;

            let html = `<td class="px-1 py-1.5 border-r border-slate-100 sticky-c-alert bg-white text-center align-middle group-hover:bg-slate-50 transition-colors">${alertControl}</td>
                <td class="px-2 py-1.5 font-black text-slate-800 text-center border-r border-slate-100 sticky-c1 bg-white align-middle group-hover:bg-slate-50 transition-colors">${safeMarca}</td>
                <td class="px-1 py-1.5 text-center font-black text-blue-700 border-r border-slate-100 sticky-c2 bg-white align-middle group-hover:bg-slate-50 transition-colors">${cant}</td>
                <td class="px-3 py-1.5 text-left truncate text-[11px] border-r border-slate-100 sticky-c3 bg-white align-middle group-hover:bg-slate-50 transition-colors" title="${safeDescription}">${safeDescription}</td>
                <td class="px-1 py-1.5 text-center text-slate-500 border-r border-slate-100 text-[11px] sticky-c4 bg-white align-middle group-hover:bg-slate-50 transition-colors">${safeLength}</td>
                <td class="production-weight-cell is-unit" title="Peso unitario">${safeWeightUnit}</td>
                <td class="production-weight-cell is-total" title="Peso total planificado">${safeWeightTotal}</td>
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
                    const value = v[proc];
                    const valueAttribute = value === null ? '' : value;
                    const percentage = value === null || cant <= 0
                        ? '—'
                        : `${((value / cant) * 100).toFixed(1)}%`;

                    html += `<td class="px-1 py-1.5 text-center border-r border-slate-100 font-bold text-slate-500 col-${proc} align-middle" style="${isHidden}">${cant}</td>
                        <td class="production-process-real-cell px-1 py-1.5 border-r border-slate-100 col-${proc} align-middle" style="${isHidden}"><input type="number" value="${valueAttribute}" placeholder="—" min="0" max="${cant}" step="1" data-last-valid-value="${valueAttribute}" ${canEdit ? `onchange="validarYCalcular(this, ${cant}, '${proc}')"` : 'disabled aria-readonly="true"'} class="cell-input proc-${proc} ${canEdit ? '' : 'cursor-default bg-slate-50'}" aria-label="Avance ${proc} de ${safeMarca}"></td>
                        <td class="px-1 py-1.5 text-center font-medium text-slate-400 bg-white border-r border-slate-200 pct-${proc} col-${proc} align-middle group-hover:bg-slate-50 transition-colors" style="${isHidden}">${percentage}</td>`;
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
            tableFragment.appendChild(tr); piezas++;

            if(!isSuministro) {
                procesosProd.forEach(proc => { if(proc !== 'des') { const inp = tr.querySelector(`.proc-${proc}`); if (inp && inp.value !== '') validarYCalcular(inp, cant, proc, true, true); }});
            }
            const inpDes = tr.querySelector('.proc-des');
            if(inpDes && inpDes.value > 0) validarYCalcular(inpDes, cant, 'des', true, true);
        });
    });

    tbody.appendChild(tableFragment);

    const lbl = document.getElementById('contador-piezas');
    if(lbl) lbl.innerText = `${piezas} Regs`;
    actualizarResumenElementos(componentes);
    recalcularMatriz();
    window.requestAnimationFrame(ajustarAlturaMatriz);
}

async function cargarRutasProduccion() {
    const routeInput = document.getElementById('import-route-select');
    if (!routeInput || !canEdit) return;
    try {
        const response = await fetch('/api/produccion/rutas', {
            headers: { 'Accept': 'application/json' }
        });
        const payload = await readJsonResponse(response);
        if (!response.ok || !payload.success) {
            throw new Error(responseError(payload, 'No se cargaron las rutas.'));
        }
        productionRoutes = Array.isArray(payload.rutas) ? payload.rutas : [];
        const previous = routeInput.value;
        renderizarOpcionesRutaImportacion();
        seleccionarRutaImportacion(
            productionRoutes.some(route => route.codigo === previous)
                ? previous
                : '',
            { closeMenu: false }
        );
    } catch (error) {
        console.error('No se pudieron cargar las rutas V2:', error);
        mostrarAlerta('No se pudieron preparar las rutas de fabricación.', 'error');
    }
}

function cerrarMenuRutaImportacion() {
    const menu = document.getElementById('import-route-menu');
    const trigger = document.getElementById('import-route-trigger');
    if (menu) menu.hidden = true;
    if (trigger) trigger.setAttribute('aria-expanded', 'false');
}

function toggleImportRouteMenu(event) {
    event?.preventDefault();
    event?.stopPropagation();
    const menu = document.getElementById('import-route-menu');
    const trigger = document.getElementById('import-route-trigger');
    if (!menu || !trigger) return;
    const willOpen = menu.hidden;
    menu.hidden = !willOpen;
    trigger.setAttribute('aria-expanded', String(willOpen));
}

function seleccionarRutaImportacion(routeCode, options = {}) {
    const routeInput = document.getElementById('import-route-select');
    const label = document.getElementById('import-route-label');
    const trigger = document.getElementById('import-route-trigger');
    const selectedRoute = productionRoutes.find(route => route.codigo === routeCode);
    if (routeInput) routeInput.value = selectedRoute?.codigo || '';
    if (label) label.textContent = selectedRoute?.nombre || 'Ruta de fabricación';
    if (trigger) {
        const processNames = (selectedRoute?.procesos || [])
            .map(step => step.proceso?.nombre)
            .filter(Boolean)
            .join(' → ');
        trigger.title = processNames || 'Seleccionar ruta de fabricación';
    }
    document.querySelectorAll('#import-route-menu [data-route-code]').forEach(option => {
        const isSelected = option.dataset.routeCode === (selectedRoute?.codigo || '');
        option.classList.toggle('is-selected', isSelected);
        option.setAttribute('aria-selected', String(isSelected));
    });
    if (options.closeMenu !== false) cerrarMenuRutaImportacion();
}

function renderizarOpcionesRutaImportacion() {
    const menu = document.getElementById('import-route-menu');
    if (!menu) return;
    menu.replaceChildren();

    const createOption = (routeCode, title, description = '') => {
        const option = document.createElement('button');
        option.type = 'button';
        option.dataset.routeCode = routeCode;
        option.setAttribute('role', 'option');
        const strong = document.createElement('strong');
        strong.textContent = title;
        option.appendChild(strong);
        if (description) {
            const small = document.createElement('small');
            small.textContent = description;
            option.appendChild(small);
        }
        option.addEventListener('click', event => {
            event.preventDefault();
            event.stopPropagation();
            seleccionarRutaImportacion(routeCode);
        });
        menu.appendChild(option);
    };

    createOption('', 'Seleccionar ruta', 'Define el flujo para los elementos de fabricación.');
    productionRoutes.forEach(route => {
        const processNames = (route.procesos || [])
            .map(step => step.proceso?.nombre)
            .filter(Boolean)
            .join(' → ');
        createOption(route.codigo, route.nombre, processNames);
    });
}

function configurarSelectorRutaImportacion() {
    document.addEventListener('click', event => {
        if (!event.target.closest('#production-route-picker')) cerrarMenuRutaImportacion();
    });
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape') cerrarMenuRutaImportacion();
    });
}

function normalizarEtiquetaExcel(value) {
    return String(value ?? '')
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .trim()
        .toUpperCase()
        .replace(/\s+/g, ' ');
}

function numeroExcel(value) {
    if (typeof value === 'number') return Number.isFinite(value) ? value : null;
    let text = String(value ?? '').trim().replace(/\s/g, '');
    if (!text) return null;
    text = text.replace(/[^0-9,.-]/g, '');
    if (!text || text === '-' || text === '.' || text === ',') return null;
    const comma = text.lastIndexOf(',');
    const dot = text.lastIndexOf('.');
    if (comma !== -1 && dot !== -1) {
        const decimalSeparator = comma > dot ? ',' : '.';
        const thousandsSeparator = decimalSeparator === ',' ? /\./g : /,/g;
        text = text.replace(thousandsSeparator, '');
        if (decimalSeparator === ',') text = text.replace(',', '.');
    } else if (comma !== -1) {
        text = text.replace(',', '.');
    }
    const parsed = Number.parseFloat(text);
    return Number.isFinite(parsed) ? parsed : null;
}

function formatearPesoKg(value, includeUnit = true) {
    const weight = Number(value);
    if (!Number.isFinite(weight) || weight <= 0) {
        return includeUnit ? '0.0 kg' : '—';
    }
    const formatted = weight.toLocaleString('es-PE', {
        minimumFractionDigits: 1,
        maximumFractionDigits: 1
    });
    return includeUnit ? `${formatted} kg` : formatted;
}

function actualizarResumenElementos(componentes) {
    const rows = Array.isArray(componentes) ? componentes : [];
    const fabrication = rows.filter(component => (
        String(component.categoria || 'FABRICACION').toUpperCase() === 'FABRICACION'
    ));
    const supply = rows.filter(component => (
        String(component.categoria || 'FABRICACION').toUpperCase() !== 'FABRICACION'
    ));
    const plannedWeight = fabrication.reduce(
        (sum, component) => sum + (Number(component.peso_total_kg) || 0),
        0
    );
    const activeRoute = fabrication.find(component => component.ruta_codigo)?.ruta_codigo || '';

    const weightElement = document.getElementById('global-peso-fabricacion');
    const summaryWeightElement = document.getElementById('production-summary-weight');
    const siteElement = document.getElementById('production-active-site');
    const routeElement = document.getElementById('production-active-route');
    const fabricationElement = document.getElementById('contador-fabricacion');
    const supplyElement = document.getElementById('contador-abastecimiento');
    if (weightElement) weightElement.textContent = formatearPesoKg(plannedWeight);
    if (summaryWeightElement) summaryWeightElement.textContent = formatearPesoKg(plannedWeight);
    if (siteElement) siteElement.textContent = currentPlSite || currentPlName || 'Sin site';
    if (routeElement) routeElement.textContent = activeRoute
        ? activeRoute.replaceAll('_', ' ')
        : 'Sin ruta asignada';
    if (fabricationElement) fabricationElement.textContent = `${fabrication.length} fabricación`;
    if (supplyElement) supplyElement.textContent = `${supply.length} abastecimiento`;
}

function canonicalizarCodigoOt(value, requiereEtiqueta = false) {
    const text = normalizarEtiquetaExcel(value);
    const expression = requiereEtiqueta
        ? /(?:\bOT\b|N[º°O.]?\s*O\.?\s*T\.?)\s*[:#-]?\s*(20\d{2}|\d{2})\s*[-_/]\s*(\d{1,4})\b/
        : /(?:\bOT\b|N[º°O.]?\s*O\.?\s*T\.?)?\s*(20\d{2}|\d{2})\s*[-_/]\s*(\d{1,4})\b/;
    const match = text.match(expression);
    if (!match) return null;
    const year = match[1].length === 2 ? `20${match[1]}` : match[1];
    return `${year}-${String(Number.parseInt(match[2], 10)).padStart(4, '0')}`;
}

function detectarReferenciasOt(fileName, rows) {
    const detectedInWorkbook = new Set();
    const collect = (value, requiereEtiqueta = false) => {
        const code = canonicalizarCodigoOt(value, requiereEtiqueta);
        if (code) detectedInWorkbook.add(code);
    };
    rows.slice(0, 40).forEach(row => {
        if (!Array.isArray(row)) return;
        collect(row.join(' '), true);
    });
    return {
        fileNameCode: canonicalizarCodigoOt(fileName),
        workbookCodes: Array.from(detectedInWorkbook)
    };
}

function indiceEncabezado(headers, tests) {
    return headers.findIndex(header => tests.some(test => (
        typeof test === 'string' ? header.includes(test) : test.test(header)
    )));
}

function detectarColumnasExcel(row) {
    if (!Array.isArray(row)) return null;
    const headers = row.map(normalizarEtiquetaExcel);
    const columns = {
        marca: indiceEncabezado(headers, ['MARCA', 'CODIGO', /^X3$/]),
        cantidad: indiceEncabezado(headers, ['CANTIDAD', /^CANT\b/, 'CANT T']),
        unidad: indiceEncabezado(headers, [/^UND\b/, 'UNIDAD']),
        descripcion: indiceEncabezado(headers, ['DESCRIP']),
        ubicacion: indiceEncabezado(headers, ['UBICACION', 'ZONA', 'LOCALIZACION']),
        perfil: indiceEncabezado(headers, ['PERFIL', 'SECCION']),
        material: indiceEncabezado(headers, ['MATERIAL', 'CALIDAD']),
        longitud: indiceEncabezado(headers, ['LONGITUD', /^LONG\b/, /^L\s*\[?MM/]),
        areaUnit: indiceEncabezado(headers, [/AREA.*(U\.?|UNIT)/]),
        areaTotal: indiceEncabezado(headers, [/AREA.*(T\.?|TOTAL)/]),
        pesoUnit: indiceEncabezado(headers, [/PESO.*(U\.?|UNIT)/]),
        pesoTotal: indiceEncabezado(headers, [/PESO.*(T\.?|TOTAL)/]),
        fecha: indiceEncabezado(headers, [
            /^FECHA$/,
            /FECHA.*(FABRIC|REALIZ|TERMIN|FINAL)/
        ])
    };
    return columns.marca !== -1 && columns.cantidad !== -1 ? columns : null;
}

function detectarColumnasAbastecimiento(row) {
    if (!Array.isArray(row)) return null;
    const headers = row.map(normalizarEtiquetaExcel);
    const cantidad = indiceEncabezado(headers, ['CANTIDAD', /^CANT\b/, 'CANT T']);
    const descripcion = indiceEncabezado(headers, ['DESCRIP']);
    if (cantidad === -1 || descripcion === -1) return null;
    return {
        marca: indiceEncabezado(headers, ['MARCA', 'CODIGO']),
        cantidad,
        unidad: indiceEncabezado(headers, [/^UND\b/, 'UNIDAD']),
        descripcion,
        ubicacion: indiceEncabezado(headers, ['UBICACION', 'ZONA', 'LOCALIZACION']),
        perfil: indiceEncabezado(headers, ['PERFIL', 'SECCION']),
        material: indiceEncabezado(headers, ['MATERIAL', 'CALIDAD']),
        longitud: indiceEncabezado(headers, ['LONGITUD', /^LONG\b/, /^L\s*\[?MM/]),
        areaUnit: indiceEncabezado(headers, [/AREA.*(U\.?|UNIT)/]),
        areaTotal: indiceEncabezado(headers, [/AREA.*(T\.?|TOTAL)/]),
        pesoUnit: indiceEncabezado(headers, [/PESO.*(U\.?|UNIT)/]),
        pesoTotal: indiceEncabezado(headers, [/PESO.*(T\.?|TOTAL)/]),
        fecha: indiceEncabezado(headers, [
            /^FECHA$/,
            /FECHA.*(FABRIC|REALIZ|TERMIN|FINAL)/
        ])
    };
}

function unidadCantidadExcel(value, fallback = '') {
    const explicitUnit = String(fallback || '').trim().toUpperCase();
    if (explicitUnit) return explicitUnit;
    const match = String(value ?? '').trim().toUpperCase().match(/[A-ZÁÉÍÓÚÑ]+/);
    return match ? match[0] : 'UND';
}

function prefijoAbastecimiento(section) {
    const key = `${section.categoria}:${section.subcategoria || ''}`;
    return {
        'PERNERIA:TEMPLATE': 'P-TEMP',
        'PERNERIA:TORRE': 'P-TOR',
        'SUMINISTRO:CABLE_DE_VIDA': 'CV',
        'SUMINISTRO:SISTEMA_DE_VIENTOS': 'SV',
        'SUMINISTRO:OTROS': 'SUM'
    }[key] || 'SUM';
}

function clasificarSeccionExcel(value) {
    const text = normalizarEtiquetaExcel(value);
    if (text.includes('PERNERIA TEMPLATE')) {
        return { tipo: 'p_template', categoria: 'PERNERIA', subcategoria: 'TEMPLATE' };
    }
    if (text.includes('PERNERIA TORRE')) {
        return { tipo: 'p_torre', categoria: 'PERNERIA', subcategoria: 'TORRE' };
    }
    if (/CABLES? DE VIDA/.test(text)) {
        return { tipo: 'c_vida', categoria: 'SUMINISTRO', subcategoria: 'CABLE_DE_VIDA' };
    }
    if (text.includes('SISTEMA DE VIENTOS')) {
        return { tipo: 'vientos', categoria: 'SUMINISTRO', subcategoria: 'SISTEMA_DE_VIENTOS' };
    }
    if (text.includes('OTROS SUMINISTROS') || text === 'SUMINISTROS') {
        return { tipo: 'suministro', categoria: 'SUMINISTRO', subcategoria: 'OTROS' };
    }
    if (
        text.includes('MATERIALES DE FABRICACION')
        || text.includes('MATERIALES PARA FABRICACION')
        || text === 'FABRICACION'
    ) {
        return { tipo: 'fab', categoria: 'FABRICACION', subcategoria: null };
    }
    return null;
}

function valorColumna(row, index) {
    return index >= 0 && index < row.length ? row[index] : '';
}

function fechaExcelIso(value) {
    if (value instanceof Date && !Number.isNaN(value.getTime())) {
        const year = value.getFullYear();
        const month = String(value.getMonth() + 1).padStart(2, '0');
        const day = String(value.getDate()).padStart(2, '0');
        return `${year}-${month}-${day}`;
    }
    if (typeof value === 'number' && Number.isFinite(value) && window.XLSX?.SSF) {
        const parts = XLSX.SSF.parse_date_code(value);
        if (parts?.y && parts?.m && parts?.d) {
            return `${parts.y}-${String(parts.m).padStart(2, '0')}-${String(parts.d).padStart(2, '0')}`;
        }
    }
    const text = String(value ?? '').trim();
    const isoMatch = text.match(/\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b/);
    if (isoMatch) return `${isoMatch[1]}-${isoMatch[2].padStart(2, '0')}-${isoMatch[3].padStart(2, '0')}`;
    const localMatch = text.match(/\b(\d{1,2})[-/.](\d{1,2})[-/.](20\d{2})\b/);
    if (localMatch) return `${localMatch[3]}-${localMatch[2].padStart(2, '0')}-${localMatch[1].padStart(2, '0')}`;
    return '';
}

function importarPackingList(event) {
    if (!canEdit || !currentPlId) return;
    const file = event.target.files[0];
    if (!file) return;
    pendingImportMeta = null;

    const reader = new FileReader();
    reader.onload = async function(loadEvent) {
        try {
            const data = new Uint8Array(loadEvent.target.result);
            const workbook = XLSX.read(data, { type: 'array', cellDates: true });
            const firstSheet = workbook.Sheets[workbook.SheetNames[0]];
            const json = XLSX.utils.sheet_to_json(firstSheet, {
                header: 1,
                defval: ""
            });

            const otReferences = detectarReferenciasOt(file.name, json);
            const detectedOtCodes = otReferences.workbookCodes;
            const expectedOtCode = canonicalizarCodigoOt(
                window.ProduccionConfig.otOt
            );
            const mismatchedOtCodes = detectedOtCodes.filter(
                code => expectedOtCode && code !== expectedOtCode
            );
            let otMismatchConfirmed = false;
            if (mismatchedOtCodes.length) {
                const canConfirmStaleHeader = (
                    otReferences.fileNameCode === expectedOtCode
                    && detectedOtCodes.length === 1
                );
                if (!canConfirmStaleHeader) {
                    mostrarAlerta(
                        `Importación bloqueada: esta pantalla corresponde a ${expectedOtCode}, pero el Excel contiene ${mismatchedOtCodes.join(', ')}.`,
                        'error'
                    );
                    return;
                }
                otMismatchConfirmed = await solicitarConfirmacionDiferenciaOt(
                    expectedOtCode,
                    mismatchedOtCodes[0]
                );
                if (!otMismatchConfirmed) return;
            } else if (
                otReferences.fileNameCode
                && expectedOtCode
                && otReferences.fileNameCode !== expectedOtCode
                && !detectedOtCodes.includes(expectedOtCode)
            ) {
                mostrarAlerta(
                    `Importación bloqueada: el nombre del archivo indica ${otReferences.fileNameCode}, no ${expectedOtCode}.`,
                    'error'
                );
                return;
            }

            let currentColumns = null;
            let firstHeaderRow = -1;
            for (let index = 0; index < Math.min(json.length, 40); index++) {
                const detectedColumns = detectarColumnasExcel(json[index]);
                if (detectedColumns) {
                    currentColumns = detectedColumns;
                    firstHeaderRow = index;
                    break;
                }
            }

            if (!currentColumns) {
                mostrarAlerta(
                    "No se detectó el formato del Packing List.",
                    "error"
                );
                return;
            }

            const componentes = [];
            const warnings = [];
            if (otMismatchConfirmed) {
                warnings.push(
                    `Encabezado ${mismatchedOtCodes[0]} confirmado manualmente para ${expectedOtCode}.`
                );
            }
            let currentSection = {
                tipo: 'fab',
                categoria: 'FABRICACION',
                subcategoria: null
            };
            const supplyCounters = new Map();

            for (let index = firstHeaderRow + 1; index < json.length; index++) {
                const row = json[index];
                if (!row || row.length === 0) continue;

                const rowText = row.join(' ');
                const candidateQuantity = numeroExcel(
                    valorColumna(row, currentColumns.cantidad)
                );
                const candidateMarca = String(
                    valorColumna(row, currentColumns.marca) || ''
                ).trim();
                const candidateDescription = String(
                    valorColumna(row, currentColumns.descripcion) || ''
                ).trim();
                const isStructuredDataRow = (
                    candidateQuantity !== null
                    && candidateQuantity > 0
                    && (
                        Boolean(candidateMarca)
                        || (
                            currentSection.categoria !== 'FABRICACION'
                            && Boolean(candidateDescription)
                        )
                    )
                );
                const section = isStructuredDataRow
                    ? null
                    : clasificarSeccionExcel(rowText);
                if (section) {
                    currentSection = section;
                    continue;
                }

                const repeatedHeader = currentSection.categoria === 'FABRICACION'
                    ? detectarColumnasExcel(row)
                    : (detectarColumnasAbastecimiento(row) || detectarColumnasExcel(row));
                if (repeatedHeader) {
                    currentColumns = repeatedHeader;
                    continue;
                }

                const rawMarca = valorColumna(row, currentColumns.marca);
                const rawCantidad = valorColumna(row, currentColumns.cantidad);
                const isSupply = currentSection.categoria !== 'FABRICACION';
                let marca = String(rawMarca || '').trim();
                const cantidad = numeroExcel(rawCantidad);
                if ((!marca && !isSupply) || cantidad === null || cantidad <= 0) continue;
                if (!Number.isInteger(cantidad)) {
                    warnings.push(`Fila ${index + 1}: la cantidad de ${marca || 'abastecimiento'} no es entera y no se importó.`);
                    continue;
                }

                if (!marca) {
                    const supplyKey = `${currentSection.categoria}:${currentSection.subcategoria || ''}`;
                    const supplyIndex = (supplyCounters.get(supplyKey) || 0) + 1;
                    supplyCounters.set(supplyKey, supplyIndex);
                    marca = `${prefijoAbastecimiento(currentSection)}-${String(supplyIndex).padStart(3, '0')}`;
                }

                const descripcion = String(
                    valorColumna(row, currentColumns.descripcion) || ''
                ).toUpperCase().trim();
                const longitud = numeroExcel(
                    valorColumna(row, currentColumns.longitud)
                );
                const areaUnit = numeroExcel(
                    valorColumna(row, currentColumns.areaUnit)
                );
                let areaTotal = numeroExcel(
                    valorColumna(row, currentColumns.areaTotal)
                );
                const pesoUnit = numeroExcel(
                    valorColumna(row, currentColumns.pesoUnit)
                );
                let pesoTotal = numeroExcel(
                    valorColumna(row, currentColumns.pesoTotal)
                );
                if (areaTotal === null && areaUnit !== null) {
                    areaTotal = areaUnit * cantidad;
                }
                if (pesoTotal === null && pesoUnit !== null) {
                    pesoTotal = pesoUnit * cantidad;
                }

                const selectedRoute = document.getElementById('import-route-select')?.value || '';

                componentes.push({
                    marca,
                    cantidad,
                    descripcion,
                    longitud: longitud !== null
                        ? longitud.toFixed(1)
                        : '0.0',
                    longitud_mm: longitud,
                    unidad: unidadCantidadExcel(
                        rawCantidad,
                        valorColumna(row, currentColumns.unidad)
                    ),
                    ubicacion: String(
                        valorColumna(row, currentColumns.ubicacion) || ''
                    ).trim(),
                    perfil: String(
                        valorColumna(row, currentColumns.perfil) || ''
                    ).trim(),
                    material: String(
                        valorColumna(row, currentColumns.material) || ''
                    ).trim(),
                    area_unitaria_m2: areaUnit,
                    area_total_m2: areaTotal,
                    peso_unitario_kg: pesoUnit,
                    peso_total_kg: pesoTotal,
                    fila_origen: index + 1,
                    tipo: currentSection.tipo,
                    categoria: currentSection.categoria,
                    subcategoria: currentSection.subcategoria,
                    ruta_codigo: currentSection.categoria === 'FABRICACION'
                        ? selectedRoute
                        : null,
                    estado_suministro: currentSection.categoria === 'FABRICACION'
                        ? 'No requerido'
                        : 'Pendiente',
                    operario: '',
                    fecha_realizacion: currentColumns.fecha !== -1
                        ? (fechaExcelIso(row[currentColumns.fecha]) || null)
                        : null,
                    fecha_inicio_real: null,
                    fecha_termino_real: currentColumns.fecha !== -1
                        ? (fechaExcelIso(row[currentColumns.fecha]) || null)
                        : null,
                    hab: null,
                    arm: null,
                    sol: null,
                    lim: null,
                    lib: null,
                    gal: null,
                    are: null,
                    pin: null,
                    des: 0
                });
            }

            const fabricationItems = componentes.filter(
                component => component.categoria === 'FABRICACION'
            );
            const supplyItems = componentes.filter(
                component => component.categoria !== 'FABRICACION'
            );
            const routeCode = document.getElementById('import-route-select')?.value || '';
            if (fabricationItems.length && !routeCode) {
                mostrarAlerta(
                    'Selecciona la ruta de fabricación antes de importar el Excel.',
                    'error'
                );
                return;
            }
            if (!detectedOtCodes.length) {
                warnings.push('No se encontró un código OT dentro del archivo ni en su nombre.');
            }
            const withoutWeight = fabricationItems.filter(
                component => !(component.peso_total_kg > 0)
            ).length;
            if (withoutWeight) {
                warnings.push(`${withoutWeight} elementos de fabricación no contienen peso total.`);
            }

            if (componentes.length === 0) {
                mostrarAlerta(
                    "El Excel no contiene elementos válidos para importar.",
                    "error"
                );
                return;
            }

            const importedSite = document.getElementById('import-site-input')?.value.trim() || '';
            const importedFingerprint = stableComponentsFingerprint(componentes);
            if (
                loadedComponentsFingerprint !== null
                && importedFingerprint === loadedComponentsFingerprint
                && importedSite === String(currentPlSite || '').trim()
            ) {
                pendingImportMeta = null;
                setPendingImport(false);
                mostrarAlerta(
                    'El Excel coincide con la información guardada. No hay cambios pendientes.',
                    'info'
                );
                return;
            }

            pendingImportMeta = {
                schema_version: 2,
                archivo: file.name,
                hoja: workbook.SheetNames[0],
                site: importedSite,
                ot_detectadas: detectedOtCodes,
                ot_diferencia_confirmada: otMismatchConfirmed,
                ruta_codigo: routeCode,
                advertencias: warnings
            };
            renderizarTabla(componentes, false);
            setPendingImport(true);
            const datedElements = componentes.filter(component => component.fecha_termino_real).length;
            const totalWeight = fabricationItems.reduce(
                (sum, component) => sum + (Number(component.peso_total_kg) || 0),
                0
            );
            mostrarAlerta(
                `Excel cargado: ${componentes.length} elementos · ${formatearPesoKg(totalWeight)} de fabricación · ${supplyItems.length} de abastecimiento${datedElements ? ` · ${datedElements} con fecha` : ''}${warnings.length ? ` · ${warnings.length} advertencias` : ''}. Pendiente de guardar.`,
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

const PROCESS_SEQUENCES = {
    GALVANIZADO: ['hab', 'arm', 'sol', 'lim', 'lib', 'gal'],
    PINTADO: ['hab', 'arm', 'sol', 'lim', 'lib', 'are', 'pin']
};

function processSequenceForRow(row) {
    const routeCode = String(row.dataset.rutaCodigo || '').toUpperCase();
    return PROCESS_SEQUENCES[routeCode]
        || procesosProd.filter(key => key !== 'des' && activeProcs[key]);
}

function paintProcessCell(row, procKey, value, maxCant) {
    const percentageCell = row.querySelector(`.pct-${procKey}`);
    if (!percentageCell) return;
    if (value === null) {
        percentageCell.innerText = '—';
        percentageCell.className = `px-1 py-1 text-center w-[45px] font-medium text-slate-300 bg-white border-r border-slate-200 pct-${procKey} col-${procKey}`;
        return;
    }
    const percentage = maxCant > 0 ? (value / maxCant) * 100 : 0;
    percentageCell.innerText = `${percentage.toFixed(1)}%`;
    if (percentage >= 100) {
        percentageCell.className = `px-1 py-1 text-center w-[45px] font-black text-emerald-600 bg-emerald-50 border-r border-slate-200 pct-${procKey} col-${procKey}`;
    } else if (percentage > 0) {
        percentageCell.className = `px-1 py-1 text-center w-[45px] font-bold text-blue-600 bg-blue-50/50 border-r border-slate-200 pct-${procKey} col-${procKey}`;
    } else {
        percentageCell.className = `px-1 py-1 text-center w-[45px] font-medium text-slate-400 bg-white border-r border-slate-200 pct-${procKey} col-${procKey}`;
    }
}

function validarYCalcular(input, maxCant, procKey, skipSave = false, skipRecalculate = false) {
    if (!canEdit && !skipSave) return;
    const row = input.closest('tr');
    if (!row) return;

    const previousValue = input.dataset.lastValidValue ?? '';
    const valueText = input.value.trim();
    let value = valueText === '' ? null : Number.parseInt(valueText, 10);
    if (value !== null && !Number.isFinite(value)) value = 0;
    if (value !== null) value = Math.max(0, Math.min(value, maxCant));

    if (procKey !== 'des' && value !== null && value > 0) {
        const sequence = processSequenceForRow(row);
        const position = sequence.indexOf(procKey);
        if (position >= 0) {
            const blockingStep = sequence.slice(position + 1).find(key => {
                const laterValue = optionalProgressNumber(row.querySelector(`.proc-${key}`)?.value);
                return laterValue !== null && laterValue > value;
            });
            if (blockingStep) {
                input.value = previousValue;
                mostrarAlerta(
                    `No se puede bajar este proceso: ${blockingStep.toUpperCase()} ya registra un avance mayor.`,
                    'error'
                );
                return;
            }

            const adjustedNames = [];
            sequence.slice(0, position).forEach(key => {
                const previousInput = row.querySelector(`.proc-${key}`);
                const previousProgress = optionalProgressNumber(previousInput?.value);
                if (previousInput && previousProgress !== null && previousProgress > 0 && previousProgress < value) {
                    previousInput.value = value;
                    previousInput.dataset.lastValidValue = String(value);
                    paintProcessCell(row, key, value, maxCant);
                    adjustedNames.push(key.toUpperCase());
                }
            });
            if (adjustedNames.length && !skipSave) {
                mostrarAlerta(
                    `Se ajustó ${adjustedNames.join(', ')} a ${value} para mantener la secuencia.`,
                    'info'
                );
            }
        }
    }

    input.value = value === null ? '' : String(value);
    input.dataset.lastValidValue = input.value;

    if (procKey === 'des') {
        value = value ?? 0;
        input.value = String(value);
        const dateCell = row.querySelector('.pct-des');
        if (dateCell) {
            if (value > 0) {
                const completionDate = row.dataset.fechaTerminoReal || '';
                const date = completionDate
                    ? new Date(`${completionDate}T00:00:00`).toLocaleDateString('es-PE', {day: '2-digit', month: 'short'}).toUpperCase()
                    : 'SIN FECHA';
                dateCell.innerHTML = `<span class="font-black ${completionDate ? 'text-slate-800' : 'text-slate-400'}">${date}</span>`;
                dateCell.className = 'px-1 py-1.5 text-center bg-slate-200 border-l border-slate-300 sticky-r2 pct-des';
            } else {
                dateCell.innerHTML = '-';
                dateCell.className = 'px-1 py-1.5 text-center bg-slate-50 border-l border-slate-200 sticky-r2 pct-des text-slate-400 font-medium';
            }
        }
    } else {
        paintProcessCell(row, procKey, value, maxCant);
    }

    if (!skipSave && row.dataset.id) {
        programarGuardadoCelda(row.dataset.id, `${procKey}_real`, value);
    }
    if (!skipRecalculate) recalcularMatriz();
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

    let sumasProcesos = { hab: 0, arm: 0, sol: 0, lim: 0, lib: 0, gal: 0, are: 0, pin: 0 };
    let conteoFilasValidas = { hab: 0, arm: 0, sol: 0, lim: 0, lib: 0, gal: 0, are: 0, pin: 0 };

    let sumaAvancesTotales = 0; let pesoFab = 0;
    let sumaAvancesABA = 0; let unidadesABA = 0;
    let alertCount = 0;

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
            const pesoFisico = Math.max(parseFloat(fila.dataset.pesoTotalKg) || 0, 0);
            procesosProd.forEach(key => {
                if(key === 'des') return; if(!activeProcs[key]) return;
                const input = fila.querySelector(`.proc-${key}`); if (!input) return;
                const valStr = input.value.trim();
                const valNum = parseFloat(valStr);

                if(!isNaN(valNum) && valNum !== -1) {
                    const porc = cantT > 0 ? valNum / cantT : 0;
                    avanceFilaPonderado += (porc * pesos[key]);
                    pesoFilaTotal += pesos[key];
                    if (pesoFisico > 0) {
                        sumasProcesos[key] += porc * pesoFisico;
                        conteoFilasValidas[key] += pesoFisico;
                    }
                }
            });
            porcFilaFinal = pesoFilaTotal > 0 ? (avanceFilaPonderado / pesoFilaTotal) * 100 : 0;
            if (pesoFisico > 0) {
                sumaAvancesTotales += porcFilaFinal * pesoFisico;
                pesoFab += pesoFisico;
            }
        }

        if (fila.classList.contains('row-alert')) alertCount += 1;

        const tdTotal = fila.querySelector('.row-total-percentage');
        if (tdTotal) {
            fila.dataset.porcentaje = porcFilaFinal;
            tdTotal.innerText = `${porcFilaFinal.toFixed(1)}%`;
            if (porcFilaFinal === 100) { tdTotal.className = "px-2 py-1 text-center font-black text-emerald-400 bg-slate-900 sticky-r1 shadow-left row-total-percentage align-middle"; }
            else { tdTotal.className = "px-2 py-1 text-center font-black text-white bg-slate-900 sticky-r1 shadow-left row-total-percentage align-middle"; }
        }
    });

    const elGlobal = document.getElementById('global-avance-total');
    const globalProgress = pesoFab > 0 ? (sumaAvancesTotales / pesoFab) : 0;
    const advancedWeight = pesoFab * globalProgress / 100;
    if (elGlobal) elGlobal.innerText = `${globalProgress.toFixed(1)}%`;
    const advancedWeightElement = document.getElementById('global-peso-avanzado');
    if (advancedWeightElement) advancedWeightElement.innerText = formatearPesoKg(advancedWeight);
    const summaryProgress = document.getElementById('production-summary-progress');
    const summaryProgressBar = document.getElementById('production-summary-progress-bar');
    const summaryAdvancedWeight = document.getElementById('production-summary-advanced-weight');
    if (summaryProgress) summaryProgress.innerText = `${globalProgress.toFixed(1)}%`;
    if (summaryProgressBar) summaryProgressBar.style.width = `${Math.max(0, Math.min(globalProgress, 100))}%`;
    if (summaryAdvancedWeight) summaryAdvancedWeight.innerText = formatearPesoKg(advancedWeight);

    const elABA = document.getElementById('global-avance-aba');
    if (elABA) elABA.innerText = `${(unidadesABA > 0 ? (sumaAvancesABA / unidadesABA) : 0).toFixed(1)}%`;

    procesosProd.forEach(p => {
        if(p === 'des') return; const el = document.getElementById(`box-${p}`);
        const promedio = conteoFilasValidas[p] > 0 ? (sumasProcesos[p] / conteoFilasValidas[p]) * 100 : 0;
        if (el) el.innerText = `${promedio.toFixed(1)}%`;
        const insight = document.querySelector(`[data-insight-process="${p}"]`);
        if (insight) {
            const value = insight.querySelector('strong');
            const bar = insight.querySelector('b');
            if (value) value.innerText = `${promedio.toFixed(1)}%`;
            if (bar) bar.style.width = `${Math.max(0, Math.min(promedio, 100))}%`;
            insight.hidden = activeProcs[p] === false;
        }
    });

    const alertCounter = document.getElementById('production-alert-count');
    const alertsContainer = document.getElementById('production-insight-alerts');
    if (alertCounter) alertCounter.textContent = `${alertCount} ${alertCount === 1 ? 'activa' : 'activas'}`;
    if (alertsContainer) {
        alertsContainer.innerHTML = alertCount
            ? `<p class="is-warning"><span class="material-symbols-rounded">warning</span>${alertCount} ${alertCount === 1 ? 'elemento requiere' : 'elementos requieren'} revisión.</p>`
            : '<p><span class="material-symbols-rounded">task_alt</span>Sin inconsistencias visibles en el lote.</p>';
    }
}

function filtrarSoloFaltantes() {
    const rows = Array.from(document.querySelectorAll('#matriz-body tr[data-cant]'));
    const showingOnlyPending = document.body.classList.toggle('production-only-pending');
    rows.forEach((row) => {
        const progress = Number.parseFloat(row.dataset.porcentaje || '0');
        row.style.display = showingOnlyPending && progress >= 100 ? 'none' : '';
    });
    mostrarAlerta(
        showingOnlyPending ? 'Mostrando únicamente elementos pendientes.' : 'Mostrando todos los elementos.',
        'info'
    );
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
    const startDateInput = document.getElementById('det-fecha-inicio-real');
    const endDateInput = document.getElementById('det-fecha-termino-real');
    if (startDateInput) {
        startDateInput.value = currentDetalleRow.dataset.fechaInicioReal || '';
        startDateInput.dataset.previous = startDateInput.value;
    }
    if (endDateInput) {
        endDateInput.value = currentDetalleRow.dataset.fechaTerminoReal || '';
        endDateInput.dataset.previous = endDateInput.value;
    }

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
    const processRows = [];
    const assignmentCards = [];

    const nombresProcObj = {hab: 'Habilitado', arm: 'Armado', sol: 'Soldado', lim: 'Limpieza', lib: 'Liberación', gal: 'Galvanizado', are: 'Arenado', pin: 'Pintado'};

    if (isSuministro) {
        const selectEstado = currentDetalleRow.querySelector('.select-estado-suministro');
        const estActual = selectEstado ? selectEstado.value : 'No requerido';

        const supplyStatusClass = estActual === 'Entregado' || estActual === 'Despachado'
            ? 'is-complete'
            : (estActual !== 'No requerido' ? 'is-progress' : '');

        processRows.push(`<tr>
            <td>Abastecimiento</td>
            <td><span class="production-detail-process-status ${supplyStatusClass}"><i></i>${escapeHtml(estActual)}</span></td>
            <td>-</td><td>-</td><td>${porcTotal.toFixed(1)}%</td>
        </tr>`);

        assignmentCards.push(`<div class="production-detail-supply">
            <strong>Estado de abastecimiento</strong>
            <span>${escapeHtml(estActual)}</span>
        </div>`);
    } else {
        procesosProd.forEach(p => {
            if (p === 'des' || !activeProcs[p]) return;
            const input = currentDetalleRow.querySelector(`.proc-${p}`);
            if (input) {
                const registeredValue = optionalProgressNumber(input.value);
                const val = registeredValue ?? 0;
                const isUnregistered = registeredValue === null;

                let txtEstado = isUnregistered ? 'Sin registrar' : 'Pendiente';
                let statusClass = '';
                if(val >= cant && cant > 0) { txtEstado = 'Completado'; statusClass = 'is-complete'; }
                else if(val > 0) { txtEstado = 'En proceso'; statusClass = 'is-progress'; }

                const porcentajeLocal = isUnregistered ? '—' : (cant > 0 ? ((val / cant) * 100).toFixed(1) : '0.0') + '%';
                const operatorName = opDict[p] || '';
                const processControls = canEdit ? `
                        <div class="production-detail-operator">
                            <span>Personal asignado</span>
                            <button type="button" onclick="abrirSelectorPersonal('${p}')" class="production-detail-personnel-trigger">
                                <strong>${operatorName ? escapeHtml(operatorName) : 'Seleccionar personal'}</strong>
                                <span class="material-symbols-rounded" aria-hidden="true">expand_more</span>
                            </button>
                            <small>${operatorName ? 'Selecciona nuevamente para cambiar la asignación.' : 'Elige una persona registrada.'}</small>
                        </div>`
                    : `<div class="production-detail-readonly"><span>Operario</span>
                        <strong>${operatorName ? escapeHtml(operatorName) : 'Sin operarios asignados'}</strong>
                    </div>`;

                processRows.push(`<tr>
                    <td>${nombresProcObj[p]}</td>
                    <td><span class="production-detail-process-status ${statusClass}"><i></i>${txtEstado}</span></td>
                    <td>${cant}</td>
                    <td>${isUnregistered ? '—' : val}</td>
                    <td>${porcentajeLocal}</td>
                </tr>`);

                assignmentCards.push(`<article class="production-detail-assignment">
                    <div class="production-detail-assignment-heading">
                        <strong>${nombresProcObj[p]}</strong>
                        <span>${txtEstado} · ${porcentajeLocal}</span>
                    </div>
                    <div class="production-detail-assignment-controls">
                        ${processControls}
                    </div>
                </article>`);
            }
        });
    }

    if (tablaContainer) tablaContainer.innerHTML = processRows.join('');
    if (cardsContainer) cardsContainer.innerHTML = assignmentCards.join('');

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

async function guardarPeriodoElemento(input, fieldName) {
    if (!canEdit || !input || !currentDetalleRow?.dataset.id) return;
    const elementRow = currentDetalleRow;
    const previousValue = input.dataset.previous || '';
    const nextValue = input.value || null;
    const startValue = fieldName === 'fecha_inicio_real'
        ? nextValue
        : (elementRow.dataset.fechaInicioReal || null);
    const endValue = fieldName === 'fecha_termino_real'
        ? nextValue
        : (elementRow.dataset.fechaTerminoReal || null);
    if (startValue && endValue && endValue < startValue) {
        input.value = previousValue;
        mostrarAlerta('La fecha de término no puede ser anterior al inicio.', 'error');
        return;
    }
    input.disabled = true;

    const saved = await encolarGuardadoComponente(
        elementRow.dataset.id,
        fieldName,
        nextValue,
    );

    if (saved) {
        const storedValue = nextValue || '';
        if (fieldName === 'fecha_inicio_real') elementRow.dataset.fechaInicioReal = storedValue;
        if (fieldName === 'fecha_termino_real') elementRow.dataset.fechaTerminoReal = storedValue;
        input.dataset.previous = storedValue;
        const dispatchInput = elementRow.querySelector('.proc-des');
        if (dispatchInput && Number(dispatchInput.value) > 0) {
            validarYCalcular(
                dispatchInput,
                Number.parseFloat(elementRow.dataset.cant) || 0,
                'des',
                true,
                true,
            );
        }
        mostrarAlerta(
            storedValue ? 'Período del elemento actualizado.' : 'Fecha del elemento eliminada.',
            'exito',
        );
    } else {
        input.value = previousValue;
    }

    input.disabled = !canEdit;
}


async function guardarOpProceso(proc, nombre) {
    if (!canEdit || !currentDetalleRow) return false;
    const operatorRow = currentDetalleRow;
    const hiddenOperator = operatorRow.querySelector('.input-operario');
    if (!hiddenOperator || !operatorRow.dataset.id) return false;

    const operatorMap = parseOperarios(hiddenOperator.value);
    operatorMap[proc] = normalizeOperatorNames(nombre);
    const previousValue = hiddenOperator.value;
    const nextValue = stringifyOperarios(operatorMap);
    hiddenOperator.value = nextValue;

    const saved = await encolarGuardadoComponente(
        operatorRow.dataset.id,
        'operario',
        nextValue,
    );
    if (saved) {
        mostrarAlerta('Operarios actualizados.', 'exito');
        abrirDetalle(
            currentDetalleRow.querySelector('.btn-detalle'),
            document.getElementById('det-marca').innerText,
            document.getElementById('det-long').innerText.replace(' mm',''),
            Number.parseFloat(document.getElementById('det-cant').innerText) || 0,
            document.getElementById('det-desc').innerText,
            currentDetalleRow.dataset.tipo
        );
        return true;
    } else {
        if (hiddenOperator.value === nextValue) hiddenOperator.value = previousValue;
        return false;
    }
}

function configurarNavegacionSegura() {
    const trackingLink = document.querySelector('[data-wait-for-production-saves]');
    if (!canEdit) return;

    window.addEventListener('beforeunload', (event) => {
        if (allowConfirmedNavigation || !hasUnsavedProductionChanges()) return;
        event.preventDefault();
        event.returnValue = '';
    });

    document.addEventListener('click', (event) => {
        const link = event.target.closest('a[href]');
        if (
            !link
            || !hasUnsavedProductionChanges()
            || event.defaultPrevented
            || event.button !== 0
            || event.ctrlKey
            || event.metaKey
            || event.shiftKey
            || event.altKey
            || link.target === '_blank'
            || link.hasAttribute('download')
        ) return;
        const destination = new URL(link.href, window.location.href);
        if (destination.href === window.location.href || destination.protocol === 'javascript:') return;

        const confirmed = window.confirm(
            hasPendingImport
                ? 'El Excel cargado todavía no fue guardado. Si sales, perderás estos datos.\n\n¿Deseas salir de todos modos?'
                : 'Todavía hay avances guardándose. Si sales ahora, el último cambio podría perderse.\n\n¿Deseas salir de todos modos?'
        );
        if (!confirmed) {
            event.preventDefault();
            event.stopImmediatePropagation();
            return;
        }
        allowConfirmedNavigation = true;
    }, true);

    if (!trackingLink) return;

    trackingLink.addEventListener('click', async (event) => {
        if (
            event.defaultPrevented
            || event.button !== 0
            || event.ctrlKey
            || event.metaKey
            || event.shiftKey
            || event.altKey
        ) return;

        event.preventDefault();
        const destination = trackingLink.href;
        if (document.activeElement instanceof HTMLElement) {
            document.activeElement.blur();
        }
        await Promise.resolve();

        if (cellSaveTimers.size > 0) {
            await new Promise((resolve) => window.setTimeout(
                resolve,
                CELL_SAVE_DELAY_MS + 50,
            ));
        }

        trackingLink.setAttribute('aria-busy', 'true');
        trackingLink.classList.add('pointer-events-none', 'opacity-60');
        const saved = await cellSaveQueue;
        if (saved === false) {
            trackingLink.removeAttribute('aria-busy');
            trackingLink.classList.remove('pointer-events-none', 'opacity-60');
            return;
        }
        window.location.assign(destination);
    });
}


function toggleChat() {
    const drawer = document.getElementById('chat-drawer');
    const overlay = document.getElementById('chat-overlay');
    const trigger = document.getElementById('production-chat-trigger');
    if (!drawer || !overlay) return;

    const opening = drawer.classList.contains('translate-x-full');
    if (opening) {
        drawer.classList.remove('translate-x-full');
        drawer.setAttribute('aria-hidden', 'false');
        if (trigger) trigger.setAttribute('aria-expanded', 'true');
        overlay.classList.add('overlay-open');
        cargarMensajes();
        const chatInput = document.getElementById('chat-input');
        if (chatInput) chatInput.focus();
    } else {
        drawer.classList.add('translate-x-full');
        drawer.setAttribute('aria-hidden', 'true');
        if (trigger) trigger.setAttribute('aria-expanded', 'false');
        overlay.classList.remove('overlay-open');
        if (trigger) trigger.focus();
    }
}

function prepararHistorialMensajes(history, hasMessages) {
    history.replaceChildren();

    if (!hasMessages) {
        const empty = document.createElement('div');
        empty.className = 'production-chat-empty';
        const icon = document.createElement('span');
        icon.className = 'material-symbols-rounded';
        icon.textContent = 'chat_bubble';
        const title = document.createElement('strong');
        title.textContent = 'Sin mensajes todavía';
        const copy = document.createElement('span');
        copy.textContent = 'Los mensajes de esta orden aparecerán aquí.';
        empty.append(icon, title, copy);
        history.appendChild(empty);
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
            prepararHistorialMensajes(history, data.length > 0);
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
    const sendButton = document.querySelector('.production-chat-send');
    const message = input?.value.trim();
    if (!input || !message) return;

    input.disabled = true;
    if (sendButton) sendButton.disabled = true;
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
        if (sendButton) sendButton.disabled = false;
        input.focus();
    }
}

function agregarMensajeAlDOM(msg) {
    const history = document.getElementById('chat-history');
    const esMio = Boolean(msg.usuario_id && msg.usuario_id.toString() === currentUserId.toString());
    const nameText = esMio ? 'Tú' : (msg.usuario_nombre || 'Usuario');
    const fechaMostrar = msg.fecha && !msg.fecha.includes('Invalid') ? msg.fecha : 'Recién';
    if (!history) return;

    const emptyState = history.querySelector('.production-chat-empty');
    if (emptyState) emptyState.remove();

    const wrapper = document.createElement('div');
    wrapper.className = `production-chat-message ${esMio ? 'is-own' : 'is-other'}`;

    const metadata = document.createElement('div');
    metadata.className = 'production-chat-message-meta';
    metadata.append(document.createTextNode(String(nameText)));

    const date = document.createElement('time');
    date.textContent = String(fechaMostrar);
    metadata.append(date);

    const messageRow = document.createElement('div');
    messageRow.className = 'production-chat-message-row';

    let avatar = null;
    if (!esMio) {
        avatar = document.createElement('span');
        avatar.className = 'production-chat-avatar';
        avatar.setAttribute('aria-hidden', 'true');
        avatar.textContent = String(nameText)
            .trim()
            .split(/\s+/)
            .slice(0, 2)
            .map(part => part.charAt(0))
            .join('')
            .toUpperCase() || 'US';
    }

    const bubble = document.createElement('div');
    bubble.className = 'production-chat-bubble';
    bubble.textContent = String(msg.mensaje ?? '');

    let deleteButton = null;
    if (isAdmin) {
        deleteButton = document.createElement('button');
        deleteButton.type = 'button';
        deleteButton.className = 'production-chat-delete';
        deleteButton.title = 'Eliminar mensaje';
        deleteButton.setAttribute('aria-label', 'Eliminar mensaje');
        const deleteIcon = document.createElement('span');
        deleteIcon.className = 'material-symbols-rounded';
        deleteIcon.textContent = 'delete';
        deleteButton.appendChild(deleteIcon);
        deleteButton.addEventListener('click', () => eliminarMensaje(msg.id, deleteButton));
    }

    if (esMio && deleteButton) messageRow.appendChild(deleteButton);
    if (avatar) messageRow.appendChild(avatar);
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
