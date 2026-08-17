(() => {
    'use strict';

    const config = window.TrackingConfig || {};
    const categoryMeta = {
        planos: {
            view: 'plans',
            title: 'Planos',
            singular: 'plano',
            listId: 'tracking-plans-list',
            countId: 'tracking-plans-tab-count',
        },
        otros: {
            view: 'documents',
            title: 'Otros documentos',
            singular: 'documento',
            listId: 'tracking-documents-list',
            countId: 'tracking-documents-tab-count',
        },
    };

    let selectedDocuments = { planos: null, otros: null };
    let activeManagerCategory = null;
    let candidateFiles = [];
    let selectedCandidateId = null;
    let lastFocusedElement = null;

    function createElement(tagName, className = '', text = null) {
        const node = document.createElement(tagName);
        if (className) node.className = className;
        if (text !== null) node.textContent = String(text);
        return node;
    }

    function setText(id, value) {
        const node = document.getElementById(id);
        if (node) node.textContent = String(value);
    }

    function responseStatusMessage(status, fallback) {
        const messages = {
            401: 'Tu sesión venció. Inicia sesión nuevamente y vuelve a intentarlo.',
            403: 'No tienes permiso para realizar esta operación.',
            404: 'No se encontró la información solicitada.',
            413: 'El archivo supera el tamaño permitido por el servidor.',
            429: 'Se realizaron demasiadas solicitudes. Espera un momento.',
            500: 'El servidor no pudo completar la operación.',
            502: 'Google Drive no respondió correctamente.',
            503: 'El servicio no está disponible en este momento.',
            504: 'La operación tardó demasiado y fue interrumpida.',
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

    function replaceCategory(urlTemplate, category) {
        return String(urlTemplate || '').replace('__CATEGORY__', category);
    }

    function formatSize(value) {
        const size = Number(value);
        if (!Number.isFinite(size) || size < 0) return '—';
        if (size < 1024) return `${size} B`;
        if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
        return `${(size / (1024 * 1024)).toFixed(1)} MB`;
    }

    function formatDate(value) {
        if (!value) return 'Sin fecha';
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return 'Sin fecha';
        return new Intl.DateTimeFormat('es-PE', {
            day: '2-digit',
            month: '2-digit',
            year: 'numeric',
        }).format(date);
    }

    function fileTypeLabel(documentData) {
        const name = String(documentData?.name || '');
        const mimeType = String(documentData?.mime_type || '').toLowerCase();
        const extension = name.includes('.')
            ? name.split('.').pop().toUpperCase()
            : '';
        if (mimeType === 'application/pdf' || extension === 'PDF') return 'PDF';
        if (extension) return extension.slice(0, 8);
        return 'ARCHIVO';
    }

    function displayFileName(documentData) {
        const name = String(documentData?.name || 'Documento').trim() || 'Documento';
        const type = fileTypeLabel(documentData);
        if (type === 'PDF' && name.toLowerCase().endsWith('.pdf')) {
            return name.slice(0, -4) || 'Documento';
        }
        return name;
    }

    function emptyDocumentState(category) {
        const meta = categoryMeta[category];
        const wrapper = createElement('div', 'tracking-document-empty');
        wrapper.append(
            createElement(
                'strong',
                '',
                config.canManageDocuments
                    ? `Aún no hay un ${meta.singular} publicado`
                    : `No hay un ${meta.singular} publicado`,
            ),
            createElement(
                'p',
                '',
                config.canManageDocuments
                    ? `Usa Gestionar para publicar el archivo que se mostrará en ${meta.title}.`
                    : 'El archivo aparecerá aquí cuando sea publicado.',
            ),
        );
        return wrapper;
    }

    function openDocument(documentData) {
        if (!documentData) return;
        if (!documentData.previewable || !documentData.preview_url) {
            if (documentData.download_url) window.location.assign(documentData.download_url);
            return;
        }

        const backdrop = document.getElementById('tracking-document-viewer-backdrop');
        const frame = document.getElementById('tracking-document-frame');
        const download = document.getElementById('tracking-document-download');
        const dialog = backdrop?.querySelector('.tracking-document-viewer');
        if (!backdrop || !frame || !download || !dialog) return;

        lastFocusedElement = document.activeElement;
        setText('tracking-document-viewer-title', documentData.name || 'Documento');
        download.href = documentData.download_url || '#';
        frame.src = documentData.preview_url;
        backdrop.hidden = false;
        document.body.classList.add('tracking-document-modal-open');
        window.requestAnimationFrame(() => dialog.focus());
    }

    function closeDocumentViewer() {
        const backdrop = document.getElementById('tracking-document-viewer-backdrop');
        const frame = document.getElementById('tracking-document-frame');
        if (!backdrop || !frame) return;
        backdrop.hidden = true;
        frame.src = 'about:blank';
        document.body.classList.remove('tracking-document-modal-open');
        if (lastFocusedElement instanceof HTMLElement) lastFocusedElement.focus();
    }

    function updateManageButton(category) {
        const button = document.querySelector(
            `[data-open-document-manager="${category}"]`,
        );
        if (!button) return;
        button.textContent = category === 'planos'
            ? 'Gestionar plano'
            : 'Gestionar documentos';
    }

    function renderDocument(category, documentData) {
        const meta = categoryMeta[category];
        const container = document.getElementById(meta.listId);
        if (!container) return;
        container.replaceChildren();
        setText(meta.countId, documentData ? 1 : 0);
        updateManageButton(category);

        if (!documentData) {
            container.append(emptyDocumentState(category));
            return;
        }

        const typeLabel = fileTypeLabel(documentData);
        const displayName = displayFileName(documentData);
        const card = createElement('button', 'tracking-document-card');
        card.type = 'button';
        card.dataset.documentCategory = category;
        card.setAttribute(
            'aria-label',
            `${displayName}. ${documentData.previewable ? 'Abrir vista previa' : 'Descargar archivo'}.`,
        );

        const badge = createElement(
            'span',
            `tracking-document-type${typeLabel === 'PDF' ? ' is-pdf' : ''}`,
            typeLabel,
        );
        const copy = createElement('span', 'tracking-document-copy');
        copy.append(
            createElement('strong', '', displayName),
            createElement(
                'small',
                '',
                `${typeLabel} · ${formatSize(documentData.size)}`,
            ),
        );

        card.append(badge, copy);
        card.addEventListener('click', () => openDocument(documentData));
        container.append(card);
    }

    function applyDocuments(payload) {
        const documents = payload && typeof payload === 'object' ? payload : {};
        selectedDocuments = {
            planos: documents.planos || null,
            otros: documents.otros || null,
        };
        renderDocument('planos', selectedDocuments.planos);
        renderDocument('otros', selectedDocuments.otros);
    }

    async function loadDocuments() {
        if (!config.documentsListUrl) return;
        try {
            const response = await fetch(config.documentsListUrl, {
                cache: 'no-store',
                credentials: 'same-origin',
                headers: {
                    Accept: 'application/json',
                    'X-Requested-With': 'XMLHttpRequest',
                },
            });
            const payload = await readApiJson(
                response,
                'No se pudieron cargar los documentos publicados.',
            );
            if (response.ok && payload.success) applyDocuments(payload.documents);
        } catch (error) {
            console.warn('No se pudieron cargar los documentos:', error.message);
        }
    }

    function setManagerState(message, mode = 'loading') {
        const state = document.getElementById('tracking-document-manager-state');
        if (!state) return;
        state.textContent = String(message || '');
        state.dataset.mode = mode;
        state.hidden = false;
    }

    function updateCandidateSelection() {
        document.querySelectorAll('[data-document-candidate-id]').forEach((row) => {
            const selected = row.dataset.documentCandidateId === selectedCandidateId;
            row.classList.toggle('is-selected', selected);
            row.setAttribute('aria-pressed', selected ? 'true' : 'false');
        });

        const selected = candidateFiles.find((item) => item.id === selectedCandidateId);
        const saveButton = document.getElementById('tracking-save-document');
        if (saveButton) saveButton.disabled = !selectedCandidateId;
        setText(
            'tracking-document-selection-note',
            selected ? selected.name : 'Selecciona un archivo de la lista',
        );
    }

    function candidateMatches(fileData, query) {
        if (!query) return true;
        const haystack = [
            fileData.name,
            fileData.location_label,
            fileData.folder_name,
            fileTypeLabel(fileData),
        ].join(' ').toLocaleLowerCase('es');
        return haystack.includes(query);
    }

    function renderCandidateRows() {
        const container = document.getElementById('tracking-document-candidates');
        const state = document.getElementById('tracking-document-manager-state');
        const search = document.getElementById('tracking-document-search');
        if (!container) return;

        const query = String(search?.value || '').trim().toLocaleLowerCase('es');
        const visibleFiles = candidateFiles.filter((item) => candidateMatches(item, query));
        container.replaceChildren();
        setText(
            'tracking-document-result-count',
            `${visibleFiles.length} de ${candidateFiles.length}`,
        );

        if (!candidateFiles.length) {
            setManagerState('No hay documentos disponibles en la carpeta de esta OT.', 'empty');
            return;
        }
        if (!visibleFiles.length) {
            setManagerState('No se encontraron archivos con ese nombre.', 'empty');
            return;
        }
        if (state) state.hidden = true;

        visibleFiles.forEach((fileData) => {
            const row = createElement('button', 'tracking-document-candidate');
            row.type = 'button';
            row.dataset.documentCandidateId = fileData.id;
            row.setAttribute('aria-pressed', 'false');

            const fileCell = createElement('span', 'tracking-document-candidate-file');
            const type = createElement(
                'span',
                'tracking-document-type',
                fileTypeLabel(fileData),
            );
            const copy = createElement('span', 'tracking-document-candidate-copy');
            copy.append(
                createElement('strong', '', fileData.name),
                createElement('small', '', `Modificado ${formatDate(fileData.modified_time)}`),
            );
            fileCell.append(type, copy);

            const location = createElement(
                'span',
                'tracking-document-candidate-location',
                fileData.location_label || fileData.folder_name || 'Carpeta de la OT',
            );
            const size = createElement(
                'span',
                'tracking-document-candidate-size',
                formatSize(fileData.size),
            );
            const marker = createElement('i', 'tracking-document-radio');

            row.append(fileCell, location, size, marker);
            row.addEventListener('click', () => {
                selectedCandidateId = fileData.id;
                updateCandidateSelection();
            });
            container.append(row);
        });
        updateCandidateSelection();
    }

    function renderCandidates(files) {
        candidateFiles = Array.isArray(files)
            ? files.filter((item) => item && item.id && item.name)
            : [];
        if (!candidateFiles.some((item) => item.id === selectedCandidateId)) {
            selectedCandidateId = null;
        }
        renderCandidateRows();
    }

    async function openDocumentManager(category) {
        if (!config.canManageDocuments || !categoryMeta[category]) return;
        const backdrop = document.getElementById('tracking-document-manager-backdrop');
        const dialog = document.getElementById('tracking-document-manager');
        const container = document.getElementById('tracking-document-candidates');
        const removeButton = document.getElementById('tracking-remove-document');
        const saveButton = document.getElementById('tracking-save-document');
        const search = document.getElementById('tracking-document-search');
        const uploadInput = document.getElementById('tracking-document-upload');
        if (!backdrop || !dialog || !container) return;

        const meta = categoryMeta[category];
        activeManagerCategory = category;
        selectedCandidateId = selectedDocuments[category]?.drive_file_id || null;
        candidateFiles = [];
        container.replaceChildren();
        if (search) search.value = '';
        if (uploadInput) uploadInput.value = '';
        setText('tracking-document-manager-title', `Seleccionar ${meta.singular}`);
        setText('tracking-document-result-count', '0 de 0');
        setText('tracking-document-selection-note', 'Selecciona un archivo de la lista');
        if (saveButton) saveButton.textContent = `Publicar ${meta.singular}`;
        if (removeButton) {
            removeButton.textContent = `Quitar ${meta.singular} publicado`;
            removeButton.disabled = !selectedDocuments[category];
        }
        setManagerState('Consultando Google Drive…');
        backdrop.hidden = false;
        lastFocusedElement = document.activeElement;
        document.body.classList.add('tracking-document-modal-open');
        window.requestAnimationFrame(() => dialog.focus());

        try {
            const response = await fetch(
                replaceCategory(config.documentCandidatesUrlTemplate, category),
                {
                    cache: 'no-store',
                    credentials: 'same-origin',
                    headers: {
                        Accept: 'application/json',
                        'X-Requested-With': 'XMLHttpRequest',
                    },
                },
            );
            const payload = await readApiJson(
                response,
                'No se pudieron consultar los archivos.',
            );
            if (!response.ok || !payload.success) {
                throw new Error(payload.error || 'No se pudieron consultar los archivos.');
            }
            if (!payload.ot_folder_found) {
                setManagerState('No se encontró la carpeta de esta OT en Google Drive.', 'error');
                return;
            }
            renderCandidates(payload.files);
        } catch (error) {
            setManagerState(error.message || 'No se pudieron consultar los archivos.', 'error');
        }
    }

    async function uploadDocument(input) {
        const file = input?.files?.[0];
        if (!file || !activeManagerCategory || !config.uploadDocumentUrlTemplate) return;

        const uploadLabel = input.closest('.tracking-drive-upload');
        input.disabled = true;
        if (uploadLabel) uploadLabel.dataset.uploading = 'true';
        setManagerState(`Subiendo ${file.name}…`);

        try {
            const formData = new FormData();
            formData.append('file', file);
            const response = await fetch(
                replaceCategory(
                    config.uploadDocumentUrlTemplate,
                    activeManagerCategory,
                ),
                {
                    method: 'POST',
                    credentials: 'same-origin',
                    headers: {
                        Accept: 'application/json',
                        'X-CSRFToken': config.csrfToken || '',
                        'X-Requested-With': 'XMLHttpRequest',
                    },
                    body: formData,
                },
            );
            const payload = await readApiJson(
                response,
                'No se pudo subir el archivo.',
            );
            if (!response.ok || !payload.success || !payload.file?.id) {
                throw new Error(payload.error || 'No se pudo subir el archivo.');
            }

            candidateFiles = [
                payload.file,
                ...candidateFiles.filter((item) => item.id !== payload.file.id),
            ];
            selectedCandidateId = payload.file.id;
            renderCandidateRows();
            setText(
                'tracking-document-selection-note',
                `${payload.file.name} subido. Pulsa Publicar para mostrarlo.`,
            );
        } catch (error) {
            setManagerState(error.message || 'No se pudo subir el archivo.', 'error');
        } finally {
            input.disabled = false;
            input.value = '';
            if (uploadLabel) uploadLabel.dataset.uploading = 'false';
        }
    }

    function closeDocumentManager() {
        const backdrop = document.getElementById('tracking-document-manager-backdrop');
        if (!backdrop) return;
        backdrop.hidden = true;
        activeManagerCategory = null;
        candidateFiles = [];
        selectedCandidateId = null;
        document.body.classList.remove('tracking-document-modal-open');
        if (lastFocusedElement instanceof HTMLElement) lastFocusedElement.focus();
    }

    async function saveManagerSelection(fileId) {
        if (!activeManagerCategory) return;
        const saveButton = document.getElementById('tracking-save-document');
        const removeButton = document.getElementById('tracking-remove-document');
        if (saveButton) saveButton.disabled = true;
        if (removeButton) removeButton.disabled = true;

        try {
            const response = await fetch(
                replaceCategory(config.saveDocumentUrlTemplate, activeManagerCategory),
                {
                    method: 'PUT',
                    credentials: 'same-origin',
                    headers: {
                        Accept: 'application/json',
                        'Content-Type': 'application/json',
                        'X-CSRFToken': config.csrfToken || '',
                        'X-Requested-With': 'XMLHttpRequest',
                    },
                    body: JSON.stringify({ file_id: fileId || null }),
                },
            );
            const payload = await readApiJson(
                response,
                'No se pudo guardar la selección.',
            );
            if (!response.ok || !payload.success) {
                throw new Error(payload.error || 'No se pudo guardar la selección.');
            }

            const category = activeManagerCategory;
            selectedDocuments[category] = payload.document || null;
            renderDocument(category, selectedDocuments[category]);
            closeDocumentManager();
            window.TrackingWorkspace?.select(categoryMeta[category].view);
        } catch (error) {
            setManagerState(error.message || 'No se pudo guardar la selección.', 'error');
            if (saveButton) saveButton.disabled = !selectedCandidateId;
            if (removeButton) {
                removeButton.disabled = !selectedDocuments[activeManagerCategory];
            }
        }
    }

    function setupDocumentManager() {
        document.querySelectorAll('[data-open-document-manager]').forEach((button) => {
            button.addEventListener('click', () => {
                openDocumentManager(button.dataset.openDocumentManager);
            });
        });
        document.querySelectorAll('[data-close-document-manager]').forEach((button) => {
            button.addEventListener('click', closeDocumentManager);
        });

        const backdrop = document.getElementById('tracking-document-manager-backdrop');
        if (backdrop) {
            backdrop.addEventListener('click', (event) => {
                if (event.target === backdrop) closeDocumentManager();
            });
        }

        const search = document.getElementById('tracking-document-search');
        if (search) search.addEventListener('input', renderCandidateRows);

        const uploadInput = document.getElementById('tracking-document-upload');
        if (uploadInput) {
            uploadInput.addEventListener('change', () => uploadDocument(uploadInput));
        }

        const saveButton = document.getElementById('tracking-save-document');
        if (saveButton) {
            saveButton.addEventListener('click', () => saveManagerSelection(selectedCandidateId));
        }
        const removeButton = document.getElementById('tracking-remove-document');
        if (removeButton) {
            removeButton.addEventListener('click', () => saveManagerSelection(null));
        }
    }

    function setupDocumentViewer() {
        document.querySelectorAll('[data-close-document-viewer]').forEach((button) => {
            button.addEventListener('click', closeDocumentViewer);
        });
        const backdrop = document.getElementById('tracking-document-viewer-backdrop');
        if (backdrop) {
            backdrop.addEventListener('click', (event) => {
                if (event.target === backdrop) closeDocumentViewer();
            });
        }
    }

    document.addEventListener('keydown', (event) => {
        if (event.key !== 'Escape') return;
        const viewer = document.getElementById('tracking-document-viewer-backdrop');
        if (viewer && !viewer.hidden) {
            closeDocumentViewer();
            return;
        }
        const manager = document.getElementById('tracking-document-manager-backdrop');
        if (manager && !manager.hidden) closeDocumentManager();
    }, true);

    document.addEventListener('DOMContentLoaded', () => {
        setupDocumentManager();
        setupDocumentViewer();
        loadDocuments();
    });
})();
