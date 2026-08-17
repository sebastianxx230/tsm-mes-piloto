import io
import mimetypes
import os
import re
import unicodedata
from pathlib import Path

import googleapiclient.http
from googleapiclient.errors import HttpError
from flask import Blueprint, current_app, jsonify, request, send_file, url_for
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from controllers.reporte_fotografico_controller import (
    _list_drive_files,
    ensure_ot_category_folder,
    get_drive_service,
    get_drive_subfolders,
    get_ot_drive_folder,
    upload_drive_file,
)
from db_config import db
from models.catalogo_ot import CatalogoOT
from models.documento_seguimiento import DocumentoSeguimiento
from models.produccion import BitacoraOT
from utils.auth import roles_required


documentos_seguimiento_bp = Blueprint(
    'documentos_seguimiento_bp',
    __name__,
)

DRIVE_ID_PATTERN = re.compile(r'^[A-Za-z0-9_-]{1,150}$')
MAX_DOCUMENT_BYTES = max(
    1024 * 1024,
    int(os.environ.get('MAX_TRACKING_DOCUMENT_BYTES', str(50 * 1024 * 1024))),
    )
MAX_DOCUMENT_UPLOAD_BYTES = max(
    512 * 1024,
    min(
        MAX_DOCUMENT_BYTES,
        int(os.environ.get(
            'MAX_TRACKING_DOCUMENT_UPLOAD_BYTES',
            str(3 * 1024 * 1024),
        )),
    ),
)
IMAGE_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tif', '.tiff',
    '.heic', '.heif', '.svg', '.avif',
}
ALLOWED_DOCUMENT_UPLOAD_EXTENSIONS = {
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.dwg', '.dxf', '.txt', '.csv', '.zip', '.rar',
}
GOOGLE_EXPORTABLE_MIME_TYPES = {
    'application/vnd.google-apps.document',
    'application/vnd.google-apps.spreadsheet',
    'application/vnd.google-apps.presentation',
    'application/vnd.google-apps.drawing',
}
CATEGORY_CONFIG = {
    'planos': {
        'label': 'Planos',
        'env_name': 'DRIVE_PLANOS_FOLDER_NAME',
        'folder_names': (
            'PLANOS',
            'PLANOS_PRODUCCION',
            'PLANOS DE PRODUCCION',
        ),
    },
    'otros': {
        'label': 'Otros documentos',
        'env_name': 'DRIVE_OTROS_DOCUMENTOS_FOLDER_NAME',
        'folder_names': (
            'DOCUMENTOS',
            'OTROS_DOCUMENTOS',
            'OTROS DOCUMENTOS',
        ),
    },
}


def _error(message, status=400):
    return jsonify({'success': False, 'error': message}), status


def _normalize_name(value):
    normalized = unicodedata.normalize('NFKD', str(value or ''))
    normalized = ''.join(
        character for character in normalized
        if not unicodedata.combining(character)
    )
    return re.sub(r'[^A-Z0-9]+', '_', normalized.upper()).strip('_')


def _category_config(category):
    config = CATEGORY_CONFIG.get(category)
    if config is None:
        raise ValueError('La categoría de documentos no es válida.')
    return config


def _expected_folder_names(category):
    config = _category_config(category)
    custom_name = str(os.environ.get(config['env_name']) or '').strip()
    names = list(config['folder_names'])
    if custom_name:
        names.insert(0, custom_name)
    return tuple(dict.fromkeys(names))


def _find_ot_folder(service, ot_code):
    """Localiza la carpeta de la OT dentro del contenedor anual configurado."""
    return get_ot_drive_folder(service, ot_code)


def _matching_category_folders(service, ot_folder_id, category):
    expected = {
        _normalize_name(name)
        for name in _expected_folder_names(category)
    }
    return [
        folder
        for folder in get_drive_subfolders(service, ot_folder_id)
        if _normalize_name(folder.get('name')) in expected
    ]

def _is_allowed_document(file_data):
    name = str(file_data.get('name') or '').strip()
    mime_type = str(file_data.get('mimeType') or '').strip().lower()
    extension = Path(name).suffix.lower()

    if not name or not file_data.get('id'):
        return False
    if mime_type.startswith('image/') or extension in IMAGE_EXTENSIONS:
        return False
    if mime_type in {
        'application/vnd.google-apps.folder',
        'application/vnd.google-apps.shortcut',
    }:
        return False
    return True


