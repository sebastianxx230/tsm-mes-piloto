from decimal import Decimal

from db_config import db
from models.catalogo_ot import CatalogoOT
from models.produccion import (
    AvanceElementoProceso,
    ComponenteOT,
    ImportacionPackingList,
    ProcesoProduccion,
    RutaProduccion,
)
from models.usuario import RolSistema, Usuario


def _v2_payload(ids, detected_ot='2026-TEST'):
    return {
        'pl_id': ids['packing_list'],
        'expected_version': 1,
        'import_meta': {
            'schema_version': 2,
            'archivo': 'OT_2026-TEST.xlsx',
            'hoja': 'PACKING LIST',
            'site': 'SITE NORTE',
            'ot_detectadas': [detected_ot],
            'ruta_codigo': 'GALVANIZADO',
            'advertencias': [],
        },
        'componentes': [{
            'marca': 'V2-001',
            'cantidad': 3,
            'descripcion': 'Soporte galvanizado',
            'tipo': 'fabricacion',
            'categoria': 'FABRICACION',
            'unidad': 'UND',
            'ubicacion': 'SITE NORTE',
            'perfil': 'L 2 X 2',
            'material': 'ASTM A36',
            'longitud': '1250',
            'longitud_mm': 1250,
            'area_unitaria_m2': 1.25,
            'peso_unitario_kg': 4.5,
            'fila_origen': 18,
        }, {
            'marca': 'P-TORRE-01',
            'cantidad': 8,
            'descripcion': 'Pernos para torre',
            'tipo': 'p_torre',
            'categoria': 'PERNERIA',
            'subcategoria': 'TORRE',
            'unidad': 'UND',
            'fila_origen': 42,
        }],
    }


def test_v2_routes_are_seeded_and_exposed(client, login, app):
    login('editor')
    response = client.get('/api/produccion/rutas')

    assert response.status_code == 200, response.get_json()
    payload = response.get_json()
    assert payload['success'] is True
    assert {route['codigo'] for route in payload['rutas']} == {
        'GALVANIZADO',
        'PINTADO',
    }

    galvanized = next(
        route for route in payload['rutas']
        if route['codigo'] == 'GALVANIZADO'
    )
    assert [
        step['proceso']['codigo'] for step in galvanized['procesos']
    ] == ['hab', 'arm', 'sol', 'lim', 'lib', 'gal', 'des']

    with app.app_context():
        assert RolSistema.query.count() == 10
        admin = Usuario.query.filter_by(username='admin').one()
        editor = Usuario.query.filter_by(username='editor').one()
        assert admin.has_role('admin')
        assert {'administrador_sistema', 'produccion_oficina'} <= admin.role_keys
        assert editor.has_role('editor')
        assert editor.has_permission('produccion.editar')
        assert not editor.has_permission('sistema.administrar')


def test_v2_import_persists_rich_items_route_and_traceability(
        app,
        client,
        login,
        ids,
):
    login('editor')
    client.get('/api/produccion/rutas')

    response = client.post(
        '/api/produccion/importar',
        json=_v2_payload(ids),
    )

    assert response.status_code == 200, response.get_json()
    payload = response.get_json()
    assert payload['route']['codigo'] == 'GALVANIZADO'
    assert payload['fabrication_weight_kg'] == 13.5
    assert payload['import_id'] > 0

    with app.app_context():
        fabrication = ComponenteOT.query.filter_by(marca='V2-001').one()
        assert fabrication.categoria == 'FABRICACION'
        assert fabrication.ubicacion == 'SITE NORTE'
        assert fabrication.material == 'ASTM A36'
        assert fabrication.area_total_m2 == Decimal('3.7500')
        assert fabrication.peso_total_kg == Decimal('13.5000')
        assert fabrication.ruta.codigo == 'GALVANIZADO'
        assert fabrication.hab_real is None
        assert fabrication.are_real is None

        supply = ComponenteOT.query.filter_by(marca='P-TORRE-01').one()
        assert supply.categoria == 'PERNERIA'
        assert supply.subcategoria == 'TORRE'
        assert supply.ruta_id is None

        progress = AvanceElementoProceso.query.filter_by(
            componente_id=fabrication.id,
        ).all()
        assert len(progress) == ProcesoProduccion.query.count() == 9
        applicable = {
            row.proceso.codigo for row in progress if row.aplica
        }
        assert applicable == {
            'hab', 'arm', 'sol', 'lim', 'lib', 'gal', 'des'
        }
        assert ImportacionPackingList.query.count() == 1
        assert fabrication.packing_list.site == 'SITE NORTE'

    legacy_components = _v2_payload(ids)['componentes']
    legacy_components[0]['ruta_codigo'] = 'GALVANIZADO'
    legacy_save = client.post(
        '/api/produccion/importar',
        json={
            'pl_id': ids['packing_list'],
            'expected_version': 2,
            'import_meta': {'schema_version': 1},
            'componentes': legacy_components,
        },
    )
    assert legacy_save.status_code == 200, legacy_save.get_json()
    with app.app_context():
        reloaded = ComponenteOT.query.filter_by(marca='V2-001').one()
        assert reloaded.ruta.codigo == 'GALVANIZADO'
        assert len(reloaded.avances_proceso) == 9


