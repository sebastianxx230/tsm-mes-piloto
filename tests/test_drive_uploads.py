import io

import controllers.documentos_seguimiento_controller as document_controller
import controllers.reporte_fotografico_controller as drive_controller


def test_2026_drive_folder_uses_new_prefix_with_legacy_fallback(monkeypatch):
    monkeypatch.setenv('DRIVE_PARENT_FOLDER_ID_2026', 'root-2026')
    requested_names = []

    def fake_folder_lookup(_service, folder_name, parent_id):
        requested_names.append((folder_name, parent_id))
        return 'folder-new' if folder_name == 'OT_2026-0088' else None

    monkeypatch.setattr(
        drive_controller,
        'get_drive_folder_id',
        fake_folder_lookup,
    )

    folder_id, folder_name = drive_controller.get_ot_drive_folder(
        object(),
        '2026-0088',
    )

    assert folder_id == 'folder-new'
    assert folder_name == 'OT_2026-0088'
    assert requested_names == [('OT_2026-0088', 'root-2026')]
    assert drive_controller.drive_ot_folder_names('2026-0088') == (
        'OT_2026-0088',
        '2026-0088',
    )


def test_photos_are_read_only_from_fotografias_when_new_structure_exists(
    monkeypatch,
):
    monkeypatch.setattr(
        drive_controller,
        'get_ot_drive_folder',
        lambda _service, _ot: ('ot-folder', 'OT_2026-0088'),
    )
    monkeypatch.setattr(
        drive_controller,
        'get_drive_subfolders',
        lambda _service, _folder: [
            {'id': 'documents', 'name': 'DOCUMENTOS'},
            {'id': 'photos', 'name': 'FOTOGRAFIAS'},
            {'id': 'plans', 'name': 'PLANOS'},
        ],
    )
    visited = []

    def fake_images(_service, folder_id):
        visited.append(folder_id)
        return [{'id': 'photo-1', 'name': 'avance.jpg'}]

    monkeypatch.setattr(drive_controller, 'get_images_in_folder', fake_images)

    folder_found, photos = drive_controller.get_unique_images_for_ot(
        object(),
        '2026-0088',
    )

    assert folder_found is True
    assert [photo['id'] for photo in photos] == ['photo-1']
    assert visited == ['photos']


def test_admin_uploads_plan_to_canonical_drive_folder(
    client,
    login,
    ids,
    monkeypatch,
):
    monkeypatch.setattr(document_controller, 'get_drive_service', lambda: object())
    monkeypatch.setattr(
        document_controller,
        'ensure_ot_category_folder',
        lambda _service, ot_code, category: {
            'ot_folder_id': 'ot-folder',
            'ot_folder_name': f'OT_{ot_code}',
            'category_folder_id': 'plans-folder',
            'category_folder_name': category,
        },
    )
    uploaded = {}

    def fake_upload(_service, folder_id, filename, mime_type, content):
        uploaded.update({
            'folder_id': folder_id,
            'filename': filename,
            'mime_type': mime_type,
            'content': content,
        })
        return {
            'id': 'uploaded-plan',
            'name': filename,
            'mimeType': mime_type,
            'size': str(len(content)),
            'modifiedTime': '2026-08-17T18:00:00Z',
        }

    monkeypatch.setattr(document_controller, 'upload_drive_file', fake_upload)
    login('admin')

    response = client.post(
        f'/api/seguimiento/{ids["ot"]}/documentos/planos/subir',
        data={'file': (io.BytesIO(b'%PDF-1.4 test'), 'plano-principal.pdf')},
        content_type='multipart/form-data',
    )

    assert response.status_code == 201
    assert response.get_json()['file']['id'] == 'uploaded-plan'
    assert uploaded['folder_id'] == 'plans-folder'
    assert uploaded['filename'] == 'plano-principal.pdf'
    assert uploaded['mime_type'] == 'application/pdf'


def test_admin_uploads_photo_to_fotografias(
    client,
    login,
    ids,
    monkeypatch,
):
    monkeypatch.setattr(drive_controller, 'get_drive_service', lambda: object())
    monkeypatch.setattr(
        drive_controller,
        'ensure_ot_category_folder',
        lambda _service, ot_code, category: {
            'ot_folder_id': 'ot-folder',
            'ot_folder_name': f'OT_{ot_code}',
            'category_folder_id': 'photos-folder',
            'category_folder_name': category,
        },
    )
    monkeypatch.setattr(
        drive_controller,
        'upload_drive_file',
        lambda _service, folder_id, filename, mime_type, content: {
            'id': 'uploaded-photo',
            'name': filename,
            'mimeType': mime_type,
            'size': str(len(content)),
            'parents': [folder_id],
        },
    )
    invalidated = []
    monkeypatch.setattr(
        drive_controller,
        'invalidate_photo_count_cache',
        lambda ot_id: invalidated.append(ot_id),
    )
    login('admin')

    response = client.post(
        f'/api/seguimiento/{ids["ot"]}/fotos/subir',
        data={'file': (io.BytesIO(b'jpeg-test'), 'avance.jpg')},
        content_type='multipart/form-data',
    )

    assert response.status_code == 201
    assert response.get_json()['photo']['id'] == 'uploaded-photo'
    assert invalidated == [ids['ot']]


def test_drive_uploads_remain_admin_only(client, login, ids):
    login('editor')

    photo_response = client.post(
        f'/api/seguimiento/{ids["ot"]}/fotos/subir',
        data={'file': (io.BytesIO(b'jpeg-test'), 'avance.jpg')},
        content_type='multipart/form-data',
    )
    document_response = client.post(
        f'/api/seguimiento/{ids["ot"]}/documentos/otros/subir',
        data={'file': (io.BytesIO(b'%PDF-test'), 'informe.pdf')},
        content_type='multipart/form-data',
    )

    assert photo_response.status_code == 403
    assert document_response.status_code == 403
