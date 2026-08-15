document.documentElement.classList.remove('dark');
const observer = new MutationObserver(() => {
    if (document.documentElement.classList.contains('dark')) {
        document.documentElement.classList.remove('dark');
    }
});
observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });

window.addEventListener('DOMContentLoaded', () => {
    const themeBtn = document.getElementById('themeToggleBtn');
    if (themeBtn) themeBtn.style.display = 'none';
    if (!window.ReporteConfig.canGenerate && !window.ReporteConfig.is2026) {
        document.getElementById('count-display').innerText = document.querySelectorAll('.photo-item-25').length;
    }
});


const IS_2026 = window.ReporteConfig.is2026;
const CAN_GENERATE = window.ReporteConfig.canGenerate;
const REPORT_REQUEST_TIMEOUT_MS = 240000;

function responseStatusMessage(status, fallback) {
    const messages = {
        400: 'La solicitud del reporte no es válida.',
        401: 'Tu sesión venció. Inicia sesión nuevamente y repite la operación.',
        403: 'No tienes permiso para realizar esta operación.',
        404: 'No se encontró la OT o su carpeta de fotografías.',
        413: 'El reporte supera el tamaño permitido. Selecciona menos fotografías.',
        422: 'Una o más fotografías no pudieron procesarse.',
        429: 'Se alcanzó el límite de reportes. Espera un minuto e inténtalo nuevamente.',
        502: 'Google Drive o el servidor no respondió correctamente.',
        503: 'El servicio de fotografías no está disponible en este momento.',
        504: 'La generación tardó demasiado y fue interrumpida.',
    };
    return messages[status] || fallback;
}

async function readApiJson(response, fallback) {
    const rawBody = await response.text();
    let payload = null;

    if (rawBody.trim()) {
        try {
            payload = JSON.parse(rawBody);
        } catch (_) {
            payload = null;
        }
    }

    if (!response.ok) {
        const serverMessage = payload && typeof payload.error === 'string'
            ? payload.error.trim()
            : '';
        throw new Error(serverMessage || responseStatusMessage(response.status, fallback));
    }
    if (!payload || typeof payload !== 'object') {
        throw new Error(responseStatusMessage(response.status, fallback));
    }
    return payload;
}