def _is_previewable(file_data):
    mime_type = str(file_data.get('mimeType') or '')
    name = str(file_data.get('name') or '')
    return (
            mime_type == 'application/pdf'
            or mime_type in GOOGLE_EXPORTABLE_MIME_TYPES
            or name.lower().endswith('.pdf')
    )


def _safe_size(value):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _read_document_upload(file_storage):
    original_name = Path(str(file_storage.filename or '')).name.strip()
    extension = Path(original_name).suffix.lower()
    if not original_name or extension not in ALLOWED_DOCUMENT_UPLOAD_EXTENSIONS:
        raise ValueError(
            'Sube un PDF, documento de Office, DWG, DXF, TXT, CSV, ZIP o RAR.'
        )

    safe_name = secure_filename(original_name)
    if not safe_name:
        raise ValueError('El nombre del archivo no es válido.')

    content = file_storage.stream.read(MAX_DOCUMENT_UPLOAD_BYTES + 1)
    if not content:
        raise ValueError('El archivo está vacío.')
    if len(content) > MAX_DOCUMENT_UPLOAD_BYTES:
        raise OverflowError(
            f'El archivo supera el límite de '
            f'{MAX_DOCUMENT_UPLOAD_BYTES // (1024 * 1024)} MB.'
        )

    guessed_mime = mimetypes.guess_type(safe_name)[0]
    mime_type = str(file_storage.mimetype or guessed_mime or '').strip()
    if not mime_type or mime_type == 'application/octet-stream':
        mime_type = guessed_mime or 'application/octet-stream'
    return safe_name, mime_type, content


def _list_documents_in_folder(service, folder_id):
    query = (
        f"'{folder_id}' in parents and "
        "mimeType!='application/vnd.google-apps.folder' and trashed=false"
    )
    return _list_drive_files(
        service,
        query,
        'id, name, mimeType, size, modifiedTime, parents',
        order_by='name',
    )


def _list_candidates_for_ot(service, ot_code, category):
    """Lista la carpeta temática nueva y conserva la raíz como respaldo legado."""
    ot_folder_id, ot_folder_name = _find_ot_folder(service, ot_code)
    if not ot_folder_id:
        return {
            'folder_found': False,
            'ot_folder_found': False,
            'category_folder_found': False,
            'folder_id': None,
            'folder_name': None,
            'source_folders': [],
            'files': [],
        }

    category_folders = _matching_category_folders(
        service,
        ot_folder_id,
        category,
    )
    if category_folders:
        source_folders = [
            {
                'id': folder.get('id'),
                'name': folder.get('name'),
                'location_label': folder.get('name') or 'Subcarpeta',
            }
            for folder in category_folders
            if folder.get('id')
        ]
    else:
        source_folders = [
            {
                'id': ot_folder_id,
                'name': ot_folder_name,
                'location_label': 'Carpeta principal de la OT (estructura anterior)',
            },
        ]

    candidates = []
    seen_ids = set()
    for source in source_folders:
        for file_data in _list_documents_in_folder(service, source['id']):
            if not _is_allowed_document(file_data):
                continue
            file_id = file_data.get('id')
            if not file_id or file_id in seen_ids:
                continue
            seen_ids.add(file_id)
            candidates.append({
                'id': file_id,
                'name': file_data['name'],
                'mime_type': (
                        file_data.get('mimeType')
                        or 'application/octet-stream'
                ),
                'size': _safe_size(file_data.get('size')),
                'modified_time': file_data.get('modifiedTime'),
                'previewable': _is_previewable(file_data),
                'folder_id': source['id'],
                'folder_name': source['name'],
                'location_label': source['location_label'],
            })

    candidates.sort(key=lambda item: str(item.get('name') or '').casefold())
    return {
        'folder_found': True,
        'ot_folder_found': True,
        'category_folder_found': bool(category_folders),
        'folder_id': ot_folder_id,
        'folder_name': ot_folder_name,
        'source_folders': source_folders,
        'files': candidates,
    }