def test_v2_import_rejects_another_ot_and_syncs_legacy_progress(
        app,
        client,
        login,
        ids,
):
    login('editor')
    client.get('/api/produccion/rutas')

    mismatch = client.post(
        '/api/produccion/importar',
        json=_v2_payload(ids, detected_ot='2026-0099'),
    )
    assert mismatch.status_code == 400
    assert 'no corresponde a esta OT' in mismatch.get_json()['error']

    imported = client.post(
        '/api/produccion/importar',
        json=_v2_payload(ids),
    )
    assert imported.status_code == 200, imported.get_json()

    with app.app_context():
        component_id = ComponenteOT.query.filter_by(marca='V2-001').one().id

    updated = client.post(
        '/api/produccion/actualizar_celda',
        json={
            'id': component_id,
            'campo': 'hab_real',
            'valor': 2,
            'expected_version': 2,
        },
    )
    assert updated.status_code == 200

    with app.app_context():
        process = ProcesoProduccion.query.filter_by(codigo='hab').one()
        progress = AvanceElementoProceso.query.filter_by(
            componente_id=component_id,
            proceso_id=process.id,
        ).one()
        assert progress.aplica is True
        assert progress.cantidad_completada == 2
        assert progress.fecha_inicio is not None
        assert RutaProduccion.query.count() == 2


def test_process_sequence_auto_adjusts_only_registered_previous_steps(
        app,
        client,
        login,
        ids,
):
    login('editor')

    for field_name, value, version in (
        ('hab_real', 10, 1),
        ('arm_real', 4, 2),
        ('sol_real', 8, 3),
    ):
        response = client.post('/api/produccion/actualizar_celda', json={
            'id': ids['component'],
            'campo': field_name,
            'valor': value,
            'expected_version': version,
        })
        assert response.status_code == 200, response.get_json()

    assert response.get_json()['adjusted_fields'] == {'arm_real': 8}
    with app.app_context():
        component = db.session.get(ComponenteOT, ids['component'])
        assert (component.hab_real, component.arm_real, component.sol_real) == (10, 8, 8)


def test_process_sequence_allows_skipping_an_unregistered_step(
        app,
        client,
        login,
        ids,
):
    login('editor')
    first = client.post('/api/produccion/actualizar_celda', json={
        'id': ids['component'],
        'campo': 'hab_real',
        'valor': 8,
        'expected_version': 1,
    })
    assert first.status_code == 200
    sold = client.post('/api/produccion/actualizar_celda', json={
        'id': ids['component'],
        'campo': 'sol_real',
        'valor': 8,
        'expected_version': 2,
    })
    assert sold.status_code == 200, sold.get_json()
    assert sold.get_json()['adjusted_fields'] == {}
    with app.app_context():
        component = db.session.get(ComponenteOT, ids['component'])
        assert component.arm_real is None


def test_component_real_period_is_validated_and_serialized(
        app,
        client,
        login,
        ids,
):
    login('editor')
    start = client.post('/api/produccion/actualizar_celda', json={
        'id': ids['component'],
        'campo': 'fecha_inicio_real',
        'valor': '2026-08-20',
        'expected_version': 1,
    })
    assert start.status_code == 200
    invalid_end = client.post('/api/produccion/actualizar_celda', json={
        'id': ids['component'],
        'campo': 'fecha_termino_real',
        'valor': '2026-08-19',
        'expected_version': 2,
    })
    assert invalid_end.status_code == 400
    valid_end = client.post('/api/produccion/actualizar_celda', json={
        'id': ids['component'],
        'campo': 'fecha_termino_real',
        'valor': '2026-08-22',
        'expected_version': 2,
    })
    assert valid_end.status_code == 200
    with app.app_context():
        payload = db.session.get(ComponenteOT, ids['component']).to_dict()
        assert payload['fecha_inicio_real'] == '2026-08-20'
        assert payload['fecha_termino_real'] == '2026-08-22'


def test_v2_import_accepts_confirmed_stale_header_when_filename_matches_ot(
        app,
        client,
        login,
        ids,
):
    with app.app_context():
        work_order = db.session.get(CatalogoOT, ids['ot'])
        work_order.ot = '2026-0098'
        db.session.commit()

    login('editor')
    client.get('/api/produccion/rutas')
    payload = _v2_payload(ids, detected_ot='2025-0098')
    payload['import_meta'].update({
        'archivo': 'Packing List General OT 26-098.xlsx',
        'ot_diferencia_confirmada': True,
    })

    response = client.post('/api/produccion/importar', json=payload)

    assert response.status_code == 200, response.get_json()
    with app.app_context():
        import_record = ImportacionPackingList.query.one()
        assert import_record.ot_detectada == '2025-0098'
        assert any(
            'Se confirmó manualmente' in warning
            for warning in import_record.advertencias
        )