async function readReportHtml(response) {
    const rawBody = await response.text();
    if (!response.ok) {
        let serverMessage = '';
        try {
            const payload = JSON.parse(rawBody);
            serverMessage = typeof payload.error === 'string' ? payload.error.trim() : '';
        } catch (_) {
            if (!/^\s*</.test(rawBody)) serverMessage = rawBody.trim();
        }
        throw new Error(
            serverMessage
            || responseStatusMessage(response.status, 'No se pudo generar el reporte.'),
        );
    }
    if (!rawBody.trim() || !/<html[\s>]/i.test(rawBody)) {
        throw new Error('El servidor devolvió un reporte incompleto. Inténtalo nuevamente.');
    }
    return rawBody;
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

function createPhotoCard(imageId, source, is2026) {
    const safeId = String(imageId ?? '');
    const safeSource = String(source ?? '');
    if (!/^[A-Za-z0-9_-]+$/.test(safeId)) throw new Error('Identificador de imagen inválido.');
    if (!safeSource.startsWith('https://') && !safeSource.startsWith('data:image/')) {
        throw new Error('Origen de imagen inválido.');
    }

    const card = document.createElement('div');
    card.className = `${is2026 ? 'photo-item' : 'photo-item-25'} relative group aspect-[4/3] rounded-xl bg-slate-100 overflow-hidden ${CAN_GENERATE ? 'cursor-pointer hover:border-blue-400' : 'cursor-default'} shadow-sm border border-slate-200 transition-all duration-300`;
    card.dataset.id = safeId;

    const image = document.createElement('img');
    image.src = safeSource;
    image.dataset.originalSrc = safeSource;
    image.id = `img-node-${safeId}`;
    image.referrerPolicy = 'no-referrer';
    image.loading = 'lazy';
    image.className = 'w-full h-full object-cover pointer-events-none transition-transform duration-500';

    const cropButton = document.createElement('button');
    cropButton.type = 'button';
    cropButton.className = 'absolute top-2 left-2 z-30 bg-slate-900/80 text-white rounded-lg p-1.5 hover:bg-blue-600 transition hidden group-hover:flex shadow-sm';
    const cropIcon = document.createElement('span');
    cropIcon.className = 'material-symbols-rounded text-[15px]';
    cropIcon.textContent = 'crop';
    cropButton.appendChild(cropIcon);
    cropButton.addEventListener('click', event => openCropper(safeId, event));

    const border = document.createElement('div');
    border.className = `${is2026 ? '' : 'border-overlay '}absolute inset-0 rounded-xl pointer-events-none transition-all duration-200 z-10`;
    if (is2026) border.id = `border-${safeId}`;

    const badge = document.createElement('div');
    badge.className = `${is2026 ? '' : 'badge-overlay '}hidden absolute top-2 right-2 w-8 h-8 bg-blue-700 text-white rounded-full flex items-center justify-center text-[13px] font-black shadow-xl border-[2px] border-white z-20 badge-anim`;
    if (is2026) {
        badge.id = `badge-${safeId}`;
        badge.textContent = '0';
    } else {
        const checkIcon = document.createElement('span');
        checkIcon.className = 'material-symbols-rounded text-[16px]';
        checkIcon.textContent = 'check';
        badge.appendChild(checkIcon);
    }

    if (CAN_GENERATE) card.append(image, cropButton, border, badge);
    else card.append(image, border);
    return card;
}

function mostrarAlerta(mensaje, tipo = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    const bg = tipo === 'error' ? 'bg-red-600' : (tipo === 'exito' ? 'bg-emerald-600' : 'bg-slate-900');
    const icon = tipo === 'error' ? 'error' : (tipo === 'exito' ? 'check_circle' : 'info');

    toast.className = `${bg} text-white px-5 py-3 rounded-lg shadow-xl font-bold text-[12px] flex items-center gap-2 transform transition-all duration-300 -translate-y-10 opacity-0`;
    const iconElement = document.createElement('span');
    iconElement.className = 'material-symbols-rounded text-[18px]';
    iconElement.textContent = icon;
    const messageElement = document.createElement('span');
    messageElement.textContent = String(mensaje ?? '');
    toast.append(iconElement, messageElement);
    container.appendChild(toast);

    requestAnimationFrame(() => { toast.classList.remove('-translate-y-10', 'opacity-0'); toast.classList.add('translate-y-0', 'opacity-100'); });
    setTimeout(() => { toast.classList.remove('translate-y-0', 'opacity-100'); toast.classList.add('-translate-y-10', 'opacity-0'); setTimeout(() => toast.remove(), 300); }, 3000);
}

let onConfirmCallback = null;
function solicitarConfirmacion(mensaje, callback) {
    document.getElementById('confirm-text').innerText = mensaje;
    onConfirmCallback = callback;
    const modal = document.getElementById('confirm-modal');
    const box = document.getElementById('confirm-box');
    modal.classList.remove('hidden');
    requestAnimationFrame(() => { box.classList.remove('scale-95'); });
}

function cerrarModalConfirm() {
    const modal = document.getElementById('confirm-modal');
    const box = document.getElementById('confirm-box');
    box.classList.add('scale-95');
    setTimeout(() => modal.classList.add('hidden'), 200);
    onConfirmCallback = null;
}

document.getElementById('btn-modal-ejecutar').onclick = function() {
    if(onConfirmCallback) onConfirmCallback();
    cerrarModalConfirm();
};

const localImagesBase64 = {};
let currentCropper = null;
let currentCropId = null;

function openCropper(imgId, event) {
    if (!CAN_GENERATE) return;
    event.stopPropagation();
    currentCropId = imgId;
    const modal = document.getElementById('crop-modal');
    const imgNode = document.getElementById('crop-image');
    const loader = document.getElementById('crop-loader');

    if (currentCropper) { currentCropper.destroy(); currentCropper = null; }
    imgNode.classList.remove('ready'); imgNode.removeAttribute('src');
    loader.classList.remove('hidden'); modal.classList.remove('hidden');

    imgNode.onload = () => {
        currentCropper = new Cropper(imgNode, {
            aspectRatio: 4 / 3, viewMode: 1, dragMode: 'move', background: true, autoCropArea: 0.9, zoomable: true,
            ready: function() { loader.classList.add('hidden'); imgNode.classList.add('ready'); }
        });
    };
    imgNode.onerror = () => { loader.classList.add('hidden'); mostrarAlerta('Error cargando previsualización.', 'error'); closeCropper(); };

    if (localImagesBase64[imgId]) { imgNode.removeAttribute('crossOrigin'); imgNode.src = localImagesBase64[imgId]; }
    else { imgNode.crossOrigin = 'anonymous'; imgNode.src = document.getElementById(`img-node-${imgId}`).getAttribute('data-original-src') || document.getElementById(`img-node-${imgId}`).src; }
}

function rotateCropper() { if (currentCropper) currentCropper.rotate(90); }

function revertirOriginal() {
    if (!currentCropId) return;
    if (localImagesBase64[currentCropId]) delete localImagesBase64[currentCropId];
    const imgNode = document.getElementById(`img-node-${currentCropId}`);
    const originalSrc = imgNode.getAttribute('data-original-src');
    if(originalSrc) imgNode.src = originalSrc;
    closeCropper(); mostrarAlerta("La foto regresó a su estado original.", "info");
}

function saveCrop() {
    if(!currentCropper) return;
    const canvas = currentCropper.getCroppedCanvas({ width: 500, height: 375 });
    const base64 = canvas.toDataURL('image/jpeg', 0.3);
    localImagesBase64[currentCropId] = base64;
    document.getElementById(`img-node-${currentCropId}`).src = base64;
    closeCropper(); mostrarAlerta("Ajustes guardados correctamente.", "exito");
}

function closeCropper() { if(currentCropper) { currentCropper.destroy(); currentCropper = null; } document.getElementById('crop-modal').classList.add('hidden'); }

async function comprimirImagen(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onerror = () => reject(new Error('No se pudo leer la fotografía seleccionada.'));
        reader.onload = event => {
            const img = new Image();
            img.onerror = () => reject(new Error('El archivo seleccionado no contiene una imagen válida.'));
            img.onload = () => {
                const canvas = document.createElement('canvas'); const MAX_WIDTH = 600; const MAX_HEIGHT = 450;
                let width = img.width; let height = img.height;
                if (width > height) { if (width > MAX_WIDTH) { height *= MAX_WIDTH / width; width = MAX_WIDTH; } }
                else { if (height > MAX_HEIGHT) { width *= MAX_HEIGHT / height; height = MAX_HEIGHT; } }
                canvas.width = Math.max(1, Math.round(width));
                canvas.height = Math.max(1, Math.round(height));
                const ctx = canvas.getContext('2d');
                if (!ctx) {
                    reject(new Error('El navegador no pudo preparar la fotografía.'));
                    return;
                }
                ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
                canvas.toBlob((blob) => {
                    if (blob) resolve(blob);
                    else reject(new Error('No se pudo optimizar la fotografía.'));
                }, 'image/jpeg', 0.55);
            };
            img.src = event.target.result;
        };
        reader.readAsDataURL(file);
    });
}

