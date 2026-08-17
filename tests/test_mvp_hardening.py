import re
from pathlib import Path

import controllers.reporte_fotografico_controller as report_controller
from app import _classify_database_error, _normalize_database_url
from db_config import db
from models.catalogo_ot import CatalogoOT


def test_health_checks_database(client):
    response = client.get('/health', headers={'X-Request-ID': 'health-test'})

    assert response.status_code == 200
    assert response.get_json() == {'status': 'ok', 'database': 'available'}
    assert response.headers['X-Request-ID'] == 'health-test'


def test_liveness_does_not_query_database(client, monkeypatch):
    def fail_if_queried(*_args, **_kwargs):
        raise AssertionError('The liveness endpoint must not query PostgreSQL')

    monkeypatch.setattr(db.session, 'execute', fail_if_queried)
    response = client.get('/health/live')

    assert response.status_code == 200
    assert response.get_json() == {'status': 'ok', 'service': 'tsm-mes'}


def test_readiness_alias_checks_database(client):
    response = client.get('/health/ready')

    assert response.status_code == 200
    assert response.get_json() == {'status': 'ok', 'database': 'available'}


def test_https_csrf_keeps_request_logging_and_accepts_same_origin_referrer(
    app,
    client,
    login,
    ids,
    monkeypatch,
):
    previous_enabled = app.config['WTF_CSRF_ENABLED']
    previous_strict = app.config['WTF_CSRF_SSL_STRICT']
    app.config.update(WTF_CSRF_ENABLED=True, WTF_CSRF_SSL_STRICT=True)
    try:
        login('admin')
        page = client.get(
            '/seguimiento/ot/2026-TEST',
            base_url='https://localhost',
        )
        token_match = re.search(
            r'<meta name="csrf-token" content="([^"]+)"',
            page.get_data(as_text=True),
        )
        assert token_match is not None
        csrf_token = token_match.group(1)

        rejected = client.put(
            f'/api/seguimiento/{ids["ot"]}/fotos',
            json={'photos': []},
            headers={'X-CSRFToken': csrf_token},
            base_url='https://localhost',
        )
        assert rejected.status_code == 400
        assert rejected.get_json()['code'] == 'csrf_expired'
        assert rejected.headers['X-Request-ID']

        monkeypatch.setattr(report_controller, 'get_drive_service', lambda: object())
        monkeypatch.setattr(
            report_controller,
            'get_unique_images_for_ot',
            lambda _service, _ot_code: (True, []),
        )
        accepted = client.put(
            f'/api/seguimiento/{ids["ot"]}/fotos',
            json={'photos': []},
            headers={
                'X-CSRFToken': csrf_token,
                'Referer': 'https://localhost/seguimiento/ot/2026-TEST',
            },
            base_url='https://localhost',
        )
        assert accepted.status_code == 200

        report_request = client.post(
            '/reporte/generar',
            data={'csrf_token': csrf_token, 'ot_id': ids['ot']},
            headers={'Referer': 'https://localhost/reporte/seleccionar/1'},
            base_url='https://localhost',
        )
        assert report_request.status_code == 400
        assert 'No se seleccionaron imágenes' in report_request.get_data(as_text=True)
    finally:
        app.config.update(
            WTF_CSRF_ENABLED=previous_enabled,
            WTF_CSRF_SSL_STRICT=previous_strict,
        )


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


def test_database_error_classification_does_not_expose_details():
    assert _classify_database_error(
        RuntimeError('password authentication failed for user "example"')
    ) == 'authentication_failed'
    assert _classify_database_error(
        RuntimeError('could not translate host name "example.invalid"')
    ) == 'dns_failed'
    assert _classify_database_error(
        RuntimeError('invalid dsn: invalid connection option "channel_binding"')
    ) == 'invalid_connection_option'
    assert _classify_database_error(RuntimeError('unexpected database error')) == 'connection_failed'


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


def test_report_image_is_compressed_to_rendered_budget(monkeypatch):
    from PIL import Image
    import controllers.reporte_fotografico_controller as report_controller

    monkeypatch.setattr(report_controller, 'REPORT_OUTPUT_MAX_WIDTH', 640)
    monkeypatch.setattr(report_controller, 'REPORT_OUTPUT_JPEG_QUALITY', 70)
    monkeypatch.setattr(
        report_controller,
        'MAX_REPORT_RENDERED_IMAGE_BYTES',
        80 * 1024,
    )
    image = Image.effect_noise((1400, 1050), 80).convert('RGB')

    encoded, encoded_size = report_controller._prepare_report_image(image)

    assert encoded
    assert encoded_size <= 80 * 1024
