from db_config import db
from controllers.gestion_ot_controller import _build_tracking_summary
from models.catalogo_ot import CatalogoOT
from models.produccion import ComponenteOT, PackingList


def test_component_updates_require_current_packing_list_version(app, client, login, ids):
    login('editor')

    missing = client.post('/api/produccion/actualizar_celda', json={
        'id': ids['component'],
        'campo': 'alerta',
        'valor': True,
    })
    assert missing.status_code == 428

    saved = client.post('/api/produccion/actualizar_celda', json={
        'id': ids['component'],
        'campo': 'alerta',
        'valor': True,
        'expected_version': 1,
    })
    assert saved.status_code == 200
    assert saved.get_json()['version'] == 2

    stale = client.post('/api/produccion/actualizar_celda', json={
        'id': ids['component'],
        'campo': 'alerta',
        'valor': False,
        'expected_version': 1,
    })
    assert stale.status_code == 409
    assert stale.get_json()['current_version'] == 2
    with app.app_context():
        assert db.session.get(ComponenteOT, ids['component']).alerta is True


def test_work_order_edit_detects_stale_version(client, login):
    login('editor')
    payload = {
        'modo': 'edit',
        'ot': '2026-TEST',
        'cliente': 'Cliente actualizado',
        'fecha_iniciado': '2026-07-30',
        'descripcion': 'Cambio válido',
        'estado': 'En Proceso',
        'expected_version': 1,
    }
    assert client.post('/catalogo-ot/guardar', json=payload).status_code == 200
    stale = client.post('/catalogo-ot/guardar', json=payload)
    assert stale.status_code == 409
    assert stale.get_json()['current_version'] == 2


def test_archiving_work_order_preserves_production_history(app, client, login, ids):
    login('admin')
    response = client.post(
        f"/catalogo-ot/eliminar/{ids['ot']}",
        json={'expected_version': 1},
    )
    assert response.status_code == 200
    assert response.get_json()['archived'] is True

    with app.app_context():
        work_order = db.session.get(CatalogoOT, ids['ot'])
        assert work_order.archivado is True
        assert db.session.get(PackingList, ids['packing_list']) is not None

    catalog = client.get('/catalogo-ot').get_data(as_text=True)
    assert '2026-TEST' not in catalog


def test_archiving_packing_list_preserves_components(app, client, login, ids):
    login('admin')
    response = client.delete(
        f"/api/produccion/packing_lists/{ids['packing_list']}"
    )
    assert response.status_code == 200

    with app.app_context():
        packing_list = db.session.get(PackingList, ids['packing_list'])
        assert packing_list.archivado is True
        assert db.session.get(ComponenteOT, ids['component']) is not None

    listing = client.get(f"/api/produccion/packing_lists/{ids['ot']}")
    assert listing.status_code == 200
    assert listing.get_json() == []


def test_tracking_progress_is_weighted_by_piece_quantity(app, ids):
    with app.app_context():
        first = db.session.get(ComponenteOT, ids['component'])
        first.hab_real = 10
        db.session.add(ComponenteOT(
            pl_id=ids['packing_list'],
            marca='TEST-090',
            cantidad=90,
            descripcion='Lote grande pendiente',
            longitud='1000',
            tipo='fabricacion',
            estado_suministro='No requerido',
        ))
        db.session.commit()

        tracking = _build_tracking_summary(ids['ot'])
        hab = next(process for process in tracking['processes'] if process['key'] == 'hab')
        assert hab['progress'] == 10.0
        assert tracking['overall_progress'] == 1.4
        assert tracking['unit_count'] == 100