function blobToDataUrl(blob) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onerror = () => reject(new Error('No se pudo preparar la fotografía optimizada.'));
        reader.onload = () => resolve(reader.result);
        reader.readAsDataURL(blob);
    });
}

async function subirLocal(event) {
    if (!CAN_GENERATE) return;
    const files = event.target.files; if (!files.length) return;
    mostrarAlerta('Optimizando imágenes...', 'info');

    try {
        for(let i=0; i<files.length; i++) {
            const file = files[i];
            if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
                throw new Error(`“${file.name}” no es una imagen JPG, PNG o WebP válida.`);
            }
            const blobComprimido = await comprimirImagen(file);
            const dataUrl = await blobToDataUrl(blobComprimido);
            const localId = 'local_' + Date.now() + Math.floor(Math.random() * 1000);
            localImagesBase64[localId] = dataUrl;
            const div = createPhotoCard(localId, dataUrl, IS_2026);

            if (IS_2026) {
                div.addEventListener('click', () => toggleSelect2026(localId));
                const gallery = document.getElementById('gallery-container'); document.getElementById('empty-state').classList.add('hidden'); gallery.classList.remove('hidden'); gallery.insertBefore(div, gallery.firstChild);
            } else {
                div.dataset.proceso = 'FOTOS LOCALES';
                div.addEventListener('click', () => toggleSelect2025(div));
                document.getElementById('local-gallery-2025').classList.remove('hidden'); document.getElementById('local-gallery-grid-2025').insertBefore(div, document.getElementById('local-gallery-grid-2025').firstChild);
            }
        }
        mostrarAlerta('Imágenes listas.', 'exito');
    } catch (error) {
        mostrarAlerta(error.message || 'No se pudieron procesar las imágenes.', 'error');
    } finally {
        event.target.value = '';
    }
}

async function sincronizarDrive() {
    if(!IS_2026) { mostrarAlerta('Sincronizando carpetas con Drive...', 'info'); setTimeout(() => window.location.reload(), 1000); return; }
    const icon = document.getElementById('sync-icon'); icon.classList.add('animate-spin');
    try {
        const res = await fetch('/reporte/api/fotos/' + window.ReporteConfig.otItem, {
            credentials: 'same-origin',
            headers: {
                Accept: 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
            },
        });
        const data = await readApiJson(res, 'No se pudo sincronizar Google Drive.');
        if(data.success) {
            const gallery = document.getElementById('gallery-container'); const emptyState = document.getElementById('empty-state'); let nuevas = 0;
            data.fotos.forEach(img => {
                const imageId = String(img.id ?? '');
                if (!/^[A-Za-z0-9_-]+$/.test(imageId)) return;
                const alreadyExists = Array.from(document.querySelectorAll('[data-id]'))
                    .some(element => element.dataset.id === imageId);
                if(!alreadyExists) {
                    nuevas++; if(emptyState) emptyState.classList.add('hidden'); if(gallery) gallery.classList.remove('hidden');
                    const div = createPhotoCard(imageId, img.thumbnail, true);
                    div.addEventListener('click', () => toggleSelect2026(imageId));
                    gallery.insertBefore(div, gallery.firstChild);
                }
            });
            if(nuevas > 0) mostrarAlerta(`Sincronización completa. ${nuevas} fotos nuevas.`, 'exito'); else mostrarAlerta('La galería ya está actualizada con Drive.', 'info');
            updateUI2026();
        } else { mostrarAlerta('Error conectando a Drive.', 'error'); }
    } catch(e) { mostrarAlerta(e.message || 'Error de red al sincronizar.', 'error'); } finally { icon.classList.remove('animate-spin'); }
}

