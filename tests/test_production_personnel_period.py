from datetime import date

from db_config import db
from models.produccion import ComponenteOT, PersonalProduccion


def test_personnel_directory_normalizes_names_and_assignments(
        app,
        client,
        login,
        ids,
):
    login('editor')

    created = client.post(
        '/api/produccion/personal',
        json={'nombre': 'Álvaro Pérez'},
    )
    assert created.status_code == 201
    assert created.get_json()['created'] is True

    duplicate = client.post(
        '/api/produccion/personal',
        json={'nombre': '  alvaro   perez  '},
    )
    assert duplicate.status_code == 200
    assert duplicate.get_json()['created'] is False
    assert duplicate.get_json()['person']['nombre'] == 'Álvaro Pérez'

    assigned = client.post(
        '/api/produccion/actualizar_celda',
        json={
            'id': ids['component'],
            'campo': 'operario',
            'valor': 'hab:alvaro perez',
            'expected_version': 1,
        },
    )
    assert assigned.status_code == 200

    listing = client.get('/api/produccion/personal')
    assert listing.status_code == 200
    assert [item['nombre'] for item in listing.get_json()['personal']] == [
        'Álvaro Pérez'
    ]

    with app.app_context():
        assert PersonalProduccion.query.count() == 1
        component = db.session.get(ComponenteOT, ids['component'])
        assert component.operario == 'hab:Álvaro Pérez'


def test_import_defaults_new_manufacturing_processes_to_not_applicable(
        app,
        client,
        login,
        ids,
):
    login('editor')
    response = client.post(
        '/api/produccion/importar',
        json={
            'pl_id': ids['packing_list'],
            'expected_version': 1,
            'componentes': [{
                'marca': 'NUEVO-001',
                'cantidad': 4,
                'descripcion': 'Elemento importado',
                'longitud': '1200',
                'tipo': 'fabricacion',
                'fecha_realizacion': '2026-06-18',
            }, {
                'marca': 'NUEVO-002',
                'cantidad': 2,
                'descripcion': 'Elemento sin fecha',
                'longitud': '800',
                'tipo': 'fabricacion',
            }],
        },
    )
    assert response.status_code == 200

    with app.app_context():
        component = ComponenteOT.query.filter_by(marca='NUEVO-001').one()
        assert {
            component.hab_real,
            component.arm_real,
            component.sol_real,
            component.lim_real,
            component.lib_real,
            component.gal_real,
            component.are_real,
            component.pin_real,
        } == {-1}
        assert component.des_real == 0
        assert component.fecha_realizacion == date(2026, 6, 18)
        component_without_date = ComponenteOT.query.filter_by(
            marca='NUEVO-002'
        ).one()
        assert component_without_date.fecha_realizacion is None


def test_component_completion_date_can_be_saved_and_validated(
        app,
        client,
        login,
        ids,
):
    login('editor')
    response = client.post(
        '/api/produccion/actualizar_celda',
        json={
            'id': ids['component'],
            'campo': 'fecha_realizacion',
            'valor': '2026-08-10',
            'expected_version': 1,
        },
    )
    assert response.status_code == 200

    with app.app_context():
        component = db.session.get(ComponenteOT, ids['component'])
        assert component.fecha_realizacion == date(2026, 8, 10)

    response = client.post(
        '/api/produccion/actualizar_celda',
        json={
            'id': ids['component'],
            'campo': 'fecha_realizacion',
            'valor': '10/08/2026',
            'expected_version': 2,
        },
    )
    assert response.status_code == 400
    assert 'AAAA-MM-DD' in response.get_json()['error']
