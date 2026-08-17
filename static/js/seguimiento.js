(() => {
    'use strict';

    const config = window.TrackingConfig || {};
    const refreshIntervalMs = Math.max(Number(config.refreshIntervalMs || 15000), 10000);
    const currentUserId = String(config.currentUserId || '');
    const initialData = config.initialData && typeof config.initialData === 'object'
        ? config.initialData
        : {};

    const signatures = {
        lots: null,
        personnel: null,
        photos: null,
        manualMessages: null,
        auditEvents: null,
    };

    let refreshInProgress = false;
    let lastFocusedElement = null;
    let currentPersonnel = Array.isArray(initialData.personnel) ? initialData.personnel : [];
    let currentPhotos = Array.isArray(initialData.photos) ? initialData.photos : [];
    let availableTrackingPhotos = [];
    let selectedTrackingPhotoIds = new Set();
    let openPersonIndex = null;
    let openLotId = null;
    let photoPreviewToken = 0;
    const decodedPhotoUrls = new Set();
    const photoDecodePromises = new Map();

    function element(tagName, className = '', text) {
        const node = document.createElement(tagName);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function toArray(value) {
        return Array.isArray(value) ? value : [];
    }

    function toNumber(value) {
        const number = Number(value);
        return Number.isFinite(number) ? number : 0;
    }

    function responseStatusMessage(status, fallback) {
        const messages = {
            401: 'Tu sesión venció. Inicia sesión nuevamente y vuelve a intentarlo.',
            403: 'No tienes permiso para realizar esta operación.',
            404: 'No se encontró la información solicitada.',
            413: 'La selección supera el tamaño permitido por el servidor.',
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

    function clampProgress(value) {
        return Math.min(100, Math.max(0, toNumber(value)));
    }

    function formatProgress(value) {
        return `${clampProgress(value).toFixed(1)}%`;
    }

    function plural(count, singular, pluralForm) {
        return count === 1 ? singular : pluralForm;
    }

    function getInitials(name, fallback = 'US') {
        const initials = String(name || '')
            .trim()
            .split(/\s+/)
            .filter(Boolean)
            .slice(0, 2)
            .map((part) => part.charAt(0).toUpperCase())
            .join('');

        return initials || fallback;
    }


    function dateGroup(value) {
        const text = String(value || '').trim();
        if (!text) return 'Sin fecha';
        return text.split(/\s+/)[0] || 'Sin fecha';
    }

    function appendDateSeparator(fragment, value, previousValue) {
        const group = dateGroup(value);
        if (group === previousValue) return group;
        const separator = element('div', 'tracking-activity-date');
        separator.append(
            element('span', '', group),
            element('i'),
        );
        fragment.append(separator);
        return group;
    }

    function classifyAuditEvent(message) {
        const text = String(message || '').toLocaleLowerCase('es');
        if (text.includes('personal') || text.includes('operario') || text.includes('asignado')) {
            return { className: 'is-personnel', icon: 'person_add', label: 'Personal' };
        }
        if (text.includes('avance') || text.includes('progreso')) {
            return { className: 'is-progress', icon: 'trending_up', label: 'Avance' };
        }
        if (text.includes('estado')) {
            return { className: 'is-status', icon: 'flag', label: 'Estado' };
        }
        if (text.includes('cantidad') || text.includes('unidad')) {
            return { className: 'is-quantity', icon: 'numbers', label: 'Cantidad' };
        }
        if (text.includes('elimin')) {
            return { className: 'is-delete', icon: 'delete', label: 'Eliminación' };
        }
        return { className: 'is-default', icon: 'history', label: 'Cambio' };
    }

    function firstDefined(source, keys, fallback = '') {
        if (!source || typeof source !== 'object') return fallback;

        for (const key of keys) {
            const value = source[key];
            if (value !== undefined && value !== null && String(value).trim() !== '') {
                return value;
            }
        }

        return fallback;
    }

    function setText(id, value) {
        const node = document.getElementById(id);
        if (node) node.textContent = String(value);
    }

    function setProgressWidth(id, value) {
        const node = document.getElementById(id);
        if (node) node.style.width = `${clampProgress(value)}%`;
    }

    function createEmptyState(iconName, title, description, extraClass = '') {
        const empty = element('div', `tracking-empty ${extraClass}`.trim());
        if (iconName) {
            const icon = element('span', 'material-symbols-rounded', iconName);
            icon.setAttribute('aria-hidden', 'true');
            empty.append(icon);
        }
        empty.append(element('strong', '', title), element('p', '', description));
        return empty;
    }

    function updateSummary(data) {
        const overallProgress = clampProgress(data.overall_progress);
        const completedCount = toNumber(data.completed_count);
        const elementCount = toNumber(data.component_count);
        const lotCount = toNumber(data.lot_count);
        const personnelCount = toArray(data.personnel).length;
        const elementProgress = elementCount > 0
            ? (completedCount / elementCount) * 100
            : 0;

        setText('tracking-overall-progress', formatProgress(overallProgress));
        const statusNode = document.getElementById('tracking-overall-status');
        const statusText = overallProgress >= 100 ? 'Completado' : overallProgress > 0 ? 'En proceso' : 'Pendiente';
        setText('tracking-overall-status', statusText);
        if (statusNode) {
            statusNode.classList.toggle('is-complete', overallProgress >= 100);
            statusNode.classList.toggle('is-pending', overallProgress <= 0);
        }
        setText('tracking-completed-summary', completedCount);
        setText('tracking-component-count', elementCount);
        setText('tracking-lot-count', lotCount);
        setText('tracking-personnel-count', personnelCount);
        setText('tracking-photo-count', toArray(data.photos).length);
        setText('tracking-lot-tab-count', lotCount);
        setText('tracking-personnel-tab-count', personnelCount);
        setText('tracking-photo-tab-count', toArray(data.photos).length);
        setText('tracking-completed-count', completedCount);
        setText('tracking-progress-count', toNumber(data.in_progress_count));
        setText('tracking-pending-count', toNumber(data.pending_count));
        setText('tracking-lot-note', `${lotCount} registrado${lotCount === 1 ? '' : 's'}`);
        setText(
            'tracking-personnel-note',
            `${personnelCount} persona${personnelCount === 1 ? '' : 's'} vinculada${personnelCount === 1 ? '' : 's'} a la producción.`,
        );
        setText('tracking-lot-summary-label', `${plural(lotCount, 'Lista', 'Listas')} de producción`);

        setProgressWidth('tracking-overall-bar', overallProgress);
        setProgressWidth('tracking-component-bar', elementProgress);

        const ring = document.getElementById('tracking-overall-ring');
        if (ring) ring.style.setProperty('--progress', String(overallProgress));
    }

    function findProcessCard(key) {
        return Array.from(document.querySelectorAll('[data-process-key]'))
            .find((card) => card.dataset.processKey === String(key || ''));
    }

    function updateProcesses(processes) {
        toArray(processes).forEach((process) => {
            const card = findProcessCard(process.key);
            if (!card) return;

            const progress = clampProgress(process.progress);
            const progressValue = card.querySelector('[data-process-progress]');
            const status = card.querySelector('[data-process-status]');
            const bar = card.querySelector('[data-process-bar]');
            const statusText = String(process.status || 'Sin datos');
            const normalizedStatus = statusText.toLocaleLowerCase('es');
            const isComplete = progress >= 99.95 || normalizedStatus.includes('complet');
            const isPending = progress <= 0 || normalizedStatus.includes('pendiente') || normalizedStatus.includes('sin datos');

            card.classList.toggle('is-complete', isComplete);
            card.classList.toggle('is-pending', !isComplete && isPending);
            card.classList.toggle('is-progress', !isComplete && !isPending);

            if (progressValue) progressValue.textContent = formatProgress(progress);
            if (status) status.textContent = statusText;

            if (bar) {
                bar.setAttribute('aria-valuenow', String(progress));
                const fill = bar.querySelector('span');
                if (fill) fill.style.width = `${progress}%`;
            }
        });
    }

    function formatQuantity(value) {
        const quantity = toNumber(value);
        return Number.isInteger(quantity) ? String(quantity) : quantity.toFixed(1);
    }

    function createProgressBar(progress, label, large = false) {
        const progressBar = element(
            'div',
            `tracking-progress${large ? ' tracking-progress-large' : ''}`,
        );
        progressBar.setAttribute('role', 'progressbar');
        progressBar.setAttribute('aria-label', label);
        progressBar.setAttribute('aria-valuenow', String(progress));
        progressBar.setAttribute('aria-valuemin', '0');
        progressBar.setAttribute('aria-valuemax', '100');
        const fill = element('span');
        fill.style.width = `${progress}%`;
        progressBar.append(fill);
        return progressBar;
    }

    function createLotProcess(process, lotName) {
        const progress = clampProgress(process.progress);
        const article = element('article', 'tracking-lot-process');
        if (!process.active) article.classList.add('is-inactive');
        if (process.status === 'Completado') article.classList.add('is-complete');
        if (process.status === 'En proceso') article.classList.add('is-progress');

        const top = element('div', 'tracking-lot-process-top');
        const copy = element('div');
        copy.append(
            element('strong', '', process.name || 'Proceso'),
            element('span', '', process.status || 'Sin datos'),
        );
        top.append(copy, element('b', '', formatProgress(progress)));

        const applicableCount = toNumber(process.applicable_count);
        let detailText;
        if (!process.active) {
            detailText = 'Proceso no habilitado para esta OT.';
        } else if (!applicableCount) {
            detailText = 'Sin elementos aplicables en este lote.';
        } else {
            detailText = [
                `${formatQuantity(process.advanced_units)} de ${formatQuantity(process.total_units)} unidades`,
                `${toNumber(process.completed_count)} completos`,
                `${toNumber(process.in_progress_count)} en proceso`,
                `${toNumber(process.pending_count)} pendientes`,
            ].join(' · ');
        }

        article.append(
            top,
            createProgressBar(progress, `${process.name || 'Proceso'} en ${lotName}`),
            element('p', '', detailText),
        );
        return article;
    }

    function setLotExpanded(article, expanded) {
        if (!article) return;
        const toggle = article.querySelector('[data-lot-toggle]');
        const detail = article.querySelector('.tracking-lot-detail');
        const label = article.querySelector('[data-lot-toggle-label]');
        article.classList.toggle('is-open', expanded);
        if (toggle) toggle.setAttribute('aria-expanded', expanded ? 'true' : 'false');
        if (detail) detail.hidden = !expanded;
        if (label) label.textContent = expanded ? 'Ocultar detalle' : 'Ver detalle';
    }

    function renderLots(lots) {
        const container = document.getElementById('tracking-lot-list');
        if (!container) return;

        const safeLots = toArray(lots);
        const fragment = document.createDocumentFragment();
        if (openLotId && !safeLots.some((lot) => String(lot.id) === openLotId)) {
            openLotId = null;
        }

        if (!safeLots.length) {
            fragment.append(createEmptyState(
                null,
                'Aún no hay lotes registrados',
                'El avance aparecerá cuando Producción cargue la información de esta OT.',
            ));
        }

        safeLots.forEach((lot) => {
            const lotName = lot.name || 'Lista sin nombre';
            const elementCount = toNumber(lot.component_count);
            const unitCount = toNumber(lot.unit_count);
            const completedCount = toNumber(lot.completed_count);
            const inProgressCount = toNumber(lot.in_progress_count);
            const pendingCount = toNumber(lot.pending_count);
            const progress = clampProgress(lot.progress);
            const lotId = String(lot.id ?? '');
            const detailId = `tracking-lot-detail-${lotId || Math.random().toString(36).slice(2)}`;
            const isOpen = Boolean(lotId) && openLotId === lotId;

            const article = element('article', 'tracking-lot');
            article.dataset.lotId = lotId;
            article.classList.toggle('is-open', isOpen);
            const summary = element('button', 'tracking-lot-summary');
            summary.type = 'button';
            summary.dataset.lotToggle = '';
            summary.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
            summary.setAttribute('aria-controls', detailId);
            const top = element('div', 'tracking-lot-top');
            const name = element('div', 'tracking-lot-name');

            name.append(
                element('h3', '', lotName),
                element(
                    'p',
                    '',
                    `${elementCount} ${plural(elementCount, 'elemento', 'elementos')} · ${unitCount} ${plural(unitCount, 'unidad', 'unidades')}`,
                ),
            );

            const result = element('div', 'tracking-lot-result');
            result.append(
                element('span', 'tracking-status-pill', lot.status || 'Pendiente'),
                element('strong', '', formatProgress(progress)),
            );
            top.append(name, result);

            const foot = element('div', 'tracking-lot-foot');
            foot.append(element(
                'span',
                '',
                `${completedCount} completos · ${inProgressCount} en proceso · ${pendingCount} pendientes`,
            ));
            const disclosure = element('span', 'tracking-lot-disclosure');
            const disclosureLabel = element(
                'span',
                '',
                isOpen ? 'Ocultar detalle' : 'Ver detalle',
            );
            disclosureLabel.dataset.lotToggleLabel = '';
            const chevron = element('i');
            chevron.setAttribute('aria-hidden', 'true');
            disclosure.append(disclosureLabel, chevron);
            foot.append(disclosure);

            summary.append(
                top,
                createProgressBar(progress, `Avance de ${lotName}`, true),
                foot,
            );

            const detail = element('section', 'tracking-lot-detail');
            detail.id = detailId;
            detail.hidden = !isOpen;
            detail.setAttribute('aria-label', `Detalle de ${lotName}`);
            const detailHeading = element('header', 'tracking-lot-detail-heading');
            const detailCopy = element('div');
            detailCopy.append(
                element('strong', '', 'Avance por proceso'),
                element('span', '', 'Las cantidades corresponden únicamente a este lote.'),
            );
            detailHeading.append(detailCopy);
            const processGrid = element('div', 'tracking-lot-process-grid');
            toArray(lot.processes).forEach((process) => {
                processGrid.append(createLotProcess(process, lotName));
            });
            detail.append(detailHeading, processGrid);
            article.append(summary, detail);
            fragment.append(article);
        });

        container.replaceChildren(fragment);
    }

    function setupLotDetails() {
        const container = document.getElementById('tracking-lot-list');
        if (!container) return;
        container.addEventListener('click', (event) => {
            const toggle = event.target.closest('[data-lot-toggle]');
            if (!toggle || !container.contains(toggle)) return;
            const article = toggle.closest('.tracking-lot');
            if (!article) return;
            const shouldOpen = toggle.getAttribute('aria-expanded') !== 'true';
            container.querySelectorAll('.tracking-lot.is-open').forEach((openArticle) => {
                if (openArticle !== article) setLotExpanded(openArticle, false);
            });
            setLotExpanded(article, shouldOpen);
            openLotId = shouldOpen ? article.dataset.lotId : null;
        });
    }

    function personElementSource(person) {
        const candidates = [
            person?.elements,
            person?.elementos,
            person?.assigned_elements,
            person?.assignedElements,
            person?.element_details,
            person?.elementDetails,
            person?.components,
            person?.componentes,
        ];

        return candidates.find(Array.isArray) || [];
    }

    function normalizePersonElement(item) {
        const safeItem = item && typeof item === 'object' ? item : {};
        const code = firstDefined(safeItem, [
            'code', 'codigo', 'código', 'item_code', 'itemCode', 'element_code', 'elementCode', 'codigo_elemento',
        ], 'Sin código');
        const brand = firstDefined(safeItem, [
            'brand', 'marca', 'mark', 'element_brand', 'elementBrand', 'marca_elemento',
        ], '');
        const description = firstDefined(safeItem, [
            'description', 'descripcion', 'descripción', 'name', 'nombre', 'element_name', 'elementName',
        ], 'Sin descripción registrada');
        const lot = firstDefined(safeItem, [
            'lot', 'lote', 'list', 'lista', 'lot_name', 'lotName', 'lista_nombre',
        ], '');
        const processesValue = firstDefined(safeItem, [
            'processes', 'procesos', 'process', 'proceso', 'stages', 'etapas',
        ], '');
        const processes = Array.isArray(processesValue)
            ? processesValue.join(', ')
            : String(processesValue || '');

        return {
            code: String(code),
            brand: String(brand),
            description: String(description),
            lot: String(lot || ''),
            processes,
        };
    }

    function getPersonSearchText(person) {
        const personName = person?.name || '';
        const processes = person?.processes || '';
        const elementText = personElementSource(person)
            .map(normalizePersonElement)
            .map((item) => `${item.code} ${item.brand} ${item.description} ${item.lot} ${item.processes}`)
            .join(' ');

        return `${personName} ${processes} ${elementText}`.toLocaleLowerCase('es');
    }

    function renderPersonnel(personnel) {
        const container = document.getElementById('tracking-person-list');
        if (!container) return;

        const safePersonnel = toArray(personnel);
        currentPersonnel = safePersonnel;
        const fragment = document.createDocumentFragment();

        if (!safePersonnel.length) {
            fragment.append(createEmptyState(
                null,
                'Sin personal asignado',
                'Producción todavía no registró operarios en los elementos.',
                'tracking-empty-personnel',
            ));
        }

        safePersonnel.forEach((person, index) => {
            const personName = person.name || 'Personal sin nombre';
            const processes = person.processes || 'Asignación general';
            const elementCount = toNumber(person.component_count);
            const lotCount = toNumber(person.lot_count);

            const article = element('article', 'tracking-person');
            article.dataset.personSearch = getPersonSearchText(person);

            const main = element('div', 'tracking-person-main');
            const body = element('div', 'tracking-person-body');
            body.append(
                element('strong', 'tracking-person-name', personName),
                element('p', '', processes),
                element(
                    'span',
                    '',
                    `${elementCount} ${plural(elementCount, 'elemento', 'elementos')} · ${lotCount} ${plural(lotCount, 'lote', 'lotes')}`,
                ),
            );

            main.append(body);

            const detailButton = element('button', 'tracking-person-action');
            detailButton.type = 'button';
            detailButton.dataset.personIndex = String(index);
            detailButton.setAttribute('aria-label', `Ver detalle de participación de ${personName}`);
            detailButton.textContent = 'Ver participación';

            article.append(main, detailButton);
            fragment.append(article);
        });

        container.replaceChildren(fragment);
        applyPersonnelFilter();

        if (openPersonIndex !== null && safePersonnel[openPersonIndex]) {
            renderPersonDetail(safePersonnel[openPersonIndex]);
        }
    }

    function renderPhotos(photos) {
        const container = document.getElementById('tracking-photo-gallery');
        if (!container) return;

        const safePhotos = toArray(photos);
        currentPhotos = safePhotos;
        const fragment = document.createDocumentFragment();

        if (!safePhotos.length) {
            const description = config.canManagePhotos
                ? 'Selecciona evidencias de Drive para mostrarlas en esta vista.'
                : 'El administrador todavía no seleccionó fotografías para esta OT.';
            fragment.append(createEmptyState(
                null,
                'Aún no hay fotografías publicadas',
                description,
                'tracking-photo-empty',
            ));
        }

        safePhotos.forEach((photo, index) => {
            const photoName = String(photo.name || `Fotografía ${index + 1}`);
            const imageUrl = String(photo.image_url || '');
            if (!imageUrl) return;

            const figure = element('figure', 'tracking-photo');
            const button = element('button');
            button.type = 'button';
            button.dataset.photoPreview = '';
            button.dataset.photoUrl = imageUrl;
            button.dataset.photoName = photoName;
            button.setAttribute('aria-label', `Ampliar ${photoName}`);

            const image = element('img');
            image.src = imageUrl;
            image.alt = photoName;
            image.loading = 'lazy';
            image.decoding = 'async';

            button.append(image);
            figure.append(button, element('figcaption', '', photoName));
            fragment.append(figure);
        });

        container.replaceChildren(fragment);
    }

    function renderMessages(messages) {
        const container = document.getElementById('tracking-message-list');
        if (!container) return;

        const safeMessages = toArray(messages);
        const fragment = document.createDocumentFragment();
        let previousGroup = '';

        if (!safeMessages.length) {
            fragment.append(createEmptyState(
                'forum',
                'No hay mensajes en esta OT',
                'Los mensajes registrados desde Producción aparecerán aquí.',
                'tracking-empty-activity',
            ));
        }

        safeMessages.forEach((message) => {
            const author = message.usuario_nombre || 'Usuario';
            previousGroup = appendDateSeparator(fragment, message.fecha, previousGroup);
            const isCurrentUser = currentUserId
                && String(message.usuario_id || '') === currentUserId;
            const article = element(
                'article',
                `tracking-activity-entry tracking-message-entry${isCurrentUser ? ' is-current-user' : ''}`,
            );
            const copy = element('div', 'tracking-activity-copy');
            const meta = element('div', 'tracking-activity-meta');

            meta.append(
                element('strong', '', author),
                element('time', '', message.fecha || '-'),
            );
            copy.append(meta, element('p', '', message.mensaje || ''));
            article.append(element('span', 'tracking-activity-avatar', getInitials(author, 'US')), copy);
            fragment.append(article);
        });

        container.replaceChildren(fragment);
    }

    function renderAudits(events) {
        const container = document.getElementById('tracking-audit-list');
        if (!container) return;

        const safeEvents = toArray(events);
        const fragment = document.createDocumentFragment();
        let previousGroup = '';

        if (!safeEvents.length) {
            fragment.append(createEmptyState(
                'manage_history',
                'Aún no hay cambios registrados',
                'Los avances y asignaciones de Producción se mostrarán aquí.',
                'tracking-empty-activity',
            ));
        }

        safeEvents.forEach((event) => {
            const type = classifyAuditEvent(event.mensaje);
            previousGroup = appendDateSeparator(fragment, event.fecha, previousGroup);
            const article = element('article', `tracking-activity-entry tracking-audit-entry ${type.className}`);
            const marker = element('span', 'tracking-activity-marker material-symbols-rounded', type.icon);
            marker.setAttribute('aria-hidden', 'true');

            const copy = element('div', 'tracking-activity-copy');
            const meta = element('div', 'tracking-activity-meta');
            const identity = element('div', 'tracking-activity-identity');
            identity.append(
                element('strong', '', event.usuario_nombre || 'Sistema'),
                element('span', 'tracking-event-kind', type.label),
            );
            meta.append(identity, element('time', '', event.fecha || '-'));
            copy.append(meta, element('p', '', event.mensaje || ''));
            article.append(marker, copy);
            fragment.append(article);
        });

        container.replaceChildren(fragment);
    }

    function updateCollection(signatureKey, items, renderFunction) {
        const safeItems = toArray(items);
        const nextSignature = JSON.stringify(safeItems);
        if (signatures[signatureKey] === nextSignature) return;

        signatures[signatureKey] = nextSignature;
        renderFunction(safeItems);
    }

    function updateActivityCounts(messages, audits) {
        const messageCount = toArray(messages).length;
        const auditCount = toArray(audits).length;
        setText('tracking-message-count', messageCount);
        setText('tracking-audit-count', auditCount);
        setText('tracking-activity-total', messageCount + auditCount);
    }

    function applyTrackingData(data) {
        const safeData = data && typeof data === 'object' ? data : {};
        const lots = toArray(safeData.lots);
        const personnel = toArray(safeData.personnel);
        const photos = toArray(safeData.photos);
        const messages = toArray(safeData.manual_messages);
        const audits = toArray(safeData.audit_events);

        currentPersonnel = personnel;
        updateSummary(safeData);
        updateProcesses(safeData.processes);
        updateCollection('lots', lots, renderLots);
        updateCollection('personnel', personnel, renderPersonnel);
        updateCollection('photos', photos, renderPhotos);
        updateCollection('manualMessages', messages, renderMessages);
        updateCollection('auditEvents', audits, renderAudits);
        updateActivityCounts(messages, audits);

        if (openPersonIndex !== null && personnel[openPersonIndex]) {
            renderPersonDetail(personnel[openPersonIndex]);
        }
    }

    function applyPersonnelFilter() {
        const input = document.getElementById('tracking-person-search');
        const query = String(input?.value || '').trim().toLocaleLowerCase('es');
        const cards = document.querySelectorAll('#tracking-person-list .tracking-person');

        cards.forEach((card) => {
            const searchText = String(card.dataset.personSearch || '');
            card.hidden = Boolean(query) && !searchText.includes(query);
        });
    }

    function setupPersonnelSearch() {
        const input = document.getElementById('tracking-person-search');
        if (input) input.addEventListener('input', applyPersonnelFilter);
    }

    const trackingViewHashes = {
        lots: '',
        personnel: '#personal',
        photos: '#fotos',
        plans: '#planos',
        documents: '#otros-documentos',
    };

    function trackingViewFromHash() {
        return Object.entries(trackingViewHashes)
            .find(([, hash]) => hash && hash === window.location.hash)?.[0] || 'lots';
    }

    function selectTrackingView(target, updateHash = true) {
        const validTarget = Object.prototype.hasOwnProperty.call(trackingViewHashes, target)
            ? target
            : 'lots';

        document.querySelectorAll('[data-tracking-view]').forEach((tab) => {
            const active = tab.dataset.trackingView === validTarget;
            tab.classList.toggle('is-active', active);
            tab.setAttribute('aria-selected', active ? 'true' : 'false');
        });

        document.querySelectorAll('[data-tracking-panel]').forEach((panel) => {
            const active = panel.dataset.trackingPanel === validTarget;
            panel.classList.toggle('is-active', active);
            panel.hidden = !active;
        });

        if (updateHash) {
            const hash = trackingViewHashes[validTarget];
            window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}${hash}`);
        }
    }

    function setupTrackingWorkspace() {
        document.querySelectorAll('[data-tracking-view]').forEach((tab) => {
            tab.addEventListener('click', () => selectTrackingView(tab.dataset.trackingView));
        });

        selectTrackingView(trackingViewFromHash(), false);
        window.TrackingWorkspace = Object.freeze({ select: selectTrackingView });
    }

    function selectActivityTab(target) {
        document.querySelectorAll('[data-activity-tab]').forEach((tab) => {
            const active = tab.dataset.activityTab === target;
            tab.classList.toggle('is-active', active);
            tab.setAttribute('aria-selected', active ? 'true' : 'false');
        });

        const messagesPane = document.getElementById('tracking-messages-pane');
        const historyPane = document.getElementById('tracking-history-pane');
        if (messagesPane) messagesPane.hidden = target !== 'messages';
        if (historyPane) historyPane.hidden = target !== 'history';
    }

    function setupActivityTabs() {
        document.querySelectorAll('[data-activity-tab]').forEach((tab) => {
            tab.addEventListener('click', () => selectActivityTab(tab.dataset.activityTab));
        });
    }

    function updatePhotoSelectionUI() {
        const orderedIds = Array.from(selectedTrackingPhotoIds);
        document.querySelectorAll('[data-tracking-photo-id]').forEach((card) => {
            const position = orderedIds.indexOf(card.dataset.trackingPhotoId);
            card.classList.toggle('is-selected', position >= 0);
            card.setAttribute('aria-pressed', position >= 0 ? 'true' : 'false');
            const badge = card.querySelector('b');
            if (badge) badge.textContent = position >= 0 ? String(position + 1) : '';
        });
        setText('tracking-selected-photo-count', orderedIds.length);
    }

    function setPhotoManagerState(message, mode = 'loading') {
        const state = document.getElementById('tracking-photo-manager-state');
        if (!state) return;
        state.textContent = message;
        state.classList.toggle('is-inline', mode === 'inline');
        state.hidden = !message;
    }

    function renderPhotoCandidates(photos) {
        const container = document.getElementById('tracking-photo-candidates');
        if (!container) return;

        availableTrackingPhotos = toArray(photos).filter((photo) => (
            photo
            && typeof photo.id === 'string'
            && /^[A-Za-z0-9_-]+$/.test(photo.id)
            && typeof photo.thumbnail === 'string'
            && (
                photo.thumbnail.startsWith('https://')
                || photo.thumbnail.startsWith(`${window.location.origin}/`)
            )
        ));
        const fragment = document.createDocumentFragment();

        availableTrackingPhotos.forEach((photo, index) => {
            const photoName = String(photo.nombre || `Fotografía ${index + 1}`);
            const card = element('button', 'tracking-photo-candidate');
            card.type = 'button';
            card.dataset.trackingPhotoId = photo.id;
            card.setAttribute('aria-label', `Seleccionar ${photoName}`);
            card.setAttribute('aria-pressed', 'false');

            const image = element('img');
            image.src = photo.thumbnail;
            image.alt = photoName;
            image.loading = 'lazy';

            card.append(image, element('span', '', photoName), element('b'));
            fragment.append(card);
        });

        container.replaceChildren(fragment);
        if (!availableTrackingPhotos.length) {
            setPhotoManagerState('No hay fotografías disponibles en la carpeta de Drive de esta OT.', 'empty');
        } else {
            setPhotoManagerState('');
        }
        updatePhotoSelectionUI();
    }

    async function openPhotoManager() {
        if (!config.canManagePhotos) return;
        const backdrop = document.getElementById('tracking-photo-manager-backdrop');
        const dialog = document.getElementById('tracking-photo-manager');
        const container = document.getElementById('tracking-photo-candidates');
        if (!backdrop || !dialog || !container) return;

        lastFocusedElement = document.activeElement;
        selectedTrackingPhotoIds = new Set(
            currentPhotos.map((photo) => String(photo.drive_file_id || '')).filter(Boolean),
        );
        container.replaceChildren();
        setPhotoManagerState('Consultando fotografías de la OT…');
        updatePhotoSelectionUI();
        backdrop.hidden = false;
        syncBodyScrollLock();
        window.requestAnimationFrame(() => dialog.focus());

        try {
            const response = await fetch(config.photoCandidatesUrl, {
                cache: 'no-store',
                credentials: 'same-origin',
                headers: {
                    Accept: 'application/json',
                    'X-Requested-With': 'XMLHttpRequest',
                },
            });
            const payload = await readApiJson(
                response,
                'No fue posible consultar Google Drive.',
            );
            if (!response.ok || !payload.success || !Array.isArray(payload.fotos)) {
                throw new Error(payload.error || 'No fue posible consultar Google Drive.');
            }
            renderPhotoCandidates(payload.fotos);
        } catch (error) {
            availableTrackingPhotos = [];
            setPhotoManagerState(error.message || 'No fue posible consultar Google Drive.', 'error');
        }
    }

    function closePhotoManager() {
        const backdrop = document.getElementById('tracking-photo-manager-backdrop');
        if (!backdrop || backdrop.hidden) return;
        backdrop.hidden = true;
        syncBodyScrollLock();
        if (lastFocusedElement instanceof HTMLElement) lastFocusedElement.focus();
    }

    async function saveTrackingPhotos() {
        const saveButton = document.getElementById('tracking-save-photos');
        if (!saveButton || !config.savePhotosUrl) return;

        const photos = Array.from(selectedTrackingPhotoIds)
            .map((imageId) => availableTrackingPhotos.find((photo) => photo.id === imageId))
            .filter(Boolean)
            .map((photo) => ({ id: photo.id, name: photo.nombre || '' }));

        saveButton.disabled = true;
        saveButton.textContent = 'Guardando…';
        setPhotoManagerState('Guardando la selección…', 'inline');

        try {
            const response = await fetch(config.savePhotosUrl, {
                method: 'PUT',
                credentials: 'same-origin',
                headers: {
                    Accept: 'application/json',
                    'Content-Type': 'application/json',
                    'X-CSRFToken': config.csrfToken || '',
                    'X-Requested-With': 'XMLHttpRequest',
                },
                body: JSON.stringify({ photos }),
            });
            const payload = await readApiJson(
                response,
                'No fue posible guardar la selección.',
            );
            if (!response.ok || !payload.success || !Array.isArray(payload.photos)) {
                throw new Error(payload.error || 'No fue posible guardar la selección.');
            }

            signatures.photos = JSON.stringify(payload.photos);
            renderPhotos(payload.photos);
            setText('tracking-photo-count', payload.photos.length);
            setText('tracking-photo-tab-count', payload.photos.length);
            closePhotoManager();
            selectTrackingView('photos');
        } catch (error) {
            setPhotoManagerState(error.message || 'No fue posible guardar la selección.', 'inline');
        } finally {
            saveButton.disabled = false;
            saveButton.textContent = 'Guardar selección';
        }
    }

    function setupPhotoManager() {
        document.querySelectorAll('[data-open-photo-manager]').forEach((button) => {
            button.addEventListener('click', openPhotoManager);
        });
        document.querySelectorAll('[data-close-photo-manager]').forEach((button) => {
            button.addEventListener('click', closePhotoManager);
        });

        const candidates = document.getElementById('tracking-photo-candidates');
        if (candidates) {
            candidates.addEventListener('click', (event) => {
                const card = event.target.closest('[data-tracking-photo-id]');
                if (!card || !candidates.contains(card)) return;
                const imageId = card.dataset.trackingPhotoId;
                if (selectedTrackingPhotoIds.has(imageId)) {
                    selectedTrackingPhotoIds.delete(imageId);
                } else {
                    const limit = Math.max(1, toNumber(config.maxTrackingPhotos) || 12);
                    if (selectedTrackingPhotoIds.size >= limit) {
                        setPhotoManagerState(`Puedes seleccionar como máximo ${limit} fotografías.`, 'inline');
                        return;
                    }
                    selectedTrackingPhotoIds.add(imageId);
                }
                setPhotoManagerState('');
                updatePhotoSelectionUI();
            });
        }

        const backdrop = document.getElementById('tracking-photo-manager-backdrop');
        if (backdrop) {
            backdrop.addEventListener('click', (event) => {
                if (event.target === backdrop) closePhotoManager();
            });
        }

        const saveButton = document.getElementById('tracking-save-photos');
        if (saveButton) saveButton.addEventListener('click', saveTrackingPhotos);
    }

    function setPhotoPreviewState(state) {
        const stage = document.getElementById('tracking-photo-preview-stage');
        const image = document.getElementById('tracking-photo-preview-image');
        const loading = stage?.querySelector('[data-photo-preview-loading]');
        const error = stage?.querySelector('[data-photo-preview-error]');
        if (!stage) return;

        stage.dataset.state = state;
        stage.setAttribute('aria-busy', state === 'loading' ? 'true' : 'false');
        if (loading) loading.hidden = state !== 'loading';
        if (error) error.hidden = state !== 'error';
        if (image) image.hidden = state !== 'ready';
    }

    function preloadPhoto(url) {
        if (!url || decodedPhotoUrls.has(url)) return Promise.resolve();
        if (photoDecodePromises.has(url)) return photoDecodePromises.get(url);

        const promise = new Promise((resolve, reject) => {
            const loader = new Image();
            loader.decoding = 'async';
            loader.fetchPriority = 'high';
            loader.onload = async () => {
                try {
                    if (typeof loader.decode === 'function') await loader.decode();
                } catch (_) {
                    // onload ya confirma que la imagen está disponible para mostrar.
                }
                decodedPhotoUrls.add(url);
                resolve();
            };
            loader.onerror = () => reject(new Error('No se pudo cargar la fotografía.'));
            loader.src = url;
        }).finally(() => photoDecodePromises.delete(url));

        photoDecodePromises.set(url, promise);
        return promise;
    }

    async function openPhotoPreview(url, name, thumbnail = null) {
        const backdrop = document.getElementById('tracking-photo-preview-backdrop');
        const image = document.getElementById('tracking-photo-preview-image');
        const dialog = backdrop?.querySelector('.tracking-photo-preview');
        if (!backdrop || !image || !dialog || !url) return;

        const requestToken = ++photoPreviewToken;
        lastFocusedElement = document.activeElement;
        image.removeAttribute('src');
        image.alt = name || 'Fotografía de seguimiento';
        setText('tracking-photo-preview-name', name || 'Fotografía');
        setPhotoPreviewState('loading');
        backdrop.hidden = false;
        syncBodyScrollLock();
        window.requestAnimationFrame(() => dialog.focus());

        const thumbnailReady = thumbnail instanceof HTMLImageElement
            && thumbnail.complete
            && thumbnail.naturalWidth > 0;
        if (thumbnailReady) decodedPhotoUrls.add(url);

        try {
            if (!thumbnailReady) await preloadPhoto(url);
            if (requestToken !== photoPreviewToken || backdrop.hidden) return;
            image.src = thumbnail?.currentSrc || url;
            setPhotoPreviewState('ready');
        } catch (_) {
            if (requestToken !== photoPreviewToken || backdrop.hidden) return;
            setPhotoPreviewState('error');
        }
    }

    function closePhotoPreview() {
        const backdrop = document.getElementById('tracking-photo-preview-backdrop');
        const image = document.getElementById('tracking-photo-preview-image');
        if (!backdrop || backdrop.hidden) return;
        photoPreviewToken += 1;
        backdrop.hidden = true;
        if (image) image.removeAttribute('src');
        setPhotoPreviewState('idle');
        syncBodyScrollLock();
        if (lastFocusedElement instanceof HTMLElement) lastFocusedElement.focus();
    }

    function setupPhotoPreview() {
        const gallery = document.getElementById('tracking-photo-gallery');
        if (gallery) {
            gallery.addEventListener('click', (event) => {
                const trigger = event.target.closest('[data-photo-preview]');
                if (!trigger || !gallery.contains(trigger)) return;
                openPhotoPreview(
                    trigger.dataset.photoUrl,
                    trigger.dataset.photoName,
                    trigger.querySelector('img'),
                );
            });
            const warmPreview = (event) => {
                const trigger = event.target.closest('[data-photo-preview]');
                if (!trigger || !gallery.contains(trigger)) return;
                preloadPhoto(trigger.dataset.photoUrl).catch(() => {});
            };
            gallery.addEventListener('pointerover', warmPreview);
            gallery.addEventListener('focusin', warmPreview);
        }
        document.querySelectorAll('[data-close-photo-preview]').forEach((button) => {
            button.addEventListener('click', closePhotoPreview);
        });
        const backdrop = document.getElementById('tracking-photo-preview-backdrop');
        if (backdrop) {
            backdrop.addEventListener('click', (event) => {
                if (event.target === backdrop) closePhotoPreview();
            });
        }
    }

    function syncBodyScrollLock() {
        const activityBackdrop = document.getElementById('tracking-activity-backdrop');
        const personBackdrop = document.getElementById('tracking-person-detail-backdrop');
        const photoManagerBackdrop = document.getElementById('tracking-photo-manager-backdrop');
        const photoPreviewBackdrop = document.getElementById('tracking-photo-preview-backdrop');
        const hasOpenOverlay = Boolean(
            (activityBackdrop && !activityBackdrop.hidden)
            || (personBackdrop && !personBackdrop.hidden)
            || (photoManagerBackdrop && !photoManagerBackdrop.hidden)
            || (photoPreviewBackdrop && !photoPreviewBackdrop.hidden)
        );

        document.body.classList.toggle('tracking-overlay-open', hasOpenOverlay);
    }

    function openActivityDrawer(preferredTab = 'messages') {
        const backdrop = document.getElementById('tracking-activity-backdrop');
        const drawer = document.getElementById('tracking-activity-drawer');
        if (!backdrop || !drawer) return;

        lastFocusedElement = document.activeElement;
        selectActivityTab(preferredTab);
        backdrop.hidden = false;
        syncBodyScrollLock();
        window.requestAnimationFrame(() => drawer.focus());
    }

    function closeActivityDrawer() {
        const backdrop = document.getElementById('tracking-activity-backdrop');
        if (!backdrop || backdrop.hidden) return;

        backdrop.hidden = true;
        syncBodyScrollLock();
        if (lastFocusedElement instanceof HTMLElement) lastFocusedElement.focus();
    }

    function setupActivityDrawer() {
        document.querySelectorAll('[data-open-activity]').forEach((button) => {
            button.addEventListener('click', () => openActivityDrawer('messages'));
        });

        document.querySelectorAll('[data-close-activity]').forEach((button) => {
            button.addEventListener('click', closeActivityDrawer);
        });

        const backdrop = document.getElementById('tracking-activity-backdrop');
        if (backdrop) {
            backdrop.addEventListener('click', (event) => {
                if (event.target === backdrop) closeActivityDrawer();
            });
        }
    }

    function renderPersonDetail(person) {
        const personName = person?.name || 'Personal sin nombre';
        const processes = person?.processes || 'Asignación general';
        const elements = personElementSource(person).map(normalizePersonElement);
        const declaredElementCount = toNumber(person?.component_count);
        const lotCount = toNumber(person?.lot_count);
        const list = document.getElementById('tracking-person-detail-list');

        setText('tracking-person-detail-name', personName);
        setText('tracking-person-detail-processes', processes);
        setText('tracking-person-detail-element-count', elements.length || declaredElementCount);
        setText('tracking-person-detail-lot-count', lotCount);
        setText(
            'tracking-person-detail-list-count',
            `${elements.length || declaredElementCount} ${plural(elements.length || declaredElementCount, 'elemento', 'elementos')}`,
        );

        if (!list) return;
        const fragment = document.createDocumentFragment();

        if (!elements.length) {
            const empty = element('div', 'tracking-person-detail-empty');
            empty.append(
                element('strong', '', 'No se recibió el detalle de los elementos'),
                element(
                    'p',
                    '',
                    `El resumen registra ${declaredElementCount} ${plural(declaredElementCount, 'elemento', 'elementos')}, pero el endpoint de seguimiento todavía no envía el código y la marca por persona.`,
                ),
            );
            fragment.append(empty);
        }

        elements.forEach((item, index) => {
            const article = element('article', 'tracking-person-element');
            const main = element('div', 'tracking-person-element-main');
            const codeLine = element('div', 'tracking-person-element-code');
            const headingParts = [item.code, item.brand]
                .filter((value, position, values) => value && values.indexOf(value) === position);
            codeLine.append(element('strong', '', headingParts.join(' · ') || 'Elemento sin marca'));

            main.append(
                codeLine,
                element('p', 'tracking-person-element-description', item.description),
            );

            const metaParts = [];
            if (item.lot) metaParts.push({ label: 'Lote', value: item.lot });
            if (item.processes) metaParts.push({ label: 'Proceso', value: item.processes });

            if (metaParts.length) {
                const meta = element('div', 'tracking-person-element-meta');
                metaParts.forEach((itemMeta) => {
                    const chip = element('span', 'tracking-person-element-chip');
                    chip.append(
                        element('b', '', itemMeta.label),
                        element('span', '', itemMeta.value),
                    );
                    meta.append(chip);
                });
                main.append(meta);
            }

            article.append(
                main,
                element('span', 'tracking-person-element-index', String(index + 1).padStart(2, '0')),
            );
            fragment.append(article);
        });

        list.replaceChildren(fragment);
    }

    function openPersonDetail(index) {
        const person = currentPersonnel[index];
        const backdrop = document.getElementById('tracking-person-detail-backdrop');
        const dialog = document.getElementById('tracking-person-detail-dialog');
        if (!person || !backdrop || !dialog) return;

        lastFocusedElement = document.activeElement;
        openPersonIndex = index;
        renderPersonDetail(person);
        backdrop.hidden = false;
        syncBodyScrollLock();
        window.requestAnimationFrame(() => dialog.focus());
    }

    function closePersonDetail() {
        const backdrop = document.getElementById('tracking-person-detail-backdrop');
        if (!backdrop || backdrop.hidden) return;

        backdrop.hidden = true;
        openPersonIndex = null;
        syncBodyScrollLock();
        if (lastFocusedElement instanceof HTMLElement) lastFocusedElement.focus();
    }

    function setupPersonDetail() {
        const personnelList = document.getElementById('tracking-person-list');
        if (personnelList) {
            personnelList.addEventListener('click', (event) => {
                const button = event.target.closest('[data-person-index]');
                if (!button || !personnelList.contains(button)) return;

                const index = Number(button.dataset.personIndex);
                if (Number.isInteger(index)) openPersonDetail(index);
            });
        }

        document.querySelectorAll('[data-close-person-detail]').forEach((button) => {
            button.addEventListener('click', closePersonDetail);
        });

        const backdrop = document.getElementById('tracking-person-detail-backdrop');
        if (backdrop) {
            backdrop.addEventListener('click', (event) => {
                if (event.target === backdrop) closePersonDetail();
            });
        }
    }

    async function refreshTracking() {
        if (document.hidden || refreshInProgress || !config.refreshUrl) return;
        refreshInProgress = true;

        try {
            const response = await fetch(config.refreshUrl, {
                cache: 'no-store',
                credentials: 'same-origin',
                headers: {
                    Accept: 'application/json',
                    'X-Requested-With': 'XMLHttpRequest',
                },
            });

            applyTrackingData(await readApiJson(
                response,
                'No se pudo actualizar la vista de seguimiento.',
            ));
        } catch (error) {
            console.warn('No se pudo actualizar Seguimiento:', error.message);
        } finally {
            refreshInProgress = false;
        }
    }

    document.addEventListener('keydown', (event) => {
        if (event.key !== 'Escape') return;

        const photoPreviewBackdrop = document.getElementById('tracking-photo-preview-backdrop');
        if (photoPreviewBackdrop && !photoPreviewBackdrop.hidden) {
            closePhotoPreview();
            return;
        }

        const photoManagerBackdrop = document.getElementById('tracking-photo-manager-backdrop');
        if (photoManagerBackdrop && !photoManagerBackdrop.hidden) {
            closePhotoManager();
            return;
        }

        const personBackdrop = document.getElementById('tracking-person-detail-backdrop');
        if (personBackdrop && !personBackdrop.hidden) {
            closePersonDetail();
            return;
        }

        closeActivityDrawer();
    });

    document.addEventListener('DOMContentLoaded', () => {
        setupTrackingWorkspace();
        setupLotDetails();
        setupPersonnelSearch();
        setupActivityTabs();
        setupActivityDrawer();
        setupPersonDetail();
        setupPhotoManager();
        setupPhotoPreview();
        applyTrackingData(initialData);
        window.setInterval(refreshTracking, refreshIntervalMs);
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden) refreshTracking();
        });
    });
})();