function editFecha() { if (!CAN_GENERATE) return; document.getElementById('fecha-display').classList.add('hidden'); const input = document.getElementById('fecha-input'); input.classList.remove('hidden'); input.focus(); input.select(); }
function saveFecha() { const input = document.getElementById('fecha-input'); const display = document.getElementById('fecha-display'); let newText = input.value.trim(); if(!newText) newText = "-"; display.innerText = newText; document.getElementById(IS_2026 ? 'fecha_custom_input_26' : 'fecha_custom_input_25').value = newText; input.classList.add('hidden'); display.classList.remove('hidden'); }
function editEstructura() { if (!CAN_GENERATE) return; document.getElementById('estructura-display').classList.add('hidden'); const input = document.getElementById('estructura-input'); input.classList.remove('hidden'); input.focus(); input.select(); }
function saveEstructura() { const input = document.getElementById('estructura-input'); const display = document.getElementById('estructura-display'); let newText = input.value.trim(); if(!newText) newText = "Sin descripción"; display.innerText = newText; document.getElementById(IS_2026 ? 'estructura_custom_input_26' : 'estructura_custom_input_25').value = newText; input.classList.add('hidden'); display.classList.remove('hidden'); }

let processes = [ { id: 'proc-' + Date.now(), name: 'nuevoproceso', photos: [] } ]; let activeProcId = processes[0].id;

let draggedProcId = null;

