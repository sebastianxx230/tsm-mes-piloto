from pathlib import Path

from db_config import db
from models.produccion import ComponenteOT


def test_global_tracking_requires_login(client):
    response = client.get('/api/produccion/buscar_codigo/TEST-001')

    assert response.status_code == 302


def test_global_tracking_keeps_exact_and_prefix_searches_case_insensitive(
    app, client, login, ids
):
    with app.app_context():
        db.session.add_all([
            ComponenteOT(
                pl_id=ids['packing_list'],
                marca='TEST-002',
                cantidad=2,
                descripcion='Segundo elemento',
            ),
            ComponenteOT(
                pl_id=ids['packing_list'],
                marca='OTRA-001',
                cantidad=1,
                descripcion='No debe coincidir',
            ),
        ])
        db.session.commit()

    login('viewer')

    exact = client.get('/api/produccion/buscar_codigo/test-001')
    prefix = client.get('/api/produccion/buscar_codigo/test-')

    assert exact.status_code == 200
    assert [row['marca'] for row in exact.get_json()] == ['TEST-001']
    assert [row['marca'] for row in prefix.get_json()] == ['TEST-001', 'TEST-002']


def test_global_tracking_escapes_sql_wildcards_and_rejects_short_queries(
    client, login
):
    login('viewer')

    wildcard = client.get('/api/produccion/buscar_codigo/%25_')
    too_short = client.get('/api/produccion/buscar_codigo/T')

    assert wildcard.status_code == 200
    assert wildcard.get_json() == []
    assert too_short.status_code == 400
    assert 'al menos 2' in too_short.get_json()['error']


def test_global_tracking_caps_large_responses_and_reports_truncation(
    app, client, login, ids
):
    with app.app_context():
        db.session.add_all([
            ComponenteOT(
                pl_id=ids['packing_list'],
                marca=f'LIM-{index:03d}',
                cantidad=1,
                descripcion='Elemento para probar el límite',
            )
            for index in range(205)
        ])
        db.session.commit()

    login('viewer')
    response = client.get('/api/produccion/buscar_codigo/LIM-')

    assert response.status_code == 200
    assert len(response.get_json()) == 200
    assert response.headers['X-Result-Limit'] == '200'
    assert response.headers['X-Results-Truncated'] == 'true'


def test_global_tracking_ui_uses_element_copy_and_request_controls(client, login):
    login('viewer')
    page = client.get('/catalogo-ot').get_data(as_text=True)
    source = Path('static/js/catalogo.js').read_text(encoding='utf-8-sig')

    assert 'Rastreo global por elemento' in page
    assert 'Rastreo Global de Componentes' not in page
    assert 'AbortController' in source
    assert 'TRACKING_DEBOUNCE_MS = 350' in source
    assert 'X-Results-Truncated' in source