def _document_payload(document):
    if document is None:
        return None
    return {
        'id': document.id,
        'drive_file_id': document.drive_file_id,
        'category': document.categoria,
        'name': document.nombre,
        'mime_type': document.mime_type,
        'size': document.tamano,
        'folder_name': document.carpeta_nombre,
        'previewable': document.es_previsualizable,
        'preview_url': (
            url_for(
                'documentos_seguimiento_bp.previsualizar_documento',
                document_id=document.id,
            )
            if document.es_previsualizable
            else None
        ),
        'download_url': url_for(
            'documentos_seguimiento_bp.descargar_documento',
            document_id=document.id,
        ),
        'updated_at': (
            document.fecha_actualizacion.isoformat()
            if document.fecha_actualizacion
            else None
        ),
    }


def _get_selected_documents(ot_id):
    documents = DocumentoSeguimiento.query.filter_by(ot_id=ot_id).all()
    by_category = {document.categoria: document for document in documents}
    return {
        category: _document_payload(by_category.get(category))
        for category in CATEGORY_CONFIG
    }


@documentos_seguimiento_bp.get(
    '/api/seguimiento/<int:ot_id>/documentos'
)
@login_required
def listar_documentos(ot_id):
    if db.session.get(CatalogoOT, ot_id) is None:
        return _error('La OT no existe.', 404)
    return jsonify({
        'success': True,
        'documents': _get_selected_documents(ot_id),
    })


@documentos_seguimiento_bp.get(
    '/api/seguimiento/<int:ot_id>/documentos/<category>/candidatos'
)
@login_required
@roles_required('admin')
def listar_candidatos(ot_id, category):
    try:
        config = _category_config(category)
    except ValueError as error:
        return _error(str(error), 404)

    ot = db.session.get(CatalogoOT, ot_id)
    if ot is None:
        return _error('La OT no existe.', 404)

    service = get_drive_service()
    if service is None:
        return _error('No fue posible conectar con Google Drive.', 503)

    try:
        result = _list_candidates_for_ot(service, str(ot.ot).strip(), category)
        return jsonify({
            'success': True,
            'category': category,
            'label': config['label'],
            'expected_folders': list(_expected_folder_names(category)),
            **result,
        })
    except Exception:
        current_app.logger.exception(
            'tracking_document_candidates_failed',
            extra={'ot_id': ot_id, 'category': category},
        )
        return _error('No fue posible consultar los archivos de Drive.', 502)


@documentos_seguimiento_bp.post(
    '/api/seguimiento/<int:ot_id>/documentos/<category>/subir'
)
@login_required
@roles_required('admin')
def subir_documento(ot_id, category):
    try:
        config = _category_config(category)
    except ValueError as error:
        return _error(str(error), 404)

    ot = db.session.get(CatalogoOT, ot_id)
    if ot is None or ot.archivado:
        return _error('La OT no existe.', 404)

    file_storage = request.files.get('file')
    if file_storage is None:
        return _error('Selecciona un archivo para subir.')

    try:
        filename, mime_type, content = _read_document_upload(file_storage)
    except OverflowError as error:
        return _error(str(error), 413)
    except ValueError as error:
        return _error(str(error))

    service = get_drive_service()
    if service is None:
        return _error('No fue posible conectar con Google Drive.', 503)

    try:
        folder = ensure_ot_category_folder(
            service,
            str(ot.ot).strip(),
            config['folder_names'][0],
        )
        uploaded = upload_drive_file(
            service,
            folder['category_folder_id'],
            filename,
            mime_type,
            content,
        )

        try:
            db.session.add(BitacoraOT(
                ot_id=ot_id,
                usuario_id=current_user.id,
                usuario_nombre=getattr(current_user, 'nombre', 'Administrador'),
                mensaje=(
                    f'Subió {filename} a la carpeta '
                    f'{folder["category_folder_name"]} de Google Drive.'
                ),
                tipo='audit',
            ))
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception(
                'tracking_document_upload_audit_failed',
                extra={'ot_id': ot_id, 'category': category},
            )

        return jsonify({
            'success': True,
            'file': {
                'id': uploaded['id'],
                'name': uploaded.get('name') or filename,
                'mime_type': uploaded.get('mimeType') or mime_type,
                'size': _safe_size(uploaded.get('size')) or len(content),
                'modified_time': uploaded.get('modifiedTime'),
                'previewable': _is_previewable(uploaded),
                'folder_id': folder['category_folder_id'],
                'folder_name': folder['category_folder_name'],
                'location_label': folder['category_folder_name'],
            },
        }), 201
    except HttpError as error:
        status = int(getattr(getattr(error, 'resp', None), 'status', 0) or 0)
        current_app.logger.warning(
            'tracking_document_drive_upload_rejected',
            extra={'ot_id': ot_id, 'category': category, 'status': status},
        )
        if status in {401, 403}:
            return _error(
                'La cuenta de servicio necesita permiso de Editor en la carpeta de Drive.',
                403,
            )
        return _error('Google Drive rechazó la subida del archivo.', 502)
    except ValueError as error:
        return _error(str(error), 400)
    except Exception:
        current_app.logger.exception(
            'tracking_document_upload_failed',
            extra={'ot_id': ot_id, 'category': category},
        )
        return _error('No fue posible subir el archivo a Google Drive.', 502)


