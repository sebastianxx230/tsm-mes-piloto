from sqlalchemy import inspect, select
from sqlalchemy.dialects import postgresql

from db_config import db
from models.catalogo_ot import CatalogoOT
from models.produccion import ComponenteOT, MovimientoAlmacen, PackingList
from models.usuario import RolSistema, Usuario
from utils.production_schema import ensure_production_storage_schema


def test_dashboard_and_upcoming_modules_render_for_authenticated_users(client, login):
    login('viewer')

    dashboard = client.get('/mes/dashboard')
    assert dashboard.status_code == 200
    assert b'Dashboard General MES' in dashboard.data
    assert b'Producci' in dashboard.data
    assert b'Almac' in dashboard.data
    assert b'id="dashboard-load-status"' not in dashboard.data
    assert b'Cargando producci' in dashboard.data
    assert b'data-refresh-interval="15000"' in dashboard.data
    assert b'Actualizar dashboard' not in dashboard.data

    summary = client.get('/api/mes/dashboard/resumen')
    operations = client.get('/api/mes/dashboard/operacion')
    assert summary.status_code == 200
    assert operations.status_code == 200
    assert summary.get_json()['active_orders'] == 1
    assert len(operations.get_json()['orders']) == 1

    planning = client.get('/mes/modulo/planeamiento')
    assert planning.status_code == 200
    assert b'Pr\xc3\xb3ximamente' in planning.data


def test_dashboard_normalizes_finished_state_and_excludes_it(
        app,
        client,
        login,
        ids,
):
    with app.app_context():
        work_order = db.session.get(CatalogoOT, ids['ot'])
        work_order.estado = '  TERMINADO  '
        db.session.commit()

    login('viewer')
    summary = client.get('/api/mes/dashboard/resumen').get_json()
    operations = client.get('/api/mes/dashboard/operacion').get_json()

    assert summary['active_orders'] == 0
    assert operations['orders'] == []


def test_dashboard_excludes_orders_that_have_not_started(
        app,
        client,
        login,
        ids,
):
    with app.app_context():
        work_order = db.session.get(CatalogoOT, ids['ot'])
        work_order.estado = 'No Empezado'
        db.session.commit()

    login('viewer')
    summary = client.get('/api/mes/dashboard/resumen').get_json()
    operations = client.get('/api/mes/dashboard/operacion').get_json()

    assert summary['active_orders'] == 0
    assert operations['orders'] == []
    assert operations['processes'] == []
    assert operations['supplies'] == []


def test_profile_has_no_active_operational_module_or_decorative_summary(client, login):
    login('admin')

    response = client.get('/mi-perfil')

    assert response.status_code == 200
    assert b'mes-module-link is-active' not in response.data
    assert b'profile-card' in response.data
    assert b'RESUMEN DE CUENTA' not in response.data


def test_runtime_schema_keeps_unregistered_progress_nullable(app):
    with app.app_context():
        ensure_production_storage_schema()
        inspector = inspect(db.engine)
        component_columns = {
            column['name']: column
            for column in inspector.get_columns('componentes_ot')
        }
        for column_name in (
            'hab_real', 'arm_real', 'sol_real', 'lim_real',
            'lib_real', 'gal_real', 'are_real', 'pin_real',
        ):
            assert component_columns[column_name]['nullable'] is True

        process_columns = {
            column['name']: column
            for column in inspector.get_columns('avance_elemento_proceso')
        }
        assert process_columns['cantidad_completada']['nullable'] is True


def test_component_row_lock_never_locks_optional_route_join():
    statement = (
        select(ComponenteOT)
        .where(ComponenteOT.id == 10)
        .with_for_update(of=ComponenteOT)
    )
    sql = str(statement.compile(dialect=postgresql.dialect()))

    assert 'LEFT OUTER JOIN' not in sql.upper()
    assert 'FOR UPDATE OF componentes_ot' in sql


def test_warehouse_uses_only_fasteners_and_updates_state(
        app,
        client,
        login,
        ids,
):
    with app.app_context():
        ensure_production_storage_schema()
        packing_list = db.session.get(PackingList, ids['packing_list'])
        supply = ComponenteOT(
            pl_id=packing_list.id,
            marca='P-TEMP-01',
            cantidad=12,
            descripcion='Pernos de template',
            categoria='PERNERIA',
            subcategoria='TEMPLATE',
            unidad='UND',
            tipo='p_template',
            estado_suministro='Pendiente',
        )
        db.session.add(supply)
        db.session.add(ComponenteOT(
            pl_id=packing_list.id,
            marca='S-CORTE-01',
            cantidad=5,
            descripcion='Disco de corte de producción',
            categoria='SUMINISTRO',
            subcategoria='CONSUMIBLE',
            unidad='UND',
            tipo='suministro',
            estado_suministro='Pendiente',
        ))
        editor = Usuario.query.filter_by(username='editor').one()
        editor.roles.append(RolSistema.query.filter_by(clave='almacen').one())
        db.session.commit()
        supply_id = supply.id

    login('editor')
    catalog = client.get('/mes/almacen')
    assert catalog.status_code == 200
    assert b'Selecciona una OT' in catalog.data

    page = client.get(f"/mes/almacen?ot={ids['ot']}")
    assert page.status_code == 200
    assert b'P-TEMP-01' in page.data
    assert b'Pernos de template' in page.data
    assert b'S-CORTE-01' not in page.data
    assert b'warehouse-context-bar' in page.data
    assert b'warehouse-chat-drawer' in page.data
    assert b'compartido con Producci' in page.data

    message = client.post(
        '/api/mensajes/enviar',
        json={
            'ot_id': ids['ot'],
            'mensaje': 'Pernería disponible para producción',
        },
    )
    assert message.status_code == 200, message.get_json()
    shared_messages = client.get(f"/api/mensajes/{ids['ot']}")
    assert shared_messages.status_code == 200
    assert any(
        row['mensaje'] == 'Pernería disponible para producción'
        for row in shared_messages.get_json()
    )

    response = client.put(
        f'/api/mes/almacen/componentes/{supply_id}/estado',
        json={'estado': 'En almacén'},
    )
    assert response.status_code == 200, response.get_json()
    assert response.get_json()['estado'] == 'En almacén'

    with app.app_context():
        assert db.session.get(ComponenteOT, supply_id).estado_suministro == 'En almacén'
        movement = MovimientoAlmacen.query.filter_by(
            componente_id=supply_id,
        ).one()
        assert movement.estado_anterior == 'Pendiente'
        assert movement.estado_nuevo == 'En almacén'


def test_warehouse_role_can_write_shared_ot_messages():
    from utils.rbac_catalog import ROLE_SEED

    warehouse_role = next(role for role in ROLE_SEED if role[0] == 'almacen')
    assert 'messages.view' in warehouse_role[2]
    assert 'messages.write' in warehouse_role[2]


def test_production_v3_uses_weighted_physical_progress_contract():
    template = open('templates/produccion.html', encoding='utf-8-sig').read()
    script = open('static/js/produccion.js', encoding='utf-8-sig').read()

    assert 'production-v3-workspace' in template
    assert 'Peso avanzado' in template
    assert 'Avance físico por peso' in template
    assert 'sumaAvancesTotales += porcFilaFinal * pesoFisico' in script
    assert 'pesoFab += pesoFisico' in script
