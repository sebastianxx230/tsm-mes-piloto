from pathlib import Path

from models.produccion import BitacoraOT, ComponenteOT
from models.usuario import Usuario
from werkzeug.security import check_password_hash


def test_report_routes_require_authentication(client, ids):
    page_routes = [
        ('get', f"/reporte/seleccionar/{ids['ot']}"),
        ('post', '/reporte/generar'),
    ]

    for method, route in page_routes:
        response = getattr(client, method)(route)
        assert response.status_code == 302
        assert response.headers['Location'].startswith('/?next=')

    for route in (
        f"/reporte/api/fotos/{ids['ot']}",
        f"/reporte/api/fotos/{ids['ot']}/conteo",
    ):
        response = client.get(route, headers={'Accept': 'application/json'})
        assert response.status_code == 401
        assert response.is_json
        assert response.get_json()['code'] == 'authentication_required'


def test_viewer_cannot_modify_production_or_generate_reports(client, login, ids):
    login('viewer')
    requests = [
        client.post(
            '/api/produccion/packing_lists',
            json={'ot_id': ids['ot'], 'nombre': 'NO PERMITIDA'},
        ),
        client.post(
            '/api/produccion/packing_lists/reordenar',
            json={'orden': [ids['packing_list']]},
        ),
        client.post(
            '/api/produccion/importar',
            json={'pl_id': ids['packing_list'], 'componentes': [{'marca': 'X'}]},
        ),
        client.post(
            '/api/produccion/actualizar_celda',
            json={'id': ids['component'], 'campo': 'alerta', 'valor': True},
        ),
        client.post(
            '/api/mensajes/enviar',
            json={'ot_id': ids['ot'], 'mensaje': 'No permitido'},
        ),
        client.post(
            '/reporte/generar',
            data={'ot_id': ids['ot'], 'selected_images': 'PROCESO::imagen'},
        ),
    ]

    assert {response.status_code for response in requests} == {403}


def test_editor_cannot_update_forbidden_component_fields(app, client, login, ids):
    login('editor')

    response = client.post(
        '/api/produccion/actualizar_celda',
        json={
            'id': ids['component'],
            'campo': 'pl_id',
            'valor': ids['packing_list'] + 100,
        },
    )

    assert response.status_code == 400
    assert response.get_json()['success'] is False
    with app.app_context():
        component = db_get_component(ids['component'])
        assert component.pl_id == ids['packing_list']


def test_editor_can_update_allowed_component_field(app, client, login, ids):
    login('editor')

    response = client.post(
        '/api/produccion/actualizar_celda',
        json={
            'id': ids['component'],
            'campo': 'alerta',
            'valor': True,
            'expected_version': 1,
        },
    )

    assert response.status_code == 200
    assert response.get_json() == {'success': True, 'version': 2}
    with app.app_context():
        assert db_get_component(ids['component']).alerta is True
        audit = BitacoraOT.query.filter_by(ot_id=ids['ot'], tipo='audit').one()
        assert audit.usuario_nombre == 'Editor'
        assert 'alerta' in audit.mensaje


def test_progress_cannot_exceed_component_quantity(client, login, ids):
    login('editor')

    response = client.post(
        '/api/produccion/actualizar_celda',
        json={
            'id': ids['component'],
            'campo': 'hab_real',
            'valor': 11,
            'expected_version': 1,
        },
    )

    assert response.status_code == 400
    assert 'entre -1 y 10' in response.get_json()['error']


def test_report_image_count_is_limited(client, login, ids):
    login('editor')
    selected_images = [f'PROCESO::imagen_{index}' for index in range(31)]

    response = client.post(
        '/reporte/generar',
        data={'ot_id': ids['ot'], 'selected_images': selected_images},
    )

    assert response.status_code == 413


def test_report_rejects_malformed_image_identifiers(client, login, ids):
    login('editor')

    response = client.post(
        '/reporte/generar',
        data={
            'ot_id': ids['ot'],
            'selected_images': 'PROCESO::<script>alert(1)</script>::PROCESO',
        },
    )

    assert response.status_code == 400


def test_chat_uses_text_content_instead_of_html_insertion():
    source = Path('static/js/produccion.js').read_text(encoding='utf-8-sig')

    assert "bubble.textContent = String(msg.mensaje ?? '');" in source
    assert "history.insertAdjacentHTML('beforeend', html)" not in source


