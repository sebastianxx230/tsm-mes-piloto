(() => {
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';

    function notify(message, type = 'success') {
        const container = document.getElementById('toast-container') || document.body;
        const toast = document.createElement('div');
        toast.className = `warehouse-toast is-${type}`;
        toast.textContent = message;
        container.appendChild(toast);
        window.setTimeout(() => toast.remove(), 3200);
    }

    const orderSearch = document.getElementById('warehouse-order-search');
    const orderRows = Array.from(document.querySelectorAll('.warehouse-order-row'));
    const orderCount = document.getElementById('warehouse-order-count');
    const searchEmpty = document.getElementById('warehouse-search-empty');
    const normalize = (value) => String(value || '')
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .toLowerCase()
        .trim();
    if (orderSearch && orderRows.length) {
        orderSearch.addEventListener('input', () => {
            const query = normalize(orderSearch.value);
            let visible = 0;
            orderRows.forEach((row) => {
                const matches = !query || normalize(row.dataset.search).includes(query);
                row.hidden = !matches;
                if (matches) visible += 1;
            });
            if (orderCount) orderCount.textContent = String(visible);
            if (searchEmpty) searchEmpty.hidden = visible !== 0;
        });
    }

    const supplySearch = document.getElementById('warehouse-supply-search');
    const supplyRows = Array.from(document.querySelectorAll('[data-supply-row]'));
    const supplyCount = document.getElementById('warehouse-supply-count');
    const supplySearchEmpty = document.getElementById('warehouse-supply-search-empty');
    if (supplySearch && supplyRows.length) {
        supplySearch.addEventListener('input', () => {
            const query = normalize(supplySearch.value);
            let visible = 0;
            supplyRows.forEach((row) => {
                const matches = !query || normalize(row.dataset.search).includes(query);
                row.hidden = !matches;
                if (matches) visible += 1;
            });
            if (supplyCount) supplyCount.textContent = String(visible);
            if (supplySearchEmpty) supplySearchEmpty.hidden = visible !== 0;
        });
    }

    function updateWarehouseKpis(kpis) {
        if (!kpis) return;
        [
            'requirements', 'pending', 'in-purchase', 'purchased',
            'not-purchased', 'available', 'dispatched'
        ]
            .forEach((key) => {
                const target = document.getElementById(`warehouse-kpi-${key}`);
                const payloadKey = key.replace('-', '_');
                if (target && Number.isFinite(Number(kpis[payloadKey]))) {
                    target.textContent = String(kpis[payloadKey]);
                }
            });
    }

    document.querySelectorAll('.warehouse-state-select').forEach((select) => {
        select.addEventListener('change', async () => {
            const row = select.closest('[data-supply-row]');
            const componentId = row?.dataset.componentId;
            const packingListId = row?.dataset.packingListId;
            const expectedVersion = Number(row?.dataset.packingListVersion || 0);
            const previous = select.dataset.current || 'Pendiente';
            if (!componentId) return;

            select.disabled = true;
            try {
                const response = await fetch(`/api/mes/almacen/componentes/${componentId}/estado`, {
                    method: 'PUT',
                    headers: {
                        'Accept': 'application/json',
                        'Content-Type': 'application/json',
                        'X-CSRFToken': csrfToken,
                    },
                    body: JSON.stringify({
                        estado: select.value,
                        expected_version: expectedVersion || undefined,
                    }),
                });
                const data = await response.json().catch(() => ({}));
                if (!response.ok || !data.success) {
                    throw new Error(data.error || 'No se pudo actualizar el estado.');
                }
                select.dataset.current = data.estado;
                row.dataset.supplyState = data.estado;
                document.querySelectorAll(
                    `[data-supply-row][data-packing-list-id="${packingListId}"]`
                ).forEach((matchingRow) => {
                    matchingRow.dataset.packingListVersion = String(
                        data.packing_list_version
                    );
                });
                updateWarehouseKpis(data.kpis);
                notify('Estado de abastecimiento actualizado.');
            } catch (error) {
                select.value = previous;
                notify(error.message || 'No se pudo actualizar el estado.', 'error');
            } finally {
                select.disabled = false;
            }
        });
    });

    const warehouseConfig = window.WarehouseConfig || null;
    const chatTrigger = document.getElementById('warehouse-chat-trigger');
    const chatOverlay = document.getElementById('warehouse-chat-overlay');
    const chatDrawer = document.getElementById('warehouse-chat-drawer');
    const chatClose = document.getElementById('warehouse-chat-close');
    const chatHistory = document.getElementById('warehouse-chat-history');
    const chatForm = document.getElementById('warehouse-chat-form');
    const chatInput = document.getElementById('warehouse-chat-input');
    let chatRefreshTimer = null;
    let chatLoaded = false;

    function setChatOpen(isOpen) {
        if (!chatDrawer || !chatOverlay || !chatTrigger) return;
        chatDrawer.classList.toggle('is-open', isOpen);
        chatDrawer.setAttribute('aria-hidden', String(!isOpen));
        chatTrigger.setAttribute('aria-expanded', String(isOpen));
        chatOverlay.hidden = !isOpen;
        chatOverlay.classList.toggle('is-open', isOpen);

        if (isOpen) {
            loadWarehouseMessages({ preserveScroll: chatLoaded });
            chatRefreshTimer = window.setInterval(() => {
                if (!document.hidden) loadWarehouseMessages({ preserveScroll: true });
            }, 30000);
            window.setTimeout(() => (chatInput || chatClose)?.focus(), 120);
        } else {
            window.clearInterval(chatRefreshTimer);
            chatRefreshTimer = null;
            chatTrigger.focus();
        }
    }

    function renderWarehouseMessages(messages, { preserveScroll = false } = {}) {
        if (!chatHistory) return;
        const distanceFromBottom = chatHistory.scrollHeight - chatHistory.scrollTop;
        chatHistory.replaceChildren();

        if (!messages.length) {
            const empty = document.createElement('div');
            empty.className = 'warehouse-chat-empty';
            const title = document.createElement('strong');
            title.textContent = 'Aún no hay mensajes';
            const detail = document.createElement('p');
            detail.textContent = 'Inicia la conversación de esta orden de trabajo.';
            empty.append(title, detail);
            chatHistory.appendChild(empty);
        } else {
            messages.forEach((message) => {
                const own = String(message.usuario_id) === String(warehouseConfig.currentUserId);
                const article = document.createElement('article');
                article.className = `warehouse-chat-message ${own ? 'is-own' : 'is-other'}`;

                const meta = document.createElement('div');
                meta.className = 'warehouse-chat-message-meta';
                const author = document.createElement('strong');
                author.textContent = message.usuario_nombre || 'Usuario';
                const time = document.createElement('time');
                time.textContent = message.fecha || '';
                meta.append(author, time);

                const bubble = document.createElement('p');
                bubble.className = 'warehouse-chat-bubble';
                bubble.textContent = message.mensaje || '';
                article.append(meta, bubble);
                chatHistory.appendChild(article);
            });
        }

        if (preserveScroll && chatLoaded) {
            chatHistory.scrollTop = Math.max(0, chatHistory.scrollHeight - distanceFromBottom);
        } else {
            chatHistory.scrollTop = chatHistory.scrollHeight;
        }
        chatLoaded = true;
    }

    async function loadWarehouseMessages(options = {}) {
        if (!warehouseConfig?.otId || !chatHistory) return;
        try {
            const response = await fetch(`/api/mensajes/${warehouseConfig.otId}`, {
                headers: { Accept: 'application/json' },
                cache: 'no-store',
            });
            const data = await response.json().catch(() => null);
            if (!response.ok || !Array.isArray(data)) {
                throw new Error(data?.error || 'No se pudieron cargar los mensajes.');
            }
            renderWarehouseMessages(data, options);
        } catch (error) {
            chatHistory.replaceChildren();
            const status = document.createElement('p');
            status.className = 'warehouse-chat-error';
            status.textContent = error.message || 'No se pudieron cargar los mensajes.';
            chatHistory.appendChild(status);
        }
    }

    async function sendWarehouseMessage(event) {
        event.preventDefault();
        const message = chatInput?.value.trim() || '';
        const submit = chatForm?.querySelector('button[type="submit"]');
        if (!message || !warehouseConfig?.canWriteMessages || !submit) return;

        submit.disabled = true;
        try {
            const response = await fetch('/api/mensajes/enviar', {
                method: 'POST',
                headers: {
                    Accept: 'application/json',
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken,
                },
                body: JSON.stringify({
                    ot_id: warehouseConfig.otId,
                    mensaje: message,
                }),
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok || !data.success) {
                throw new Error(data.error || 'No se pudo enviar el mensaje.');
            }
            chatInput.value = '';
            chatInput.style.height = '';
            await loadWarehouseMessages();
        } catch (error) {
            notify(error.message || 'No se pudo enviar el mensaje.', 'error');
        } finally {
            submit.disabled = false;
            chatInput.focus();
        }
    }

    chatTrigger?.addEventListener('click', () => setChatOpen(true));
    chatClose?.addEventListener('click', () => setChatOpen(false));
    chatOverlay?.addEventListener('click', () => setChatOpen(false));
    chatForm?.addEventListener('submit', sendWarehouseMessage);
    chatInput?.addEventListener('input', () => {
        chatInput.style.height = '';
        chatInput.style.height = `${Math.min(chatInput.scrollHeight, 112)}px`;
    });
    chatInput?.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            chatForm?.requestSubmit();
        }
    });
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && chatDrawer?.classList.contains('is-open')) {
            setChatOpen(false);
        }
    });
    window.addEventListener('pagehide', () => window.clearInterval(chatRefreshTimer));
})();