@documentos_seguimiento_bp.put(
    '/api/seguimiento/<int:ot_id>/documentos/<category>'
)
@login_required
@roles_required('admin')
def guardar_documento(ot_id, category):
    try:
        config = _category_config(category)
    except ValueError as error:
        return _error(str(error), 404)

    ot = db.session.get(CatalogoOT, ot_id)
    if ot is None:
        return _error('La OT no existe.', 404)

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _error('La selección enviada no es válida.')

    raw_file_id = payload.get('file_id')
    file_id = str(raw_file_id or '').strip()
    selected = DocumentoSeguimiento.query.filter_by(
        ot_id=ot_id,
        categoria=category,
    ).one_or_none()

    if not file_id:
        if selected is not None:
            previous_name = selected.nombre
            db.session.delete(selected)
            db.session.add(BitacoraOT(
                ot_id=ot_id,
                usuario_id=current_user.id,
                usuario_nombre=getattr(current_user, 'nombre', 'Administrador'),
                mensaje=f'Retiró {previous_name} de {config["label"]}.',
                tipo='audit',
            ))
            db.session.commit()
        return jsonify({
            'success': True,
            'document': None,
        })

    if not DRIVE_ID_PATTERN.fullmatch(file_id):
        return _error('El identificador del archivo no es válido.')

    service = get_drive_service()
    if service is None:
        return _error('No fue posible conectar con Google Drive.', 503)

    try:
        result = _list_candidates_for_ot(service, str(ot.ot).strip(), category)
        candidate = next(
            (
                file_data for file_data in result['files']
                if file_data['id'] == file_id
            ),
            None,
        )
        if candidate is None:
            return _error(
                'El archivo no pertenece a la carpeta permitida o es una imagen.',
                400,
            )

        if selected is None:
            selected = DocumentoSeguimiento(
                ot_id=ot_id,
                categoria=category,
            )
            db.session.add(selected)

        selected.drive_file_id = candidate['id']
        selected.drive_folder_id = candidate['folder_id']
        selected.nombre = candidate['name']
        selected.mime_type = candidate['mime_type']
        selected.tamano = candidate['size']
        selected.carpeta_nombre = candidate['folder_name']
        selected.actualizado_por_id = current_user.id

        db.session.add(BitacoraOT(
            ot_id=ot_id,
            usuario_id=current_user.id,
            usuario_nombre=getattr(current_user, 'nombre', 'Administrador'),
            mensaje=(
                f'Publicó {candidate["name"]} en {config["label"]}.'
            ),
            tipo='audit',
        ))
        db.session.commit()
        return jsonify({
            'success': True,
            'document': _document_payload(selected),
        })
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            'tracking_document_save_failed',
            extra={'ot_id': ot_id, 'category': category},
        )
        return _error('No fue posible guardar el archivo seleccionado.', 500)


def _download_filename(name, mime_type):
    """Devuelve un nombre de descarga seguro y con extensión reconocible."""
    raw_name = Path(str(name or 'documento')).name.strip() or 'documento'
    suffix = Path(raw_name).suffix.lower()
    normalized_mime = str(mime_type or '').lower()

    if normalized_mime == 'application/pdf' and suffix != '.pdf':
        return f'{raw_name}.pdf'

    return raw_name


