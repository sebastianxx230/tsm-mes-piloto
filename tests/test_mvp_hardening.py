from pathlib import Path

from app import _normalize_database_url
from models.catalogo_ot import CatalogoOT


def test_health_checks_database(client):
    response = client.get('/health', headers={'X-Request-ID': 'health-test'})

    assert response.status_code == 200
    assert response.get_json() == {'status': 'ok', 'database': 'available'}
    assert response.headers['X-Request-ID'] == 'health-test'


def test_secret_key_has_no_source_fallback():
    source = Path('app.py').read_text(encoding='utf-8-sig')

    assert "os.environ.get('SECRET_KEY')" in source
    assert 'clave-secreta-tsm-produccion-2026' not in source
    assert 'db.create_all()' not in source


def test_database_url_normalizes_common_dashboard_pastes():
    expected = (
        'postgresql://app_user:example@ep-example-pooler.neon.tech/'
        'neondb?sslmode=require&channel_binding=require'
    )

    assert _normalize_database_url(expected) == expected
    assert _normalize_database_url(f"psql '{expected}'") == expected
    assert _normalize_database_url(f'  DATABASE_URL="{expected}"  ') == expected
    assert _normalize_database_url('sqlite:///test.sqlite') == 'sqlite:///test.sqlite'


def test_logout_requires_post_and_clears_session(client, login):
    login('viewer')

    assert client.get('/logout').status_code == 405
    response = client.post('/logout')

    assert response.status_code == 302
    assert client.get('/catalogo-ot').status_code == 302


def test_login_is_rate_limited(client):
    responses = [
        client.post('/', data={'username': 'unknown', 'password': 'wrong'})
        for _ in range(6)
    ]

    assert [response.status_code for response in responses[:5]] == [200] * 5
    assert responses[5].status_code == 429
    assert 'Retry-After' in responses[5].headers


def test_ot_payload_is_fully_validated(client, login):
    login('editor')
    invalid_payloads = [
        None,
        {'modo': 'remove'},
        {
            'modo': 'create',
            'ot': '<script>',
            'cliente': 'Cliente',
            'fecha_iniciado': '2026-07-30',
            'descripcion': '',
            'estado': 'En Proceso',
        },
        {
            'modo': 'create',
            'ot': '2026-0100',
            'cliente': '',
            'fecha_iniciado': '2026-02-30',
            'descripcion': '',
            'estado': 'Finalizada',
        },
    ]

    first = client.post('/catalogo-ot/guardar', data='null', content_type='application/json')
    assert first.status_code == 400

    for payload in invalid_payloads[1:]:
        response = client.post('/catalogo-ot/guardar', json=payload)
        assert response.status_code == 400
        assert response.get_json()['success'] is False


def test_duplicate_ot_is_rejected(client, login):
    login('editor')
    response = client.post('/catalogo-ot/guardar', json={
        'modo': 'create',
        'ot': '2026-TEST',
        'cliente': 'Cliente',
        'fecha_iniciado': '2026-07-30',
        'descripcion': '',
        'estado': 'En Proceso',
    })

    assert response.status_code == 409
    assert 'existe' in response.get_json()['error'].lower()


def test_valid_ot_can_be_created(app, client, login):
    login('editor')
    response = client.post('/catalogo-ot/guardar', json={
        'modo': 'create',
        'ot': '2026-0100',
        'cliente': 'Cliente válido',
        'fecha_iniciado': '2026-07-30',
        'descripcion': 'Estructura de prueba',
        'estado': 'No Empezado',
    })

    assert response.status_code == 200
    with app.app_context():
        assert CatalogoOT.query.filter_by(ot='2026-0100').one().cliente == 'Cliente válido'


def test_catalog_uses_dynamic_lima_date(client, login):
    login('editor')
    response = client.get('/catalogo-ot')
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'dia_actual' not in page
    assert 'data-current-year="true"' in page
    assert 'data-photo-count-url=' in page

    source = Path('static/js/catalogo.js').read_text(encoding='utf-8-sig')
    assert 'currentYearStr' not in source


def test_photo_count_is_deduplicated_and_cached(client, login, ids, monkeypatch):
    import controllers.reporte_fotografico_controller as report_controller

    login('editor')
    report_controller._photo_count_cache.clear()
    calls = {'count': 0}

    monkeypatch.setattr(report_controller, 'get_drive_service', lambda: object())

    def fake_images(_service, ot_code):
        calls['count'] += 1
        assert ot_code == '2026-TEST'
        return True, [{'id': 'a'}, {'id': 'b'}, {'id': 'c'}]

    monkeypatch.setattr(report_controller, 'get_unique_images_for_ot', fake_images)
    url = f"/reporte/api/fotos/{ids['ot']}/conteo"

    first = client.get(url)
    second = client.get(url)

    assert first.status_code == 200
    assert first.get_json()['count'] == 3
    assert first.get_json()['cached'] is False
    assert second.get_json()['cached'] is True
    assert calls['count'] == 1
