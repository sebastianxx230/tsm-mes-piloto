import controllers.reporte_fotografico_controller as report_controller
from db_config import db
from models.produccion import FotoSeguimiento


def _mock_drive_gallery(monkeypatch):
    monkeypatch.setattr(report_controller, 'get_drive_service', lambda: object())
    monkeypatch.setattr(
        report_controller,
        'get_unique_images_for_ot',
        lambda _service, _ot: (
            True,
            [
                {'id': 'drive-photo-1', 'name': 'Habilitado 01.jpg'},
                {'id': 'drive-photo-2', 'name': 'Armado 02.jpg'},
            ],
        ),
    )


def test_only_admin_can_publish_tracking_photos(client, login, ids):
    payload = {'photos': [{'id': 'drive-photo-1'}]}

    login('viewer')
    assert client.put(f"/api/seguimiento/{ids['ot']}/fotos", json=payload).status_code == 403

    login('editor')
    assert client.put(f"/api/seguimiento/{ids['ot']}/fotos", json=payload).status_code == 403


def test_admin_publishes_ordered_drive_photos(
    app, client, login, ids, monkeypatch
):
    _mock_drive_gallery(monkeypatch)
    login('admin')

    response = client.put(
        f"/api/seguimiento/{ids['ot']}/fotos",
        json={
            'photos': [
                {'id': 'drive-photo-2'},
                {'id': 'drive-photo-1'},
            ],
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['success'] is True
    assert [photo['drive_file_id'] for photo in payload['photos']] == [
        'drive-photo-2',
        'drive-photo-1',
    ]
    assert all(photo['image_url'].startswith('/seguimiento/fotos/') for photo in payload['photos'])

    with app.app_context():
        saved = (
            FotoSeguimiento.query.filter_by(ot_id=ids['ot'])
            .order_by(FotoSeguimiento.orden.asc())
            .all()
        )
        assert [photo.nombre for photo in saved] == [
            'Armado 02.jpg',
            'Habilitado 01.jpg',
        ]

    login('viewer')
    tracking = client.get(f"/api/seguimiento/{ids['ot']}").get_json()
    assert [photo['drive_file_id'] for photo in tracking['photos']] == [
        'drive-photo-2',
        'drive-photo-1',
    ]


def test_tracking_rejects_photos_outside_the_ot_folder(
    client, login, ids, monkeypatch
):
    _mock_drive_gallery(monkeypatch)
    login('admin')

    response = client.put(
        f"/api/seguimiento/{ids['ot']}/fotos",
        json={'photos': [{'id': 'foreign-drive-photo'}]},
    )

    assert response.status_code == 409
    assert 'ya no pertenece' in response.get_json()['error']


def test_viewer_can_load_only_a_published_tracking_photo(
    app, client, login, ids, monkeypatch
):
    with app.app_context():
        photo = FotoSeguimiento(
            ot_id=ids['ot'],
            drive_file_id='drive-photo-1',
            nombre='Avance.jpg',
            orden=0,
            actualizado_por_id=ids['users']['admin'],
        )
        db.session.add(photo)
        db.session.commit()
        photo_id = photo.id

    monkeypatch.setattr(report_controller, 'get_drive_service', lambda: object())
    monkeypatch.setattr(
        report_controller,
        'download_drive_image',
        lambda _service, _image_id: (b'jpeg-test-content', 'image/jpeg'),
    )
    login('viewer')

    response = client.get(f'/seguimiento/fotos/{photo_id}/imagen')

    assert response.status_code == 200
    assert response.mimetype == 'image/jpeg'
    assert response.data == b'jpeg-test-content'
    assert response.headers['Cache-Control'] == 'private, max-age=3600'
    assert client.get('/seguimiento/fotos/999999/imagen').status_code == 404


def test_tracking_and_production_expose_the_new_photo_workflow(client, login, ids):
    login('admin')

    tracking_page = client.get('/seguimiento/ot/2026-TEST').get_data(as_text=True)
    production_page = client.get(f"/produccion/{ids['ot']}").get_data(as_text=True)

    assert 'Seleccionar fotografías' in tracking_page
    assert 'Fotografías del avance' in tracking_page
    assert 'data-tracking-view="photos"' in tracking_page
    assert 'Seguimiento' in production_page

    login('viewer')
    viewer_page = client.get('/seguimiento/ot/2026-TEST').get_data(as_text=True)
    assert 'Seleccionar fotografías' not in viewer_page
    assert 'Fotografías del avance' in viewer_page
