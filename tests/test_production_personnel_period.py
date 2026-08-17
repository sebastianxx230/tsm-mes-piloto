from datetime import date

from db_config import db
from models.produccion import ComponenteOT, PackingList, PersonalProduccion


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
            'fecha_inicio_real': '2026-06-02',
            'fecha_termino_real': '2026-06-18',
            'componentes': [{
                'marca': 'NUEVO-001',
                'cantidad': 4,
                'descripcion': 'Elemento importado',
                'longitud': '1200',
                'tipo': 'fabricacion',
            }],
        },
    )
    assert response.status_code == 200
    assert response.get_json()['pl']['fecha_inicio_real'] == '2026-06-02'
    assert response.get_json()['pl']['fecha_termino_real'] == '2026-06-18'

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
        packing_list = db.session.get(PackingList, ids['packing_list'])
        assert packing_list.fecha_inicio_real == date(2026, 6, 2)
        assert packing_list.fecha_termino_real == date(2026, 6, 18)


def test_real_period_rejects_an_end_before_start(client, login, ids):
    login('editor')
    response = client.put(
        f"/api/produccion/packing_lists/{ids['packing_list']}/periodo",
        json={
            'expected_version': 1,
            'fecha_inicio_real': '2026-08-20',
            'fecha_termino_real': '2026-08-10',
        },
    )
    assert response.status_code == 400
    assert 'anterior' in response.get_json()['error']