def _load_drive_file(document):
    service = get_drive_service()
    if service is None:
        raise RuntimeError('No fue posible conectar con Google Drive.')

    metadata = service.files().get(
        fileId=document.drive_file_id,
        supportsAllDrives=True,
        fields='id, name, mimeType, size, parents, trashed',
    ).execute()

    if metadata.get('trashed'):
        raise FileNotFoundError('El archivo fue eliminado de Drive.')
    if document.drive_folder_id not in (metadata.get('parents') or []):
        raise PermissionError('El archivo ya no está en la carpeta permitida.')
    if not _is_allowed_document(metadata):
        raise PermissionError('El archivo no es un documento permitido.')

    declared_size = _safe_size(metadata.get('size'))
    if declared_size is not None and declared_size > MAX_DOCUMENT_BYTES:
        raise ValueError('El archivo supera el tamaño permitido.')

    mime_type = str(metadata.get('mimeType') or 'application/octet-stream')
    if mime_type in GOOGLE_EXPORTABLE_MIME_TYPES:
        media_request = service.files().export_media(
            fileId=document.drive_file_id,
            mimeType='application/pdf',
        )
        output_mime_type = 'application/pdf'
        output_name = _download_filename(
            Path(metadata.get('name') or document.nombre).stem,
            output_mime_type,
        )
    else:
        media_request = service.files().get_media(
            fileId=document.drive_file_id,
            supportsAllDrives=True,
        )
        output_name = metadata.get('name') or document.nombre
        output_mime_type = (
            'application/pdf'
            if mime_type == 'application/pdf'
               or str(output_name).lower().endswith('.pdf')
            else mime_type
        )
        output_name = _download_filename(output_name, output_mime_type)

    buffer = io.BytesIO()
    downloader = googleapiclient.http.MediaIoBaseDownload(buffer, media_request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
        if buffer.tell() > MAX_DOCUMENT_BYTES:
            raise ValueError('El archivo supera el tamaño permitido.')
    buffer.seek(0)
    return buffer, output_mime_type, output_name


@documentos_seguimiento_bp.get(
    '/api/seguimiento/documentos/<int:document_id>/contenido'
)
@login_required
def previsualizar_documento(document_id):
    document = db.session.get(DocumentoSeguimiento, document_id)
    if document is None:
        return _error('El documento no existe.', 404)
    if not document.es_previsualizable:
        return _error('La vista interna está disponible únicamente para PDF.', 415)

    try:
        buffer, mime_type, output_name = _load_drive_file(document)
        if mime_type != 'application/pdf':
            return _error('La vista interna está disponible únicamente para PDF.', 415)
        response = send_file(
            buffer,
            mimetype='application/pdf',
            download_name=output_name,
            as_attachment=False,
            conditional=True,
        )
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response
    except FileNotFoundError as error:
        return _error(str(error), 404)
    except PermissionError as error:
        return _error(str(error), 403)
    except ValueError as error:
        return _error(str(error), 413)
    except Exception:
        current_app.logger.exception(
            'tracking_document_preview_failed',
            extra={'document_id': document_id},
        )
        return _error('No fue posible abrir el documento.', 502)


@documentos_seguimiento_bp.get(
    '/api/seguimiento/documentos/<int:document_id>/descargar'
)
@login_required
def descargar_documento(document_id):
    document = db.session.get(DocumentoSeguimiento, document_id)
    if document is None:
        return _error('El documento no existe.', 404)

    try:
        buffer, mime_type, output_name = _load_drive_file(document)
        return send_file(
            buffer,
            mimetype=mime_type,
            download_name=output_name,
            as_attachment=True,
            conditional=True,
        )
    except FileNotFoundError as error:
        return _error(str(error), 404)
    except PermissionError as error:
        return _error(str(error), 403)
    except ValueError as error:
        return _error(str(error), 413)
    except Exception:
        current_app.logger.exception(
            'tracking_document_download_failed',
            extra={'document_id': document_id},
        )
        return _error('No fue posible descargar el documento.', 502)
