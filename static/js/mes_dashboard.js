(function () {
    'use strict';

    const root = document.getElementById('mes-dashboard');
    if (!root) return;

    const formatter = new Intl.NumberFormat('es-PE', { maximumFractionDigits: 1 });
    const valueText = (value, fallback = '—') => value === null || value === undefined || value === '' ? fallback : String(value);
    const refreshIntervalMs = Math.max(Number(root.dataset.refreshInterval) || 15000, 15000);
    let loadInFlight = false;

    function setText(id, value) {
        const element = document.getElementById(id);
        if (!element) return;
        element.textContent = value;
        element.classList.remove('mes-value-loading');
    }

    async function fetchJson(url) {
        const response = await fetch(url, {
            headers: { Accept: 'application/json' },
            credentials: 'same-origin',
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json();
        if (!payload.success) throw new Error(payload.error || 'Respuesta incompleta');
        return payload;
    }

    function emptyState(title, detail) {
        const wrapper = document.createElement('div');
        wrapper.className = 'mes-empty is-compact';
        const strong = document.createElement('strong');
        strong.textContent = title;
        const paragraph = document.createElement('p');
        paragraph.textContent = detail;
        wrapper.append(strong, paragraph);
        return wrapper;
    }

    function renderPanelError(id) {
        const host = document.getElementById(id);
        if (!host) return;
        host.className = '';
        host.setAttribute('aria-busy', 'false');
        host.replaceChildren(emptyState(
            'No se pudo actualizar esta sección',
            'El sistema volverá a intentarlo automáticamente.'
        ));
    }

    function statusClass(value) {
        const normalized = valueText(value, '').trim().toLocaleLowerCase('es');
        if (['terminado', 'terminada', 'completado', 'completada'].includes(normalized)) return 'is-complete';
        if (normalized === 'en proceso') return 'is-progress';
        if (normalized === 'no comprado') return 'is-danger';
        return '';
    }

    function renderOrders(orders) {
        const host = document.getElementById('dashboard-orders');
        host.className = '';
        host.setAttribute('aria-busy', 'false');
        host.replaceChildren();
        if (!orders.length) {
            host.append(emptyState('Aún no hay producción importada', 'Crea un Packing List dentro de una OT y carga el Excel para alimentar estos indicadores.'));
            return;
        }
        const wrap = document.createElement('div');
        wrap.className = 'mes-table-wrap';
        const table = document.createElement('table');
        table.className = 'mes-table';
        table.innerHTML = '<thead><tr><th>OT</th><th>Cliente / estructura</th><th>PL</th><th>Avance físico</th><th>kg avanzados / total</th><th>Estado</th></tr></thead>';
        const body = document.createElement('tbody');
        orders.forEach((order) => {
            const row = document.createElement('tr');
            const orderCell = document.createElement('td');
            const link = document.createElement('a');
            link.className = 'mes-table-link';
            link.href = order.production_url;
            link.textContent = valueText(order.ot);
            orderCell.append(link);

            const detailCell = document.createElement('td');
            const client = document.createElement('strong');
            client.textContent = valueText(order.cliente);
            const description = document.createElement('small');
            description.textContent = valueText(order.description);
            detailCell.append(client, description);

            const plCell = document.createElement('td');
            plCell.textContent = formatter.format(order.packing_lists || 0);
            const progressCell = document.createElement('td');
            const progress = Math.min(Math.max(Number(order.progress) || 0, 0), 100);
            progressCell.innerHTML = `<div class="mes-progress-cell"><span>${formatter.format(progress)}%</span><i><b style="width:${progress}%"></b></i></div>`;
            const weightCell = document.createElement('td');
            weightCell.textContent = `${formatter.format(order.advanced_kg || 0)} / ${formatter.format(order.weight_kg || 0)}`;
            const stateCell = document.createElement('td');
            const badge = document.createElement('span');
            badge.className = `mes-status ${statusClass(order.state)}`;
            badge.textContent = valueText(order.state, 'Pendiente');
            stateCell.append(badge);
            row.append(orderCell, detailCell, plCell, progressCell, weightCell, stateCell);
            body.append(row);
        });
        table.append(body);
        wrap.append(table);
        host.append(wrap);
    }

    function renderProcesses(processes) {
        const host = document.getElementById('dashboard-processes');
        host.className = '';
        host.setAttribute('aria-busy', 'false');
        host.replaceChildren();
        if (!processes.length) {
            host.append(emptyState('Sin OTs en proceso', 'Cuando una orden entre a fabricación aparecerá aquí con el porcentaje de cada proceso.'));
            return;
        }
        const preferredOrder = ['hab', 'arm', 'sol', 'lim', 'lib', 'gal', 'are', 'pin', 'des'];
        const labels = new Map();
        processes.forEach((order) => (order.processes || []).forEach((process) => {
            labels.set(process.code, process.name);
        }));
        const processCodes = preferredOrder.filter((code) => labels.has(code));
        const wrap = document.createElement('div');
        wrap.className = 'mes-table-wrap mes-process-matrix-wrap';
        const table = document.createElement('table');
        table.className = 'mes-table mes-process-matrix';
        const head = document.createElement('thead');
        const headerRow = document.createElement('tr');
        ['OT', 'Avance OT', ...processCodes.map((code) => labels.get(code))].forEach((label) => {
            const cell = document.createElement('th');
            cell.textContent = label;
            headerRow.append(cell);
        });
        head.append(headerRow);
        const body = document.createElement('tbody');
        processes.forEach((order) => {
            const row = document.createElement('tr');
            const orderCell = document.createElement('td');
            const link = document.createElement('a');
            link.className = 'mes-table-link';
            link.href = order.production_url;
            link.textContent = valueText(order.ot);
            const client = document.createElement('small');
            client.textContent = valueText(order.cliente);
            orderCell.append(link, client);
            const overallCell = document.createElement('td');
            overallCell.append(progressMeter(order.progress));
            const processByCode = new Map((order.processes || []).map((process) => [process.code, process]));
            row.append(orderCell, overallCell);
            processCodes.forEach((code) => {
                const cell = document.createElement('td');
                const process = processByCode.get(code);
                if (process) cell.append(progressMeter(process.progress, true));
                else cell.textContent = '—';
                row.append(cell);
            });
            body.append(row);
        });
        table.append(head, body);
        wrap.append(table);
        host.append(wrap);
    }

    function progressMeter(rawProgress, compact = false) {
        const progress = Math.min(Math.max(Number(rawProgress) || 0, 0), 100);
        const meter = document.createElement('div');
        meter.className = compact ? 'mes-progress-cell is-compact' : 'mes-progress-cell';
        const value = document.createElement('span');
        value.textContent = `${formatter.format(progress)}%`;
        const track = document.createElement('i');
        const fill = document.createElement('b');
        fill.style.width = `${progress}%`;
        track.append(fill);
        meter.append(value, track);
        return meter;
    }

    function renderSupplies(items) {
        const host = document.getElementById('dashboard-supplies');
        host.className = '';
        host.setAttribute('aria-busy', 'false');
        host.replaceChildren();
        if (!items.length) {
            host.append(emptyState('Sin requerimientos', 'La pernería y los suministros del Packing List aparecerán aquí sin afectar el avance de fabricación.'));
            return;
        }
        const wrap = document.createElement('div');
        wrap.className = 'mes-table-wrap';
        const table = document.createElement('table');
        table.className = 'mes-table';
        table.innerHTML = '<thead><tr><th>OT</th><th>Ítems</th><th>Cantidad</th><th>Pendientes</th><th>En compra</th><th>Comprados</th><th>No comprados</th><th>Disponibles</th></tr></thead>';
        const body = document.createElement('tbody');
        items.forEach((item) => {
            const row = document.createElement('tr');
            const ot = document.createElement('td');
            const link = document.createElement('a'); link.className = 'mes-table-link'; link.href = item.warehouse_url; link.textContent = valueText(item.ot);
            const client = document.createElement('small'); client.textContent = valueText(item.cliente);
            ot.append(link, client);
            const values = [
                item.requirements,
                item.quantity,
                item.pending,
                item.in_purchase,
                item.purchased,
                item.not_purchased,
                item.available,
            ];
            row.append(ot);
            values.forEach((value, index) => {
                const cell = document.createElement('td');
                cell.textContent = formatter.format(value || 0);
                if (index === 5 && Number(value) > 0) cell.className = 'mes-danger-value';
                row.append(cell);
            });
            body.append(row);
        });
        table.append(body); wrap.append(table); host.append(wrap);
    }

    function renderAlerts(alerts) {
        const host = document.getElementById('dashboard-alerts');
        host.className = 'mes-alert-list';
        host.setAttribute('aria-busy', 'false');
        host.replaceChildren();
        if (!alerts.length) {
            host.className = '';
            host.append(emptyState('Sin alertas calculadas', 'Las alertas aparecerán cuando existan OTs, pesos y avances operativos.'));
            return;
        }
        alerts.forEach((alert) => {
            const article = document.createElement('article'); article.className = `is-${valueText(alert.level, 'low')}`;
            const dot = document.createElement('i');
            const copy = document.createElement('div');
            const title = document.createElement('strong'); title.textContent = valueText(alert.title);
            const detail = document.createElement('span'); detail.textContent = valueText(alert.detail);
            copy.append(title, detail); article.append(dot, copy); host.append(article);
        });
    }

    function renderSummary(summary) {
        setText('kpi-active-orders', formatter.format(summary.active_orders || 0));
        setText('kpi-delayed-orders', formatter.format(summary.delayed_orders || 0));
    }

    function renderOperations(data) {
        setText('kpi-physical-progress', `${formatter.format(data.kpis.physical_progress || 0)}%`);
        setText('kpi-physical-progress-detail', `${formatter.format(data.kpis.advanced_weight_kg || 0)} kg equivalentes`);
        setText('kpi-pending-galvanizing', formatter.format(data.kpis.pending_galvanizing_kg || 0));
        setText('kpi-dispatched-weight', formatter.format(data.kpis.dispatched_kg || 0));
        renderOrders(data.orders || []);
        renderProcesses(data.processes || []);
        renderSupplies(data.supplies || []);
        renderAlerts(data.alerts || []);
        document.querySelector('.mes-kpi-grid')?.setAttribute('aria-busy', 'false');
    }

    async function load({ initial = false } = {}) {
        if (loadInFlight) return;
        loadInFlight = true;
        try {
            const [summaryResult, operationsResult] = await Promise.allSettled([
                fetchJson(root.dataset.summaryUrl),
                fetchJson(root.dataset.operationsUrl),
            ]);

            if (summaryResult.status === 'fulfilled') {
                const summary = summaryResult.value;
                renderSummary(summary);
            } else if (initial) {
                setText('kpi-active-orders', '—');
                setText('kpi-delayed-orders', '—');
            }

            if (operationsResult.status === 'fulfilled') {
                renderOperations(operationsResult.value);
            } else if (initial) {
                [
                    'dashboard-orders',
                    'dashboard-processes',
                    'dashboard-supplies',
                    'dashboard-alerts',
                ].forEach(renderPanelError);
                document.querySelector('.mes-kpi-grid')?.setAttribute('aria-busy', 'false');
            }
        } finally {
            loadInFlight = false;
        }
    }

    load({ initial: true });
    window.setInterval(() => {
        if (!document.hidden) load();
    }, refreshIntervalMs);
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) load();
    });
})();