def test_viewer_is_redirected_to_dedicated_tracking_view(client, login, ids):
    login('viewer')

    response = client.get(f"/produccion/{ids['ot']}")
    assert response.status_code == 302
    assert response.headers['Location'].endswith(f"/seguimiento/{ids['ot']}")

    tracking = client.get(f"/seguimiento/{ids['ot']}")
    assert tracking.status_code == 200
    page = tracking.get_data(as_text=True)
    assert 'Vista de seguimiento' in page
    assert 'Avance por proceso' in page
    assert 'Avance por lote' in page
    assert 'Personal registrado' in page
    assert 'id="tracking-activity-drawer"' in page
    assert 'id="tracking-messages-tab"' in page
    assert 'id="tracking-history-tab"' in page
    assert 'Subir Excel' not in page
    assert 'matriz-body' not in page
    assert 'Abrir producción' not in page


def test_editor_keeps_production_controls(client, login, ids):
    login('editor')

    response = client.get(f"/produccion/{ids['ot']}")

    assert response.status_code == 200
    assert 'Subir Excel' in response.get_data(as_text=True)
    assert 'Modo lectura' not in response.get_data(as_text=True)


def test_viewer_catalog_uses_explicit_read_only_actions(client, login):
    login('viewer')

    response = client.get('/catalogo-ot')
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'Ver seguimiento' in page
    assert '/seguimiento/' in page
    assert '/reporte/seleccionar/' not in page
    assert 'Documentación' not in page


def test_viewer_cannot_open_photographic_report(client, login, ids):
    login('viewer')

    gallery = client.get(f"/reporte/seleccionar/{ids['ot']}")
    photos_api = client.get(f"/reporte/api/fotos/{ids['ot']}")
    count_api = client.get(f"/reporte/api/fotos/{ids['ot']}/conteo")

    assert gallery.status_code == 403
    assert photos_api.status_code == 403
    assert count_api.status_code == 403


def test_tracking_view_summarizes_progress_personnel_and_log(app, client, login, ids):
    with app.app_context():
        from db_config import db

        component = db_get_component(ids['component'])
        for field_name in (
            'hab_real', 'arm_real', 'sol_real',
            'lim_real', 'lib_real', 'gal_real',
        ):
            setattr(component, field_name, 5)
        component.operario = 'hab:Ana Operaria|arm:Ana Operaria'
        db.session.add(BitacoraOT(
            ot_id=ids['ot'],
            usuario_nombre='Supervisor',
            mensaje='Avance validado en planta.',
        ))
        db.session.commit()

    login('viewer')
    response = client.get(f"/seguimiento/{ids['ot']}")
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert '50.0%' in page
    assert 'Ana Operaria' in page
    assert 'Avance validado en planta.' in page

    tracking = client.get(f"/api/seguimiento/{ids['ot']}")
    assert tracking.status_code == 200
    personnel = tracking.get_json()['personnel']
    assert len(personnel) == 1
    assert personnel[0]['name'] == 'Ana Operaria'
    assert personnel[0]['component_count'] == 1
    assert personnel[0]['elements'] == [{
        'id': ids['component'],
        'code': 'TEST-001',
        'brand': 'TEST-001',
        'description': 'Componente de prueba',
        'lot': 'PL DE PRUEBA',
        'processes': 'Armado, Habilitado',
    }]


def test_saved_production_personnel_is_returned_by_tracking(client, login, ids):
    login('editor')

    first_save = client.post(
        '/api/produccion/actualizar_celda',
        json={
            'id': ids['component'],
            'campo': 'operario',
            'valor': 'hab:Ana Operaria',
            'expected_version': 1,
        },
    )
    assert first_save.status_code == 200

    second_save = client.post(
        '/api/produccion/actualizar_celda',
        json={
            'id': ids['component'],
            'campo': 'operario',
            'valor': 'hab:Ana Operaria|arm:Ana Operaria',
            'expected_version': first_save.get_json()['version'],
        },
    )
    assert second_save.status_code == 200

    tracking = client.get(f"/api/seguimiento/{ids['ot']}")
    assert tracking.status_code == 200
    personnel = tracking.get_json()['personnel']
    assert [person['name'] for person in personnel] == ['Ana Operaria']
    assert personnel[0]['processes'] == 'Armado, Habilitado'


