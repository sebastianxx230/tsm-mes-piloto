from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
import os
import threading
import time
import unicodedata

from flask import (
    Blueprint,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import case, func, select
from sqlalchemy.orm import joinedload, lazyload, selectinload

from db_config import db
from models.catalogo_ot import CatalogoOT
from models.produccion import (
    AvanceElementoProceso,
    BitacoraOT,
    ComponenteOT,
    MovimientoAlmacen,
    PackingList,
    RutaProceso,
    RutaProduccion,
)
from utils.auth import permission_required
from utils.production_metrics import (
    PROCESS_DEFINITIONS,
    clamped_ratio,
    component_progress,
    process_settings,
)


mes_bp = Blueprint('mes_bp', __name__)

DASHBOARD_CACHE_TTL_SECONDS = max(
    1,
    int(os.environ.get('DASHBOARD_CACHE_TTL_SECONDS', '12')),
)
_dashboard_cache_lock = threading.Lock()
_dashboard_cache = {}

SUPPLY_STATES = (
    'Pendiente',
    'No requerido',
    'No comprado',
    'En compra',
    'Comprado',
    'En almacén',
    'Despachado',
)

COMING_MODULES = {
    'planeamiento': {
        'name': 'Planeamiento',
        'icon': 'calendar_month',
        'description': (
            'Programación de carga, prioridades, fechas planificadas y '
            'comparación del plan contra el avance real.'
        ),
        'dependencies': ('Producción estable', 'Fechas por proceso', 'Capacidad de planta'),
    },
    'calidad': {
        'name': 'Calidad',
        'icon': 'verified_user',
        'description': (
            'Liberaciones, inspecciones, observaciones, certificados y '
            'trazabilidad de conformidad por elemento.'
        ),
        'dependencies': ('Rutas productivas', 'Liberación por proceso', 'Documentos'),
    },
    'logistica': {
        'name': 'Logística',
        'icon': 'local_shipping',
        'description': (
            'Programación de despachos, guías, transporte y confirmación '
            'de salida por OT y site.'
        ),
        'dependencies': ('Almacén', 'Piezas terminadas', 'Documentación de salida'),
    },
    'comercial': {
        'name': 'Comercial',
        'icon': 'groups',
        'description': (
            'Consulta ejecutiva orientada al cliente, hitos publicados y '
            'estado resumido de cada orden.'
        ),
        'dependencies': ('Dashboard confiable', 'Contenido publicable', 'Portal externo'),
    },
    'reportes': {
        'name': 'Reportes',
        'icon': 'bar_chart',
        'description': (
            'Reportes operativos y ejecutivos construidos desde la misma '
            'fuente de datos del MES.'
        ),
        'dependencies': ('Producción V2', 'Almacén', 'Indicadores validados'),
    },
}


def _as_float(value):
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _normalized_state(value):
    """Normalize catalog states before using them in operational metrics."""
    text = ' '.join(str(value or '').strip().split()).casefold()
    return ''.join(
        character
        for character in unicodedata.normalize('NFKD', text)
        if not unicodedata.combining(character)
    )


def _is_finished_state(value):
    return _normalized_state(value) in {
        'terminado',
        'terminada',
        'completado',
        'completada',
        'finalizado',
        'finalizada',
    }


def _is_in_progress_state(value):
    return _normalized_state(value) == 'en proceso'


def _component_weight(component):
    total = _as_float(component.peso_total_kg)
    if total > 0:
        return total
    unit = _as_float(component.peso_unitario_kg)
    return max(unit * max(int(component.cantidad or 0), 0), 0.0)


def _process_ratios(component):
    """Return normalized process ratios, falling back to the legacy columns."""
    normalized = {
        row.proceso.codigo: clamped_ratio(
            row.cantidad_completada,
            component.cantidad,
        )
        for row in component.avances_proceso
        if row.aplica and row.proceso is not None
    }
    if normalized:
        return normalized

    return {
        code: clamped_ratio(getattr(component, field), component.cantidad)
        for code, _label, field, _weight, _color in PROCESS_DEFINITIONS
        if getattr(component, field, -1) != -1
    }


def _component_progress(component, work_order):
    rows = [row for row in component.avances_proceso if row.aplica]
    if not rows:
        weights, active_processes = process_settings(work_order)
        return component_progress(component, weights, active_processes)

    route_weights = {}
    if component.ruta is not None:
        for step in component.ruta.procesos:
            if step.proceso is None:
                continue
            route_weights[step.proceso.codigo] = _as_float(
                step.peso if step.peso is not None else step.proceso.peso_default
            )

    weighted = 0.0
    available = 0.0
    for row in rows:
        if row.proceso is None or row.proceso.codigo == 'des':
            continue
        weight = route_weights.get(
            row.proceso.codigo,
            _as_float(row.proceso.peso_default),
        )
        if weight <= 0:
            continue
        ratio = clamped_ratio(row.cantidad_completada, component.cantidad)
        available += weight
        if ratio is None:
            continue
        weighted += ratio * weight
    return (weighted / available * 100.0) if available else 0.0


def _production_snapshot(*, in_progress_only=False):
    work_orders = (
        CatalogoOT.query.filter_by(archivado=False)
        .order_by(CatalogoOT.item.desc())
        .all()
    )
    if in_progress_only:
        work_orders = [
            work_order
            for work_order in work_orders
            if _is_in_progress_state(work_order.estado)
        ]
    work_order_by_id = {work_order.item: work_order for work_order in work_orders}

    packing_lists = []
    if work_order_by_id:
        packing_lists = db.session.execute(
            select(PackingList)
            .where(
                PackingList.archivado.is_(False),
                PackingList.ot_id.in_(tuple(work_order_by_id)),
            )
            .options(
                joinedload(PackingList.ot_rel),
                selectinload(PackingList.componentes)
                .selectinload(ComponenteOT.avances_proceso)
                .joinedload(AvanceElementoProceso.proceso),
                selectinload(PackingList.componentes)
                .joinedload(ComponenteOT.ruta)
                .selectinload(RutaProduccion.procesos)
                .joinedload(RutaProceso.proceso),
            )
            .order_by(PackingList.ot_id.desc(), PackingList.orden.asc())
        ).scalars().unique().all()

    ot_metrics = defaultdict(lambda: {
        'packing_lists': 0,
        'weight_kg': 0.0,
        'advanced_kg': 0.0,
        'fabrication_items': 0,
        'supply_items': 0,
        'routes': set(),
        'sites': set(),
        'processes': defaultdict(
            lambda: {'total_kg': 0.0, 'advanced_kg': 0.0}
        ),
    })
    process_metrics = defaultdict(lambda: {'total_kg': 0.0, 'advanced_kg': 0.0})
    supplies = []
    pending_galvanizing_kg = 0.0
    dispatched_kg = 0.0

    for packing_list in packing_lists:
        metrics = ot_metrics[packing_list.ot_id]
        metrics['packing_lists'] += 1
        if packing_list.site:
            metrics['sites'].add(packing_list.site)

        work_order = work_order_by_id.get(packing_list.ot_id)
        if work_order is None:
            continue

        for component in packing_list.componentes:
            category = str(component.categoria or 'FABRICACION').upper()
            if category != 'FABRICACION':
                metrics['supply_items'] += 1
                supplies.append({
                    'id': component.id,
                    'ot_id': work_order.item,
                    'ot': work_order.ot,
                    'cliente': work_order.cliente,
                    'pl': packing_list.nombre,
                    'site': packing_list.site or 'Sin site',
                    'code': component.marca,
                    'category': category,
                    'subcategory': component.subcategoria or category.title(),
                    'description': component.descripcion or '-',
                    'quantity': _as_float(component.cantidad),
                    'unit': component.unidad or 'UND',
                    'weight_kg': _component_weight(component),
                    'state': component.estado_suministro or 'Pendiente',
                    'pl_version': int(packing_list.version or 1),
                })
                continue

            metrics['fabrication_items'] += 1
            weight = _component_weight(component)
            progress = _component_progress(component, work_order)
            metrics['weight_kg'] += weight
            metrics['advanced_kg'] += weight * progress / 100.0
            if component.ruta is not None:
                metrics['routes'].add(component.ruta.nombre)

            ratios = _process_ratios(component)
            for process_code, ratio in ratios.items():
                process_metrics[process_code]['total_kg'] += weight
                metrics['processes'][process_code]['total_kg'] += weight
                if ratio is not None:
                    process_metrics[process_code]['advanced_kg'] += weight * ratio
                    metrics['processes'][process_code]['advanced_kg'] += weight * ratio

            release_ratio = ratios.get('lib') or 0.0
            galvanizing_ratio = ratios.get('gal') or 0.0
            pending_galvanizing_kg += weight * max(release_ratio - galvanizing_ratio, 0.0)
            dispatched_kg += weight * (ratios.get('des') or 0.0)

    summaries = []
    for work_order in work_orders:
        metrics = ot_metrics[work_order.item]
        weight = metrics['weight_kg']
        advanced = metrics['advanced_kg']
        process_progress = []
        for code, label, _field, _weight, _color in PROCESS_DEFINITIONS:
            values = metrics['processes'][code]
            process_total = values['total_kg']
            if process_total <= 0:
                continue
            process_progress.append({
                'code': code,
                'name': label,
                'progress': (
                    values['advanced_kg'] / process_total * 100.0
                ),
            })
        summaries.append({
            'id': work_order.item,
            'ot': work_order.ot,
            'cliente': work_order.cliente,
            'description': work_order.descripcion or '-',
            'state': work_order.estado,
            'start': work_order.fecha_iniciado,
            'end': work_order.fecha_termino,
            'packing_lists': metrics['packing_lists'],
            'sites': sorted(metrics['sites']),
            'weight_kg': weight,
            'advanced_kg': advanced,
            'progress': (advanced / weight * 100.0) if weight > 0 else 0.0,
            'fabrication_items': metrics['fabrication_items'],
            'supply_items': metrics['supply_items'],
            'routes': sorted(metrics['routes']),
            'processes': process_progress,
        })

    process_catalog = {
        code: label for code, label, _field, _weight, _color in PROCESS_DEFINITIONS
    }
    processes = []
    for code, label, _field, _weight, _color in PROCESS_DEFINITIONS:
        values = process_metrics[code]
        total = values['total_kg']
        if total <= 0:
            continue
        processes.append({
            'code': code,
            'name': process_catalog.get(code, label),
            'total_kg': total,
            'advanced_kg': values['advanced_kg'],
            'progress': (
                values['advanced_kg'] / total * 100.0 if total > 0 else 0.0
            ),
        })

    return {
        'work_orders': work_orders,
        'work_order_summaries': summaries,
        'packing_lists': packing_lists,
        'processes': processes,
        'supplies': supplies,
        'pending_galvanizing_kg': pending_galvanizing_kg,
        'dispatched_kg': dispatched_kg,
    }


def _dashboard_context(snapshot):
    today = date.today()
    summaries = snapshot['work_order_summaries']
    active = [row for row in summaries if _is_in_progress_state(row['state'])]
    active_with_production = [row for row in active if row['weight_kg'] > 0]
    total_weight = sum(row['weight_kg'] for row in active_with_production)
    advanced_weight = sum(row['advanced_kg'] for row in active_with_production)
    delayed = [
        row for row in active
        if row['end'] is not None and row['end'] < today
    ]
    supplies_by_ot = {}
    for item in snapshot['supplies']:
        supply = supplies_by_ot.setdefault(item['ot_id'], {
            'ot_id': item['ot_id'],
            'ot': item['ot'],
            'cliente': item['cliente'],
            'requirements': 0,
            'quantity': 0.0,
            'pending': 0,
            'in_purchase': 0,
            'purchased': 0,
            'available': 0,
            'not_purchased': 0,
            'dispatched': 0,
        })
        supply['requirements'] += 1
        supply['quantity'] += item['quantity']
        state = item['state']
        if state == 'Pendiente':
            supply['pending'] += 1
        elif state == 'En compra':
            supply['in_purchase'] += 1
        elif state == 'Comprado':
            supply['purchased'] += 1
        elif state == 'En almacén':
            supply['available'] += 1
        elif state == 'No comprado':
            supply['not_purchased'] += 1
        elif state == 'Despachado':
            supply['dispatched'] += 1
            supply['available'] += 1

    supply_pending = sum(
        row['pending'] + row['in_purchase']
        for row in supplies_by_ot.values()
    )

    alerts = []
    for row in delayed[:3]:
        alerts.append({
            'level': 'high',
            'title': f"{row['ot']} fuera de fecha",
            'detail': f"Término registrado: {row['end'].strftime('%d/%m/%Y')}",
        })
    for item in (
        item for item in snapshot['supplies']
        if item['state'] == 'No comprado'
    ):
        alerts.append({
            'level': 'high',
            'title': f"{item['ot']}: material no comprado",
            'detail': f"{item['code']} · {item['description']}",
        })
        if sum(alert['level'] == 'high' for alert in alerts) >= 4:
            break
    if snapshot['pending_galvanizing_kg'] > 0:
        alerts.append({
            'level': 'medium',
            'title': 'Peso liberado pendiente de galvanizado',
            'detail': f"{snapshot['pending_galvanizing_kg']:,.1f} kg",
        })
    if supply_pending:
        alerts.append({
            'level': 'medium',
            'title': 'Requerimientos de abastecimiento pendientes',
            'detail': f'{supply_pending} ítems pendientes o en compra',
        })
    missing_packing_lists = sum(row['packing_lists'] == 0 for row in active)
    if missing_packing_lists:
        alerts.append({
            'level': 'low',
            'title': 'OT sin Packing List importado',
            'detail': f'{missing_packing_lists} órdenes todavía no alimentan producción',
        })

    return {
        'kpis': {
            'active_orders': len(active),
            'total_weight_kg': total_weight,
            'advanced_weight_kg': advanced_weight,
            'physical_progress': (
                advanced_weight / total_weight * 100.0 if total_weight > 0 else 0.0
            ),
            'delayed_orders': len(delayed),
            'pending_galvanizing_kg': snapshot['pending_galvanizing_kg'],
            'dispatched_kg': snapshot['dispatched_kg'],
        },
        'orders': active[:12],
        'processes': active[:12],
        'supplies': list(supplies_by_ot.values())[:12],
        'alerts': alerts[:8],
    }


def _dashboard_catalog_summary():
    """Return the fast, catalog-only part of the Dashboard."""
    today = date.today()
    work_orders = (
        CatalogoOT.query.filter_by(archivado=False)
        .order_by(CatalogoOT.item.desc())
        .all()
    )
    active = [
        work_order
        for work_order in work_orders
        if _is_in_progress_state(work_order.estado)
    ]
    delayed = [
        work_order
        for work_order in active
        if work_order.fecha_termino is not None
        and work_order.fecha_termino < today
    ]
    return {
        'active_orders': len(active),
        'delayed_orders': len(delayed),
    }


def _dashboard_operations_payload(dashboard):
    return {
        'kpis': {
            'physical_progress': dashboard['kpis']['physical_progress'],
            'advanced_weight_kg': dashboard['kpis']['advanced_weight_kg'],
            'pending_galvanizing_kg': dashboard['kpis']['pending_galvanizing_kg'],
            'dispatched_kg': dashboard['kpis']['dispatched_kg'],
        },
        'orders': [
            {
                **{
                    key: row[key]
                    for key in (
                        'ot', 'cliente', 'description', 'state',
                        'packing_lists', 'progress', 'advanced_kg', 'weight_kg',
                    )
                },
                'production_url': url_for(
                    'gestion_ot_bp.produccion',
                    id=row['id'],
                ),
            }
            for row in dashboard['orders']
        ],
        'processes': [
            {
                'ot': row['ot'],
                'cliente': row['cliente'],
                'progress': row['progress'],
                'processes': row['processes'],
                'production_url': url_for(
                    'gestion_ot_bp.produccion',
                    id=row['id'],
                ),
            }
            for row in dashboard['processes']
        ],
        'supplies': [
            {
                **row,
                'warehouse_url': url_for(
                    'mes_bp.almacen',
                    ot=row['ot_id'],
                ),
            }
            for row in dashboard['supplies']
        ],
        'alerts': dashboard['alerts'],
    }


def _cached_dashboard_value(key, builder):
    """Evita repetir las consultas pesadas para cada usuario del panel."""
    if current_app.config.get('TESTING'):
        return builder()
    now = time.monotonic()
    with _dashboard_cache_lock:
        cached = _dashboard_cache.get(key)
        if cached and cached['expires_at'] > now:
            return cached['value']

        value = builder()
        _dashboard_cache[key] = {
            'expires_at': time.monotonic() + DASHBOARD_CACHE_TTL_SECONDS,
            'value': value,
        }
        return value


def _build_dashboard_operations_payload():
    snapshot = _production_snapshot(in_progress_only=True)
    return _dashboard_operations_payload(_dashboard_context(snapshot))


def _is_warehouse_component():
    return func.upper(
        func.coalesce(ComponenteOT.categoria, 'FABRICACION')
    ) == 'PERNERIA'


def _warehouse_orders():
    state = func.coalesce(ComponenteOT.estado_suministro, 'Pendiente')
    rows = db.session.execute(
        select(
            CatalogoOT.item.label('ot_id'),
            CatalogoOT.ot,
            CatalogoOT.cliente,
            CatalogoOT.descripcion,
            func.count(ComponenteOT.id).label('requirements'),
            func.count(func.distinct(PackingList.id)).label('packing_lists'),
            func.sum(case(
                (state == 'Pendiente', 1),
                else_=0,
            )).label('pending'),
            func.sum(case(
                (state == 'En compra', 1),
                else_=0,
            )).label('in_purchase'),
            func.sum(case(
                (state == 'Comprado', 1),
                else_=0,
            )).label('purchased'),
            func.sum(case(
                (state == 'No comprado', 1),
                else_=0,
            )).label('not_purchased'),
            func.sum(case(
                (state.in_(('En almacén', 'Despachado')), 1),
                else_=0,
            )).label('available'),
            func.sum(case(
                (state == 'Despachado', 1),
                else_=0,
            )).label('dispatched'),
        )
        .join(PackingList, PackingList.ot_id == CatalogoOT.item)
        .join(ComponenteOT, ComponenteOT.pl_id == PackingList.id)
        .where(
            CatalogoOT.archivado.is_(False),
            PackingList.archivado.is_(False),
            _is_warehouse_component(),
        )
        .group_by(
            CatalogoOT.item,
            CatalogoOT.ot,
            CatalogoOT.cliente,
            CatalogoOT.descripcion,
        )
        .order_by(CatalogoOT.item.desc())
    ).all()
    return [
        {
            'ot_id': row.ot_id,
            'ot': row.ot,
            'cliente': row.cliente,
            'description': row.descripcion or '-',
            'requirements': int(row.requirements or 0),
            'packing_lists': int(row.packing_lists or 0),
            'pending': int(row.pending or 0),
            'in_purchase': int(row.in_purchase or 0),
            'purchased': int(row.purchased or 0),
            'not_purchased': int(row.not_purchased or 0),
            'available': int(row.available or 0),
            'dispatched': int(row.dispatched or 0),
        }
        for row in rows
    ]


def _warehouse_supply_payload(component, packing_list, work_order):
    category = str(component.categoria or 'OTRO').upper()
    return {
        'id': component.id,
        'ot_id': work_order.item,
        'ot': work_order.ot,
        'cliente': work_order.cliente,
        'pl_id': packing_list.id,
        'pl': packing_list.nombre,
        'site': packing_list.site or 'Sin site',
        'code': component.marca,
        'category': category,
        'subcategory': component.subcategoria or category.title(),
        'description': component.descripcion or '-',
        'quantity': _as_float(component.cantidad),
        'unit': component.unidad or 'UND',
        'weight_kg': _component_weight(component),
        'state': component.estado_suministro or 'Pendiente',
        'pl_version': int(packing_list.version or 1),
    }


def _warehouse_supplies(work_order, selected_state=''):
    statement = (
        select(ComponenteOT, PackingList)
        .join(PackingList, PackingList.id == ComponenteOT.pl_id)
        .where(
            PackingList.ot_id == work_order.item,
            PackingList.archivado.is_(False),
            _is_warehouse_component(),
        )
        .options(lazyload(ComponenteOT.ruta))
        .order_by(
            PackingList.orden.asc(),
            ComponenteOT.fila_origen.asc().nullslast(),
            ComponenteOT.id.asc(),
        )
    )
    if selected_state in SUPPLY_STATES:
        statement = statement.where(
            func.coalesce(
                ComponenteOT.estado_suministro,
                'Pendiente',
            ) == selected_state
        )
    return [
        _warehouse_supply_payload(component, packing_list, work_order)
        for component, packing_list in db.session.execute(statement).all()
    ]


def _warehouse_kpis(rows):
    return {
        'requirements': sum(int(row.get('requirements', 1)) for row in rows),
        'pending': sum(int(row.get('pending', row.get('state') == 'Pendiente')) for row in rows),
        'in_purchase': sum(int(row.get('in_purchase', row.get('state') == 'En compra')) for row in rows),
        'purchased': sum(int(row.get('purchased', row.get('state') == 'Comprado')) for row in rows),
        'not_purchased': sum(int(row.get('not_purchased', row.get('state') == 'No comprado')) for row in rows),
        'available': sum(int(row.get('available', row.get('state') in {'En almacén', 'Despachado'})) for row in rows),
        'dispatched': sum(int(row.get('dispatched', row.get('state') == 'Despachado')) for row in rows),
    }


@mes_bp.get('/mes')
@login_required
def mes_home():
    return redirect(url_for('mes_bp.dashboard'))


@mes_bp.get('/dashboard')
@mes_bp.get('/mes/dashboard')
@login_required
def dashboard():
    return render_template(
        'mes_dashboard.html',
        active_module='dashboard',
    )


@mes_bp.get('/api/mes/dashboard/resumen')
@login_required
def dashboard_summary():
    summary = _cached_dashboard_value(
        'summary',
        _dashboard_catalog_summary,
    )
    return jsonify({'success': True, **summary})


@mes_bp.get('/api/mes/dashboard/operacion')
@login_required
def dashboard_operations():
    payload = _cached_dashboard_value(
        'operations',
        _build_dashboard_operations_payload,
    )
    return jsonify({
        'success': True,
        **payload,
    })


@mes_bp.get('/almacen')
@mes_bp.get('/mes/almacen')
@login_required
def almacen():
    ot_id = request.args.get('ot', type=int)
    state = str(request.args.get('estado') or '').strip()
    warehouse_orders = _warehouse_orders()
    selected_work_order = None
    supplies = []
    selected_supply_summary = []
    if ot_id:
        selected_work_order = db.session.get(CatalogoOT, ot_id)
        if (
            selected_work_order is None
            or selected_work_order.archivado
            or not any(row['ot_id'] == ot_id for row in warehouse_orders)
        ):
            return redirect(url_for('mes_bp.almacen'))
        selected_supply_summary = _warehouse_supplies(selected_work_order)
        supplies = (
            [row for row in selected_supply_summary if row['state'] == state]
            if state in SUPPLY_STATES
            else selected_supply_summary
        )

    kpi_rows = selected_supply_summary if selected_work_order else warehouse_orders
    return render_template(
        'almacen.html',
        supplies=supplies,
        warehouse_orders=warehouse_orders,
        selected_work_order=selected_work_order,
        selected_ot=ot_id,
        selected_state=state,
        supply_states=SUPPLY_STATES,
        warehouse_kpis=_warehouse_kpis(kpi_rows),
        active_module='almacen',
    )


@mes_bp.put('/api/mes/almacen/componentes/<int:component_id>/estado')
@login_required
@permission_required('warehouse.movements.create')
def update_supply_state(component_id):
    data = request.get_json(silent=True) or {}
    state = str(data.get('estado') or '').strip()
    if state not in SUPPLY_STATES:
        return jsonify({'success': False, 'error': 'El estado no está permitido.'}), 400

    component_pl_id = db.session.execute(
        select(ComponenteOT.pl_id).where(ComponenteOT.id == component_id)
    ).scalar_one_or_none()
    if component_pl_id is None:
        return jsonify({'success': False, 'error': 'Requerimiento no encontrado.'}), 404

    packing_list = db.session.get(
        PackingList,
        component_pl_id,
        with_for_update=True,
    )
    if packing_list is None or packing_list.archivado:
        return jsonify({'success': False, 'error': 'Packing List no disponible.'}), 409

    expected_version = data.get('expected_version')
    if expected_version is not None:
        try:
            expected_version = int(expected_version)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'La versión enviada no es válida.'}), 400
        if expected_version != int(packing_list.version or 1):
            db.session.rollback()
            return jsonify({
                'success': False,
                'error': 'Otra persona actualizó esta OT. Recarga Almacén.',
                'current_version': packing_list.version,
            }), 409

    component = db.session.execute(
        select(ComponenteOT)
        .where(ComponenteOT.id == component_id)
        .with_for_update(of=ComponenteOT)
    ).scalar_one_or_none()
    if (
        component is None
        or component.pl_id != packing_list.id
        or str(component.categoria or '').upper() == 'FABRICACION'
    ):
        return jsonify({'success': False, 'error': 'Requerimiento no encontrado.'}), 404

    previous = component.estado_suministro or 'Pendiente'
    if previous != state:
        component.estado_suministro = state
        packing_list.incrementar_version()
        db.session.add(MovimientoAlmacen(
            componente_id=component.id,
            packing_list_id=packing_list.id,
            ot_id=packing_list.ot_id,
            codigo=component.marca,
            descripcion=component.descripcion,
            cantidad=component.cantidad,
            unidad=component.unidad or 'UND',
            estado_anterior=previous,
            estado_nuevo=state,
            usuario_id=current_user.id,
            usuario_nombre=current_user.nombre,
        ))
        db.session.add(BitacoraOT(
            ot_id=packing_list.ot_id,
            usuario_id=current_user.id,
            usuario_nombre=current_user.nombre,
            mensaje=(
                f'Actualizó abastecimiento de {component.marca}: '
                f'{previous} → {state}.'
            ),
            tipo='audit',
        ))
        db.session.commit()
        with _dashboard_cache_lock:
            _dashboard_cache.clear()

    work_order = db.session.get(CatalogoOT, packing_list.ot_id)
    warehouse_kpis = (
        _warehouse_kpis(_warehouse_supplies(work_order))
        if work_order is not None
        else None
    )

    return jsonify({
        'success': True,
        'estado': state,
        'packing_list_version': packing_list.version,
        'kpis': warehouse_kpis,
    })


@mes_bp.get('/mes/modulo/<string:module_key>')
@login_required
def upcoming_module(module_key):
    module = COMING_MODULES.get(module_key)
    if module is None:
        return redirect(url_for('mes_bp.dashboard'))
    return render_template(
        'modulo_proximamente.html',
        module_key=module_key,
        module=module,
        active_module=module_key,
    )