function dragTabStart(e, id) { if (!CAN_GENERATE) return; draggedProcId = id; e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', id); setTimeout(() => { e.target.classList.add('opacity-40', 'scale-95'); }, 0); }
function dragTabOver(e) { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; }
function dragTabEnter(e, el) { e.preventDefault(); el.classList.add('mx-4', 'scale-105'); }
function dragTabLeave(e, el) { el.classList.remove('mx-4', 'scale-105'); }
function dragTabDrop(e, targetId, el) {
    if (!CAN_GENERATE) return;
    e.preventDefault();
    el.classList.remove('mx-4', 'scale-105');
    if (draggedProcId && draggedProcId !== targetId) {
        const fromIdx = processes.findIndex(p => p.id === draggedProcId);
        const toIdx = processes.findIndex(p => p.id === targetId);
        if (fromIdx > -1 && toIdx > -1) {
            const [moved] = processes.splice(fromIdx, 1);
            processes.splice(toIdx, 0, moved);
            updateUI2026();
        }
    }
}
function dragTabEnd(e, el) { el.classList.remove('opacity-40', 'scale-95'); draggedProcId = null; }

function renderTabs() {
    if(!IS_2026 || !CAN_GENERATE) return; const container = document.getElementById('tabs-container'); if (!container) return; let html = '';
    processes.forEach((p, index) => {
        const isActive = p.id === activeProcId;
        const btnClass = isActive ? 'bg-slate-800 text-white shadow-md border-transparent' : 'bg-white text-slate-500 hover:bg-slate-50 border-slate-200';
        const nextProcId = (index + 1 < processes.length) ? processes[index + 1].id : 'null';

        html += `
            <div class="relative group flex items-center transition-all cursor-grab active:cursor-grabbing"
                 draggable="true"
                 ondragstart="dragTabStart(event, '${p.id}')"
                 ondragover="dragTabOver(event)"
                 ondragenter="dragTabEnter(event, this)"
                 ondragleave="dragTabLeave(event, this)"
                 ondrop="dragTabDrop(event, '${p.id}', this)"
                 ondragend="dragTabEnd(event, this)">
                 
                <div class="px-4 py-1.5 rounded-lg text-[12px] font-bold whitespace-nowrap transition-all border ${btnClass} flex items-center gap-2 pointer-events-none" onclick="setActiveProc('${p.id}')">
                    <span id="proc-name-${p.id}" class="select-none uppercase tracking-wide pointer-events-auto cursor-pointer" onclick="event.stopPropagation(); setActiveProc('${p.id}')" ondblclick="editProcName('${p.id}'); event.stopPropagation();" title="Doble clic para renombrar">${escapeHtml(p.name)}</span>
                    <input type="text" id="proc-input-${p.id}" class="hidden text-slate-900 bg-white border border-blue-400 rounded-md px-2 py-0.5 text-[11px] outline-none font-bold shadow-inner uppercase pointer-events-auto" style="width: ${Math.max(p.name.length * 8, 100)}px;" value="${escapeHtml(p.name)}" onblur="saveProcName('${p.id}')" onkeydown="handleInputKeydown(event, '${p.id}', '${nextProcId}')" onclick="event.stopPropagation()">
                    <button type="button" class="flex items-center justify-center opacity-50 hover:opacity-100 hover:text-red-500 transition-opacity ml-1 pointer-events-auto cursor-pointer" onclick="deleteProc('${p.id}'); event.stopPropagation();"><span class="material-symbols-rounded text-[14px]">close</span></button>
                </div>
            </div>
        `;
    });
    html += `<button type="button" onclick="addProc()" class="w-8 h-8 flex items-center justify-center rounded-lg bg-white text-slate-600 hover:bg-slate-100 border border-slate-200 transition-all ml-1 shadow-sm flex-shrink-0"><span class="material-symbols-rounded text-[20px]">add</span></button>`;
    container.innerHTML = html;
}

function addProc() { if (!CAN_GENERATE) return; const newId = 'proc-' + Date.now(); processes.push({ id: newId, name: 'nuevoproceso', photos: [] }); activeProcId = newId; updateUI2026(); }
function setActiveProc(id) { if (document.getElementById('proc-input-' + id) && !document.getElementById('proc-input-' + id).classList.contains('hidden')) return; activeProcId = id; updateUI2026(); }
function editProcName(id) { if (!CAN_GENERATE) return; document.getElementById('proc-name-' + id).classList.add('hidden'); const input = document.getElementById('proc-input-' + id); input.classList.remove('hidden'); input.focus(); input.select(); }
function saveProcName(id) { const input = document.getElementById('proc-input-' + id); if (!input || input.classList.contains('hidden')) return; let newName = input.value.trim(); if (!newName) newName = 'nuevoproceso'; const p = processes.find(x => x.id === id); if (p) p.name = newName; updateUI2026(); }

function handleInputKeydown(event, currentId, nextProcId) {
    if (event.key === 'Enter') { event.preventDefault(); event.target.blur(); }
    else if (event.key === 'Tab') {
        event.preventDefault(); const input = event.target; let newName = input.value.trim() || 'nuevoproceso';
        const p = processes.find(x => x.id === currentId); if (p) p.name = newName;
        if (nextProcId !== 'null') { activeProcId = nextProcId; updateUI2026(); setTimeout(() => { editProcName(nextProcId); }, 50); }
        else { const newId = 'proc-' + Date.now(); processes.push({ id: newId, name: 'nuevoproceso', photos: [] }); activeProcId = newId; updateUI2026(); setTimeout(() => { editProcName(newId); }, 50); }
    }
}

function deleteProc(id) {
    if (!CAN_GENERATE) return;
    if(processes.length === 1) { mostrarAlerta("Debe existir al menos una fase.", "error"); return; }
    solicitarConfirmacion('¿Deseas remover esta fase? Sus fotos se liberarán.', () => {
        processes = processes.filter(p => p.id !== id); if(activeProcId === id) activeProcId = processes[0].id;
        updateUI2026(); mostrarAlerta("Fase removida.", "info");
    });
}

function toggleSelect2026(imgId) {
    if (!CAN_GENERATE) return;
    let owningProc = null; processes.forEach(p => { if (p.photos.includes(imgId)) owningProc = p; });
    if (owningProc && owningProc.id !== activeProcId) return;
    const activeProc = processes.find(p => p.id === activeProcId); const idx = activeProc.photos.indexOf(imgId);
    if (idx === -1) activeProc.photos.push(imgId); else activeProc.photos.splice(idx, 1); updateUI2026();
}

function updateUI2026() {
    if(!IS_2026) return;
    if (!CAN_GENERATE) {
        document.getElementById('count-display').innerText = document.querySelectorAll('.photo-item').length;
        return;
    }
    renderTabs(); let totalSelected = 0; const activeProc = processes.find(p => p.id === activeProcId);
    document.querySelectorAll('.photo-item').forEach(el => {
        const imgId = el.getAttribute('data-id'); const border = document.getElementById('border-' + imgId); const badge = document.getElementById('badge-' + imgId);
        let owningProc = null; processes.forEach(p => { if (p.photos.includes(imgId)) owningProc = p; });
        if (owningProc) totalSelected++;
        if (owningProc && owningProc.id === activeProcId) { el.classList.remove('opacity-30', 'grayscale', 'cursor-not-allowed'); border.classList.add('border-selected'); badge.classList.remove('hidden'); badge.innerText = activeProc.photos.indexOf(imgId) + 1; badge.classList.remove('badge-anim'); void badge.offsetWidth; badge.classList.add('badge-anim'); }
        else if (owningProc && owningProc.id !== activeProcId) { border.classList.remove('border-selected'); badge.classList.add('hidden'); el.classList.add('opacity-30', 'grayscale', 'cursor-not-allowed'); }
        else { border.classList.remove('border-selected'); badge.classList.add('hidden'); el.classList.remove('opacity-30', 'grayscale', 'cursor-not-allowed'); }
    });
    document.getElementById('count-display').innerText = totalSelected;
}

function toggleSelect2025(el) {
    if (!CAN_GENERATE) return;
    const border = el.querySelector('.border-overlay'); const badge = el.querySelector('.badge-overlay');
    if (el.classList.contains('selected')) { el.classList.remove('selected'); border.classList.remove('border-selected'); badge.classList.add('hidden'); }
    else { el.classList.add('selected'); border.classList.add('border-selected'); badge.classList.remove('hidden'); badge.classList.remove('badge-anim'); void badge.offsetWidth; badge.classList.add('badge-anim'); }
    const total = document.querySelectorAll('.photo-item-25.selected').length; document.getElementById('count-display').innerText = total;
}

function limpiarTodoClick() {
    if (!CAN_GENERATE) return;
    solicitarConfirmacion('¿Deseas limpiar todas las fotos?', () => {
        if (IS_2026) { processes.forEach(p => p.photos = []); updateUI2026(); }
        else { document.querySelectorAll('.photo-item-25.selected').forEach(el => { el.classList.remove('selected'); el.querySelector('.border-overlay').classList.remove('border-selected'); el.querySelector('.badge-overlay').classList.add('hidden'); }); document.getElementById('count-display').innerText = '0'; }
        mostrarAlerta("Selección limpiada.", "info");
    });
}

function abrirReporte(e) {
    if (e) e.preventDefault();
    if (!CAN_GENERATE) return;

    let hasPhotos = false;
    if (IS_2026) { processes.forEach(p => { if(p.photos.length > 0) hasPhotos = true; }); }
    else { if(document.querySelectorAll('.photo-item-25.selected').length > 0) hasPhotos = true; }

    if (!hasPhotos) { mostrarAlerta("Selecciona al menos una foto.", "error"); return; }

    const btnGenerar = e ? e.currentTarget : document.getElementById('btn-generar');
    if (btnGenerar) {
        btnGenerar.classList.add('pointer-events-none', 'opacity-50');
    }

    const pdfWindow = window.open('', '_blank');
    if (!pdfWindow) {
        if (btnGenerar) btnGenerar.classList.remove('pointer-events-none', 'opacity-50');
        mostrarAlerta('El navegador bloqueó la ventana del reporte. Habilita las ventanas emergentes.', 'error');
        return;
    }
    pdfWindow.document.open();
    pdfWindow.document.write(`
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <title>Generando archivo PDF...</title>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');
            * { box-sizing: border-box; }
            body { 
                font-family: 'Inter', system-ui, -apple-system, sans-serif; 
                background-color: #f4f7fb; 
                display: flex; align-items: center; justify-content: center; 
                height: 100vh; margin: 0; padding: 20px;
            }
            .card { 
                background: white; border-radius: 12px; border: 1px solid #e2e8f0; 
                width: 100%; max-width: 580px; box-shadow: 0 10px 25px -5px rgba(0,0,0,0.05);
                display: flex; flex-direction: column;
            }
            .card-content { padding: 35px; }
            .header { display: flex; align-items: flex-start; gap: 18px; margin-bottom: 30px; border-bottom: 1px solid #f1f5f9; padding-bottom: 20px; }
            .pdf-icon-wrapper { flex-shrink: 0; margin-top: 2px; display: flex; align-items: center; justify-content: center; }
            .header-text h2 { margin: 0 0 6px 0; font-size: 1.25rem; font-weight: 800; color: #0f172a; }
            .header-text p { margin: 0; font-size: 0.9rem; color: #64748b; font-weight: 500; }
            .steps-container { position: relative; margin-bottom: 35px; }
            .timeline-bg { position: absolute; left: 11px; top: 10px; bottom: 15px; width: 2px; background: #e2e8f0; z-index: 1; }
            .timeline-progress { position: absolute; left: 11px; top: 10px; height: 0; width: 2px; background: #16a34a; z-index: 2; transition: height 0.6s ease; }
            .step { display: flex; align-items: flex-start; margin-bottom: 24px; position: relative; z-index: 3; }
            .step:last-child { margin-bottom: 0; }
            .icon-container { width: 24px; height: 24px; display: flex; align-items: center; justify-content: center; margin-right: 18px; background: white; }
            .step-content { flex: 1; }
            .step-title { font-weight: 700; color: #1e293b; font-size: 0.95rem; margin-bottom: 3px; }
            .step-subtitle { font-size: 0.8rem; color: #64748b; font-weight: 500; }
            .step-status { text-align: right; min-width: 90px; }
            .status-text { font-size: 0.8rem; font-weight: 700; margin-bottom: 3px; }
            .status-time { font-size: 0.75rem; color: #94a3b8; font-weight: 500; font-variant-numeric: tabular-nums; }
            .text-done { color: #16a34a; } .text-active { color: #2563eb; } .text-pending { color: #94a3b8; } .text-error { color: #dc2626; }
            .icon-done svg { width: 22px; height: 22px; color: #16a34a; background: white; border: 2px solid #16a34a; border-radius: 50%; padding: 3px; }
            .icon-active { width: 20px; height: 20px; border-radius: 50%; border: 2.5px solid #e2e8f0; border-top-color: #2563eb; background: white; animation: spin 1s linear infinite; }
            .icon-pending { width: 20px; height: 20px; border-radius: 50%; border: 2px solid #cbd5e1; background: white; }
            @keyframes spin { to { transform: rotate(360deg); } }
            .progress-section { margin-top: 10px; }
            .progress-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
            .progress-title { font-weight: 800; color: #0f172a; font-size: 0.95rem; }
            .progress-pct { font-weight: 800; color: #0f172a; font-size: 0.95rem; }
            .progress-bar-bg { width: 100%; height: 6px; background-color: #e2e8f0; border-radius: 999px; overflow: hidden; }
            .progress-bar-fill { height: 100%; background-color: #2563eb; width: 0%; transition: width 0.3s ease-out; }
            .card-footer { background: #f8fafc; padding: 18px 35px; border-top: 1px solid #f1f5f9; border-bottom-left-radius: 12px; border-bottom-right-radius: 12px; display: flex; align-items: center; gap: 10px; color: #64748b; font-size: 0.82rem; font-weight: 500; }
            .card-footer svg { width: 16px; height: 16px; opacity: 0.7; }
        </style>
    </head>
    <body>
        <div class="card">
            <div class="card-content">
                <div class="header">
                    <div class="pdf-icon-wrapper">
                        <svg viewBox="0 0 24 24" width="38" height="38">
                            <path fill="#ef4444" d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z"/>
                            <path fill="#b91c1c" d="M14 2v6h6"/>
                            <text x="5.5" y="16.5" font-family="'Inter', sans-serif" font-weight="900" font-size="6.5" fill="#ffffff" letter-spacing="-0.2">PDF</text>
                        </svg>
                    </div>
                    <div class="header-text">
                        <h2>Generando archivo PDF</h2>
                        <p>Estamos preparando tu archivo. Este proceso puede tardar unos segundos.</p>
                    </div>
                </div>
                
                <div class="steps-container">
                    <div class="timeline-bg"></div>
                    <div class="timeline-progress" id="line-progress"></div>
                    
                    <div class="step" id="step1">
                        <div class="icon-container"></div>
                        <div class="step-content">
                            <div class="step-title">Preparando información</div>
                            <div class="step-subtitle">Obteniendo datos del sistema</div>
                        </div>
                        <div class="step-status">
                            <div class="status-text"></div>
                            <div class="status-time"></div>
                        </div>
                    </div>
                    
                    <div class="step" id="step2">
                        <div class="icon-container"></div>
                        <div class="step-content">
                            <div class="step-title">Procesando fotografías</div>
                            <div class="step-subtitle">Optimizando y organizando imágenes</div>
                        </div>
                        <div class="step-status">
                            <div class="status-text"></div>
                            <div class="status-time"></div>
                        </div>
                    </div>
                    
                    <div class="step" id="step3">
                        <div class="icon-container"></div>
                        <div class="step-content">
                            <div class="step-title">Generando páginas</div>
                            <div class="step-subtitle">Armando el contenido del documento</div>
                        </div>
                        <div class="step-status">
                            <div class="status-text"></div>
                            <div class="status-time"></div>
                        </div>
                    </div>
                    
                    <div class="step" id="step4">
                        <div class="icon-container"></div>
                        <div class="step-content">
                            <div class="step-title">Creando archivo PDF</div>
                            <div class="step-subtitle">Finalizando y generando el archivo</div>
                        </div>
                        <div class="step-status">
                            <div class="status-text"></div>
                            <div class="status-time"></div>
                        </div>
                    </div>
                </div>
                
                <div class="progress-section">
                    <div class="progress-header">
                        <span class="progress-title">Progreso total</span>
                        <span class="progress-pct" id="pct">0%</span>
                    </div>
                    <div class="progress-bar-bg">
                        <div class="progress-bar-fill" id="bar"></div>
                    </div>
                </div>
            </div>
            
            <div class="card-footer">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
                    <path d="M9 12l2 2 4-4"></path>
                </svg>
                <span>Tu archivo se está generando. No cierres esta ventana.</span>
            </div>
        </div>
        
        <script>
            let p = 0;
            let currentStep = 1;
            let isFinished = false;
            const bar = document.getElementById('bar');
            const pct = document.getElementById('pct');
            const lineProgress = document.getElementById('line-progress');
            
            function getTime() {
                const now = new Date();
                return now.getHours().toString().padStart(2, '0') + ':' +
                       now.getMinutes().toString().padStart(2, '0') + ':' +
                       now.getSeconds().toString().padStart(2, '0');
            }
            
            function setStepState(stepNum, state) {
                const step = document.getElementById('step' + stepNum);
                const iconContainer = step.querySelector('.icon-container');
                const statusText = step.querySelector('.status-text');
                const statusTime = step.querySelector('.status-time');
                
                if (state === 'done') {
                    iconContainer.innerHTML = '<span class="icon-done"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg></span>';
                    statusText.innerText = 'Completado';
                    statusText.className = 'status-text text-done';
                    if (!statusTime.innerText || statusTime.innerText === '--:--:--') {
                        statusTime.innerText = getTime();
                    }
                    if (stepNum === 1) lineProgress.style.height = '33%';
                    if (stepNum === 2) lineProgress.style.height = '66%';
                    if (stepNum === 3) lineProgress.style.height = '100%';
                } else if (state === 'active') {
                    iconContainer.innerHTML = '<div class="icon-active"></div>';
                    statusText.innerText = 'En progreso';
                    statusText.className = 'status-text text-active';
                    statusTime.innerText = getTime();
                } else if (state === 'error') {
                    iconContainer.innerHTML = '<span style="display:grid;width:22px;height:22px;place-items:center;border:2px solid #dc2626;border-radius:50%;color:#dc2626;font-weight:900;background:white">!</span>';
                    statusText.innerText = 'Error';
                    statusText.className = 'status-text text-error';
                    statusTime.innerText = getTime();
                } else {
                    iconContainer.innerHTML = '<div class="icon-pending"></div>';
                    statusText.innerText = 'Pendiente';
                    statusText.className = 'status-text text-pending';
                    statusTime.innerText = '--:--:--';
                }
            }
            
            setStepState(1, 'active');
            setStepState(2, 'pending');
            setStepState(3, 'pending');
            setStepState(4, 'pending');

            function animarProgreso() {
                if (isFinished) return;
                let increment = (100 - p) * 0.12; 
                if (increment < 0.1) increment = 0.1;
                
                p += increment;
                if (p > 99) p = 99; 
                
                let displayP = Math.floor(p);
                bar.style.width = displayP + '%';
                pct.innerText = displayP + '%';

                if(displayP >= 15 && currentStep === 1) { 
                    setStepState(1, 'done'); setStepState(2, 'active'); currentStep = 2; 
                }
                if(displayP >= 45 && currentStep === 2) { 
                    setStepState(2, 'done'); setStepState(3, 'active'); currentStep = 3; 
                }
                if(displayP >= 80 && currentStep === 3) { 
                    setStepState(3, 'done'); setStepState(4, 'active'); currentStep = 4; 
                }
                
                if (p < 99) { setTimeout(animarProgreso, 250); }
            }
            setTimeout(animarProgreso, 100);

            window.addEventListener('message', (event) => {
                if (event.source !== window.opener || event.origin !== window.location.origin) return;
                if (event.data.type === 'DONE') {
                    isFinished = true;
                    bar.style.width = '100%';
                    pct.innerText = '100%';
                    
                    setStepState(1, 'done');
                    setStepState(2, 'done');
                    setStepState(3, 'done');
                    setStepState(4, 'done');

                    setTimeout(() => {
                        document.open();
                        document.write(event.data.html);
                        document.close();
                    }, 800);
                } else if (event.data.type === 'ERROR') {
                    isFinished = true;
                    setStepState(currentStep, 'error');
                    bar.style.backgroundColor = '#dc2626';
                    pct.innerText = 'Error';
                    document.querySelector('.header-text h2').innerText = 'No se pudo generar el PDF';
                    const msgContainer = document.querySelector('.card-footer span');
                    msgContainer.innerText = "Error: " + event.data.message;
                    msgContainer.style.color = "#ef4444";
                }
            });
        <\/script>
    </body>
    </html>
    `);
    pdfWindow.document.close();

    const formData = new FormData();
    formData.append('csrf_token', window.ReporteConfig.csrfToken);
    formData.append('ot_id', document.getElementById(IS_2026 ? 'ot_id_input_26' : 'ot_id_input_25').value);
    formData.append('estructura_custom', document.getElementById(IS_2026 ? 'estructura_custom_input_26' : 'estructura_custom_input_25').value);
    formData.append('fecha_custom', document.getElementById(IS_2026 ? 'fecha_custom_input_26' : 'fecha_custom_input_25').value);

    if (IS_2026) {
        processes.forEach(p => {
            if (p.photos.length > 0) {
                p.photos.forEach(imgId => {
                    formData.append('selected_images', `${p.name}::${imgId}::${p.name}`);
                    if(localImagesBase64[imgId]) formData.append(`b64_${imgId}`, localImagesBase64[imgId]);
                });
            }
        });
    } else {
        document.querySelectorAll('.photo-item-25.selected').forEach(el => {
            const imgId = el.getAttribute('data-id');
            const pName = el.getAttribute('data-proceso');
            formData.append('selected_images', `${pName}::${imgId}::${pName}`);
            if(localImagesBase64[imgId]) formData.append(`b64_${imgId}`, localImagesBase64[imgId]);
        });
    }

    const reportController = new AbortController();
    const reportTimeout = window.setTimeout(
        () => reportController.abort(),
        REPORT_REQUEST_TIMEOUT_MS,
    );

    fetch(window.ReporteConfig.urlGenerarPdf, {
        method: 'POST',
        body: formData,
        credentials: 'same-origin',
        headers: {
            Accept: 'text/html, application/json',
            'X-Requested-With': 'XMLHttpRequest',
        },
        signal: reportController.signal,
    })
        .then(readReportHtml)
        .then(htmlStr => {
            if (!pdfWindow.closed) {
                pdfWindow.postMessage({ type: 'DONE', html: htmlStr }, window.location.origin);
            }
        })
        .catch(error => {
            const message = error.name === 'AbortError'
                ? 'La generación superó los 4 minutos. Reduce la cantidad de fotografías e inténtalo nuevamente.'
                : (error.message || 'No se pudo generar el reporte.');
            if (!pdfWindow.closed) {
                pdfWindow.postMessage({ type: 'ERROR', message }, window.location.origin);
            }
            mostrarAlerta(message, 'error');
        })
        .finally(() => {
            window.clearTimeout(reportTimeout);
            if (btnGenerar) {
                btnGenerar.classList.remove('pointer-events-none', 'opacity-50');
            }
        });
}

window.onload = () => { if (IS_2026) updateUI2026(); };