def test_messages_and_audit_history_are_returned_separately(app, client, login, ids):
    with app.app_context():
        from db_config import db

        db.session.add_all([
            BitacoraOT(
                ot_id=ids['ot'],
                usuario_nombre='Coordinador',
                mensaje='Confirmar fecha de despacho.',
                tipo='manual',
            ),
            BitacoraOT(
                ot_id=ids['ot'],
                usuario_nombre='Editor',
                mensaje='Actualizó avance armado de 0 a 5.',
                tipo='audit',
            ),
        ])
        db.session.commit()

    login('viewer')
    messages = client.get(f"/api/mensajes/{ids['ot']}")
    tracking = client.get(f"/api/seguimiento/{ids['ot']}")

    assert messages.status_code == 200
    assert [item['mensaje'] for item in messages.get_json()] == [
        'Confirmar fecha de despacho.',
    ]
    assert tracking.status_code == 200
    payload = tracking.get_json()
    assert [item['mensaje'] for item in payload['manual_messages']] == [
        'Confirmar fecha de despacho.',
    ]
    assert [item['mensaje'] for item in payload['audit_events']] == [
        'Actualizó avance armado de 0 a 5.',
    ]


def test_audit_event_cannot_be_deleted_from_messages(app, client, login, ids):
    with app.app_context():
        from db_config import db

        audit = BitacoraOT(
            ot_id=ids['ot'],
            usuario_nombre='Editor',
            mensaje='Evento protegido.',
            tipo='audit',
        )
        db.session.add(audit)
        db.session.commit()
        audit_id = audit.id

    login('admin')
    response = client.delete(f'/api/mensajes/eliminar/{audit_id}')

    assert response.status_code == 403
    with app.app_context():
        assert db.session.get(BitacoraOT, audit_id) is not None


def test_tracking_refreshes_silently_and_pauses_when_hidden():
    source = Path('static/js/seguimiento.js').read_text(encoding='utf-8')

    assert 'config.refreshIntervalMs || 15000' in source
    assert 'window.setInterval(refreshTracking, refreshIntervalMs);' in source
    assert 'if (document.hidden || refreshInProgress' in source
    assert "document.addEventListener('visibilitychange'" in source
    assert "cache: 'no-store'" in source


def test_only_admin_can_open_user_management(client, login):
    for role in ('viewer', 'editor'):
        login(role)
        assert client.get('/admin/usuarios').status_code == 403

    login('admin')
    response = client.get('/admin/usuarios')
    assert response.status_code == 200
    assert 'Gestión de accesos' in response.get_data(as_text=True)


def test_admin_can_create_and_manage_user(app, client, login):
    login('admin')

    created = client.post(
        '/admin/usuarios/crear',
        data={
            'nombre': 'Nuevo Lector',
            'username': 'nuevo.lector',
            'rol': 'viewer',
            'password': 'password-segura',
            'password_confirmation': 'password-segura',
        },
    )
    assert created.status_code == 302

    with app.app_context():
        user = Usuario.query.filter_by(username='nuevo.lector').one()
        user_id = user.id
        assert user.rol == 'viewer'
        assert user.activo is True
        assert check_password_hash(user.password_hash, 'password-segura')

    updated = client.post(
        f'/admin/usuarios/{user_id}/actualizar',
        data={
            'nombre': 'Nuevo Editor',
            'username': 'nuevo.editor',
            'rol': 'editor',
            'activo': '0',
            'new_password': 'password-renovada',
        },
    )
    assert updated.status_code == 302

    with app.app_context():
        user = db_get_user(user_id)
        assert user.nombre == 'Nuevo Editor'
        assert user.username == 'nuevo.editor'
        assert user.rol == 'editor'
        assert user.activo is False
        assert check_password_hash(user.password_hash, 'password-renovada')


def test_admin_cannot_deactivate_own_account(app, client, login, ids):
    login('admin')

    response = client.post(
        f"/admin/usuarios/{ids['users']['admin']}/actualizar",
        data={
            'nombre': 'Admin',
            'username': 'admin',
            'rol': 'admin',
            'activo': '0',
        },
    )
    assert response.status_code == 302

    with app.app_context():
        assert db_get_user(ids['users']['admin']).activo is True


def test_deactivated_user_session_is_rejected(app, client, login, ids):
    login('viewer')
    with app.app_context():
        viewer = db_get_user(ids['users']['viewer'])
        viewer.activo = False
        from db_config import db
        db.session.commit()

    response = client.get('/catalogo-ot')
    assert response.status_code == 302
    assert response.headers['Location'].startswith('/?next=')


def db_get_component(component_id):
    from db_config import db

    return db.session.get(ComponenteOT, component_id)


def db_get_user(user_id):
    from db_config import db

    return db.session.get(Usuario, user_id)
