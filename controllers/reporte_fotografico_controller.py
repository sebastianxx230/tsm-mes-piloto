import base64
import binascii
import concurrent.futures
import datetime
import io
import json
import os
import re
import threading
import time

from db_config import db
from extensions import limiter
from flask import Blueprint, current_app, jsonify, render_template, request
from flask_login import current_user, login_required
from flask_limiter.util import get_remote_address
from utils.auth import roles_required

try:
    from PIL import Image, ImageOps, UnidentifiedImageError
except ImportError:
    Image = None
    ImageOps = None
    UnidentifiedImageError = OSError

import google.oauth2.service_account
import googleapiclient.discovery
import googleapiclient.http

from models.catalogo_ot import CatalogoOT


SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
reporte_bp = Blueprint('reporte_bp', __name__, template_folder='../templates')

IS_VERCEL = bool(os.environ.get('VERCEL'))

MAX_REPORT_IMAGES = max(1, int(os.environ.get('MAX_REPORT_IMAGES', '20')))
MAX_REPORT_LOCAL_IMAGES = max(
    0,
    int(os.environ.get('MAX_REPORT_LOCAL_IMAGES', '4')),
)
MAX_REPORT_IMAGE_BYTES = max(
    256 * 1024,
    int(os.environ.get('MAX_REPORT_IMAGE_BYTES', str(4 * 1024 * 1024))),
)
MAX_REPORT_TOTAL_BYTES = max(
    MAX_REPORT_IMAGE_BYTES,
    int(os.environ.get('MAX_REPORT_TOTAL_BYTES', str(32 * 1024 * 1024))),
)
MAX_REPORT_LOCAL_TOTAL_BYTES = max(
    MAX_REPORT_IMAGE_BYTES,
    int(os.environ.get('MAX_REPORT_LOCAL_TOTAL_BYTES', str(8 * 1024 * 1024))),
)
MAX_REPORT_IMAGE_PIXELS = max(
    1_000_000,
    int(os.environ.get('MAX_REPORT_IMAGE_PIXELS', '16000000')),
)
MAX_REPORT_TEXT_LENGTH = max(
    100,
    int(os.environ.get('MAX_REPORT_TEXT_LENGTH', '500')),
)
REPORT_WORKERS = min(
    4,
    max(1, int(os.environ.get('REPORT_WORKERS', '3'))),
)
REPORT_OUTPUT_MAX_WIDTH = max(
    320,
    int(os.environ.get(
        'REPORT_OUTPUT_MAX_WIDTH',
        '640' if IS_VERCEL else '800',
    )),
)
REPORT_OUTPUT_JPEG_QUALITY = min(
    90,
    max(
        45,
        int(os.environ.get(
            'REPORT_OUTPUT_JPEG_QUALITY',
            '70' if IS_VERCEL else '82',
        )),
    ),
)
MAX_REPORT_RENDERED_IMAGE_BYTES = max(
    128 * 1024,
    int(os.environ.get(
        'MAX_REPORT_RENDERED_IMAGE_BYTES',
        str(380 * 1024 if IS_VERCEL else 2 * 1024 * 1024),
    )),
)
MAX_REPORT_RENDERED_TOTAL_BYTES = max(
    MAX_REPORT_RENDERED_IMAGE_BYTES,
    int(os.environ.get(
        'MAX_REPORT_RENDERED_TOTAL_BYTES',
        str(2400 * 1024 if IS_VERCEL else 20 * 1024 * 1024),
    )),
)
DRIVE_HTTP_TIMEOUT_SECONDS = max(
    5,
    int(os.environ.get('DRIVE_HTTP_TIMEOUT_SECONDS', '25')),
)
REPORT_RATE_LIMIT = os.environ.get('REPORT_RATE_LIMIT', '3 per minute')
ALLOW_PARTIAL_DRIVE_FOLDER_MATCH = os.environ.get(
    'ALLOW_PARTIAL_DRIVE_FOLDER_MATCH',
    'False',
).lower() == 'true'

REPORT_IMAGE_ID_PATTERN = re.compile(r'^[A-Za-z0-9_-]{1,150}$')
LOCAL_IMAGE_ID_PATTERN = re.compile(r'^local_[A-Za-z0-9_-]{1,100}$')
ALLOWED_CLIENT_IMAGE_MIME_TYPES = {
    'image/jpeg',
    'image/png',
    'image/webp',
}

PHOTO_COUNT_CACHE_TTL = max(
    0,
    int(os.environ.get('PHOTO_COUNT_CACHE_TTL', '300')),
)
PHOTO_COUNT_CACHE_MAX_ITEMS = max(
    1,
    int(os.environ.get('PHOTO_COUNT_CACHE_MAX_ITEMS', '500')),
)
_photo_count_cache = {}
_photo_count_cache_lock = threading.Lock()

if Image is not None:
    Image.MAX_IMAGE_PIXELS = MAX_REPORT_IMAGE_PIXELS


def _report_rate_limit_key():
    if current_user.is_authenticated:
        return f'user:{current_user.get_id()}'
    return f'ip:{get_remote_address()}'


def image_dimensions_are_allowed(image):
    width, height = image.size
    return (
        width > 0
        and height > 0
        and width * height <= MAX_REPORT_IMAGE_PIXELS
    )


def get_drive_service():
    try:
        credentials_json = os.environ.get('GOOGLE_CREDENTIALS')
        if credentials_json:
            credential_data = json.loads(credentials_json, strict=False)
            if 'private_key' in credential_data:
                credential_data['private_key'] = credential_data[
                    'private_key'
                ].replace('\\n', '\n')
        else:
            base_dir = os.path.abspath(
                os.path.dirname(os.path.dirname(__file__))
            )
            credentials_path = os.path.join(base_dir, 'credentials.json')
            if not os.path.exists(credentials_path):
                current_app.logger.error('google_credentials_missing')
                return None
            with open(credentials_path, 'r', encoding='utf-8-sig') as file:
                credential_data = json.load(file)

        credentials = (
            google.oauth2.service_account.Credentials.from_service_account_info(
                credential_data,
                scopes=SCOPES,
            )
        )
        service = googleapiclient.discovery.build(
            'drive',
            'v3',
            credentials=credentials,
            cache_discovery=False,
        )
        service_http = getattr(service, '_http', None)
        if service_http is not None:
            service_http.timeout = DRIVE_HTTP_TIMEOUT_SECONDS
        return service
    except Exception:
        current_app.logger.exception('google_drive_client_creation_failed')
        return None


def get_parent_folder_by_ot(ot_code):
    ot_code = str(ot_code).strip()
    parent_2025 = os.environ.get('DRIVE_PARENT_FOLDER_ID_2025')
    parent_2026 = os.environ.get('DRIVE_PARENT_FOLDER_ID_2026')
    parent_default = os.environ.get('DRIVE_PARENT_FOLDER_ID')

    if ot_code.startswith('2025-'):
        return parent_2025 or parent_default
    if ot_code.startswith('2026-'):
        return parent_2026 or parent_default
    return parent_default


def _escape_drive_query_value(value):
    return str(value).replace('\\', '\\\\').replace("'", "\\'")


def _list_drive_files(service, query, field_names, order_by=None):
    """Lista todos los resultados de Drive incluyendo paginación."""
    files = []
    page_token = None

    while True:
        arguments = {
            'q': query,
            'corpora': 'allDrives',
            'supportsAllDrives': True,
            'includeItemsFromAllDrives': True,
            'fields': f'nextPageToken, files({field_names})',
            'pageSize': 1000,
        }
        if order_by:
            arguments['orderBy'] = order_by
        if page_token:
            arguments['pageToken'] = page_token

        response = service.files().list(**arguments).execute()
        files.extend(response.get('files', []))
        page_token = response.get('nextPageToken')
        if not page_token:
            return files


def get_drive_folder_id(service, folder_name, parent_id):
    """Busca una carpeta únicamente dentro del padre configurado."""
    if not parent_id:
        current_app.logger.error(
            'drive_parent_folder_not_configured',
            extra={'folder_name': str(folder_name)},
        )
        return None

    safe_name = _escape_drive_query_value(str(folder_name).strip())
    try:
        exact_query = (
            f"name='{safe_name}' and '{parent_id}' in parents "
            "and mimeType='application/vnd.google-apps.folder' "
            'and trashed=false'
        )
        exact_matches = _list_drive_files(
            service,
            exact_query,
            'id, name, parents',
        )
        if exact_matches:
            return exact_matches[0]['id']

        if not ALLOW_PARTIAL_DRIVE_FOLDER_MATCH:
            return None

        partial_query = (
            f"name contains '{safe_name}' and '{parent_id}' in parents "
            "and mimeType='application/vnd.google-apps.folder' "
            'and trashed=false'
        )
        partial_matches = _list_drive_files(
            service,
            partial_query,
            'id, name, parents',
            order_by='name',
        )
        if len(partial_matches) == 1:
            return partial_matches[0]['id']
        if len(partial_matches) > 1:
            current_app.logger.warning(
                'drive_folder_match_ambiguous',
                extra={
                    'folder_name': str(folder_name),
                    'matches': len(partial_matches),
                },
            )
        return None
    except Exception:
        current_app.logger.exception(
            'drive_folder_lookup_failed',
            extra={'folder_name': str(folder_name)},
        )
        return None


def get_drive_subfolders(service, parent_folder_id):
    try:
        query = (
            f"'{parent_folder_id}' in parents and "
            "mimeType='application/vnd.google-apps.folder' "
            'and trashed=false'
        )
        return _list_drive_files(
            service,
            query,
            'id, name, parents',
            order_by='name',
        )
    except Exception:
        current_app.logger.exception(
            'drive_subfolder_list_failed',
            extra={'parent_folder_id': parent_folder_id},
        )
        return []


def get_images_in_folder(service, folder_id):
    try:
        query = (
            f"'{folder_id}' in parents and "
            "mimeType contains 'image/' and trashed=false"
        )
        return _list_drive_files(
            service,
            query,
            'id, name, thumbnailLink, mimeType, size, parents',
            order_by='name',
        )
    except Exception:
        current_app.logger.exception(
            'drive_image_list_failed',
            extra={'folder_id': folder_id},
        )
        return []


def get_unique_images_for_ot(service, ot_code):
    """Obtiene imágenes únicas de la OT y sus subcarpetas inmediatas."""
    parent_folder_id = get_parent_folder_by_ot(ot_code)
    ot_folder_id = get_drive_folder_id(
        service,
        ot_code,
        parent_folder_id,
    )
    if not ot_folder_id:
        return False, []

    images = list(get_images_in_folder(service, ot_folder_id))
    for subfolder in get_drive_subfolders(service, ot_folder_id):
        images.extend(get_images_in_folder(service, subfolder['id']))

    unique_images = []
    seen_ids = set()
    for image in images:
        image_id = str(image.get('id') or '')
        if image_id and image_id not in seen_ids:
            seen_ids.add(image_id)
            unique_images.append(image)
    return True, unique_images


def download_drive_image(service, image_id, max_bytes=MAX_REPORT_IMAGE_BYTES):
    """Descarga una imagen de Drive con límites de MIME y tamaño."""
    metadata = service.files().get(
        fileId=image_id,
        fields='id,name,mimeType,size,parents',
        supportsAllDrives=True,
    ).execute()
    mime_type = str(metadata.get('mimeType') or '')
    declared_size = int(metadata.get('size') or 0)

    if not mime_type.startswith('image/'):
        raise ValueError('El archivo seleccionado no es una imagen.')
    if declared_size <= 0 or declared_size > max_bytes:
        raise ValueError('La imagen supera el tamaño permitido.')

    media_request = service.files().get_media(
        fileId=image_id,
        supportsAllDrives=True,
    )
    buffer = io.BytesIO()
    downloader = googleapiclient.http.MediaIoBaseDownload(
        buffer,
        media_request,
        chunksize=512 * 1024,
    )
    done = False
    while not done:
        _, done = downloader.next_chunk()
        if buffer.tell() > max_bytes:
            raise ValueError('La imagen supera el tamaño permitido.')

    return buffer.getvalue(), mime_type


def _cached_photo_count(ot_id):
    now = time.monotonic()
    with _photo_count_cache_lock:
        cached = _photo_count_cache.get(ot_id)
        if cached and now - cached['stored_at'] < PHOTO_COUNT_CACHE_TTL:
            return cached['payload']
        if cached:
            _photo_count_cache.pop(ot_id, None)
    return None


def _store_photo_count(ot_id, payload):
    with _photo_count_cache_lock:
        if len(_photo_count_cache) >= PHOTO_COUNT_CACHE_MAX_ITEMS:
            oldest_key = min(
                _photo_count_cache,
                key=lambda key: _photo_count_cache[key]['stored_at'],
            )
            _photo_count_cache.pop(oldest_key, None)
        _photo_count_cache[ot_id] = {
            'payload': payload,
            'stored_at': time.monotonic(),
        }


def get_logo_base64():
    try:
        logo_path = os.path.join(
            current_app.root_path,
            'static',
            'images',
            'nuevologo.png',
        )
        if not os.path.exists(logo_path):
            current_app.logger.warning(
                'report_logo_missing',
                extra={'logo_path': logo_path},
            )
            return ''

        with open(logo_path, 'rb') as file:
            encoded = base64.b64encode(file.read()).decode('utf-8')
        return f'data:image/png;base64,{encoded}'
    except Exception:
        current_app.logger.exception('report_logo_load_failed')
        return ''


def _thumbnail_url(image):
    thumbnail = str(image.get('thumbnailLink') or '')
    return thumbnail.replace('=s220', '=s600')


def _parse_selected_images(raw_keys):
    selected = []
    seen_keys = set()

    for raw_key in raw_keys:
        if raw_key in seen_keys:
            continue
        seen_keys.add(raw_key)

        parts = raw_key.split('::')
        if len(parts) != 3:
            raise ValueError('La selección de imágenes no es válida.')

        process_name = parts[0].strip()
        image_id = parts[1].strip()
        image_label = parts[2].strip()
        is_local = bool(LOCAL_IMAGE_ID_PATTERN.fullmatch(image_id))

        if (
            not process_name
            or len(process_name) > 100
            or not image_label
            or len(image_label) > 100
            or (
                not is_local
                and not REPORT_IMAGE_ID_PATTERN.fullmatch(image_id)
            )
        ):
            raise ValueError('La selección de imágenes no es válida.')

        selected.append({
            'key': raw_key,
            'process_name': process_name,
            'image_id': image_id,
            'image_label': image_label,
            'is_local': is_local,
        })

    return selected


def _decode_client_image(data_uri):
    if not isinstance(data_uri, str) or not data_uri:
        raise ValueError('La imagen local no contiene datos válidos.')

    mime_type = None
    encoded = data_uri
    if data_uri.startswith('data:'):
        header, separator, encoded = data_uri.partition(',')
        if not separator or ';base64' not in header:
            raise ValueError('La imagen local no contiene datos válidos.')
        mime_type = header[5:].split(';', 1)[0].lower()
        if mime_type not in ALLOWED_CLIENT_IMAGE_MIME_TYPES:
            raise ValueError('El formato de la imagen local no está permitido.')

    maximum_encoded_length = ((MAX_REPORT_IMAGE_BYTES * 4) // 3) + 16
    if len(encoded) > maximum_encoded_length:
        raise ValueError('La imagen local supera el tamaño permitido.')

    try:
        image_bytes = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError('La imagen local no contiene Base64 válido.') from error

    if not image_bytes or len(image_bytes) > MAX_REPORT_IMAGE_BYTES:
        raise ValueError('La imagen local supera el tamaño permitido.')

    return image_bytes, mime_type


def _open_validated_image(image_bytes):
    try:
        with Image.open(io.BytesIO(image_bytes)) as verification_image:
            verification_image.verify()

        with Image.open(io.BytesIO(image_bytes)) as source_image:
            source_image.load()
            if not image_dimensions_are_allowed(source_image):
                raise ValueError('La imagen supera la resolución permitida.')
            image = source_image.copy()
    except (UnidentifiedImageError, OSError) as error:
        raise ValueError('El archivo no contiene una imagen válida.') from error

    if ImageOps is not None and hasattr(ImageOps, 'exif_transpose'):
        image = ImageOps.exif_transpose(image)
    return image


def _prepare_report_image(image, already_cropped=False):
    if not already_cropped:
        width, height = image.size
        crop_x = int(width * 0.06)
        crop_y = int(height * 0.06)
        if (
            width - (2 * crop_x) > 10
            and height - (2 * crop_y) > 10
        ):
            image = image.crop(
                (
                    crop_x,
                    crop_y,
                    width - crop_x,
                    height - crop_y,
                )
            )

        width, height = image.size
        target_ratio = 4.0 / 3.0
        current_ratio = width / height if height else target_ratio
        if current_ratio < target_ratio:
            new_height = max(1, int(width / target_ratio))
            offset = max((height - new_height) // 2, 0)
            image = image.crop((0, offset, width, offset + new_height))
        elif current_ratio > target_ratio:
            new_width = max(1, int(height * target_ratio))
            offset = max((width - new_width) // 2, 0)
            image = image.crop((offset, 0, offset + new_width, height))

    if image.width > REPORT_OUTPUT_MAX_WIDTH:
        ratio = REPORT_OUTPUT_MAX_WIDTH / image.width
        resampling = getattr(Image, 'Resampling', Image)
        lanczos = getattr(resampling, 'LANCZOS', Image.BICUBIC)
        image = image.resize(
            (REPORT_OUTPUT_MAX_WIDTH, max(1, int(image.height * ratio))),
            lanczos,
        )

    if image.mode != 'RGB':
        image = image.convert('RGB')

    resampling = getattr(Image, 'Resampling', Image)
    lanczos = getattr(resampling, 'LANCZOS', Image.BICUBIC)
    working_image = image
    minimum_width = min(320, working_image.width)

    while True:
        quality_values = [
            REPORT_OUTPUT_JPEG_QUALITY,
            max(55, REPORT_OUTPUT_JPEG_QUALITY - 10),
            45,
        ]
        for quality in dict.fromkeys(quality_values):
            output = io.BytesIO()
            working_image.save(
                output,
                format='JPEG',
                quality=quality,
                optimize=True,
            )
            encoded_bytes = output.getvalue()
            if len(encoded_bytes) <= MAX_REPORT_RENDERED_IMAGE_BYTES:
                return (
                    base64.b64encode(encoded_bytes).decode('ascii'),
                    len(encoded_bytes),
                )

        if working_image.width <= minimum_width:
            break

        next_width = max(minimum_width, int(working_image.width * 0.8))
        next_height = max(
            1,
            int(working_image.height * (next_width / working_image.width)),
        )
        working_image = working_image.resize(
            (next_width, next_height),
            lanczos,
        )

    raise ValueError(
        'La fotografía no pudo optimizarse al tamaño requerido para el reporte.'
    )


@reporte_bp.route('/reporte/seleccionar/<int:ot_id>')
@login_required
@roles_required('admin', 'editor')
def seleccionar_fotos_reporte(ot_id):
    ot = db.session.get(CatalogoOT, ot_id)
    if ot is None:
        return 'OT no encontrada.', 404

    service = get_drive_service()
    if service is None:
        return 'No fue posible conectar con Google Drive.', 503

    ot_code = str(ot.ot).strip()
    parent_folder_id = get_parent_folder_by_ot(ot_code)
    ot_folder_id = get_drive_folder_id(
        service,
        ot_code,
        parent_folder_id,
    )

    if not ot_folder_id:
        return render_template(
            'reporte_selector.html',
            ot=ot.to_dict(),
            procesos=[],
            imagenes_sueltas=[],
            is_2026=False,
        ), 404

    is_2026 = ot_code.startswith('2026')

    if is_2026:
        _, images = get_unique_images_for_ot(service, ot_code)
        loose_images = [
            {
                'id': image['id'],
                'nombre': image.get('name') or 'Fotografía',
                'thumbnail': _thumbnail_url(image),
            }
            for image in images
        ]
        return render_template(
            'reporte_selector.html',
            ot=ot.to_dict(),
            procesos=[],
            imagenes_sueltas=loose_images,
            is_2026=True,
        )

    process_folders = get_drive_subfolders(service, ot_folder_id)
    processes_with_photos = []
    raw_material_process = None

    for folder in process_folders:
        process_data = {
            'nombre': folder['name'],
            'descripcion': folder['name'],
            'imagenes': [],
        }
        for image in get_images_in_folder(service, folder['id']):
            process_data['imagenes'].append({
                'id': image['id'],
                'nombre': image.get('name') or 'Fotografía',
                'thumbnail': _thumbnail_url(image),
            })

        if 'MATERIA PRIMA' in folder['name'].upper():
            raw_material_process = process_data
        else:
            processes_with_photos.append(process_data)

    if raw_material_process:
        processes_with_photos.insert(0, raw_material_process)

    return render_template(
        'reporte_selector.html',
        ot=ot.to_dict(),
        procesos=processes_with_photos,
        is_2026=False,
    )


@reporte_bp.get('/reporte/api/fotos/<int:ot_id>/conteo')
@login_required
@roles_required('admin', 'editor')
def api_conteo_fotos_drive(ot_id):
    ot = db.session.get(CatalogoOT, ot_id)
    if ot is None:
        return jsonify({
            'success': False,
            'error': 'La OT no existe.',
        }), 404

    cached = _cached_photo_count(ot_id)
    if cached is not None:
        return jsonify({**cached, 'cached': True})

    service = get_drive_service()
    if service is None:
        return jsonify({
            'success': False,
            'error': 'No fue posible conectar con Google Drive.',
        }), 503

    try:
        folder_found, images = get_unique_images_for_ot(
            service,
            str(ot.ot).strip(),
        )
        payload = {
            'success': True,
            'count': len(images),
            'folder_found': folder_found,
            'ot': ot.ot,
        }
        _store_photo_count(ot_id, payload)
        return jsonify({**payload, 'cached': False})
    except Exception:
        current_app.logger.exception(
            'photo_count_failed',
            extra={'ot_id': ot_id, 'ot_code': ot.ot},
        )
        return jsonify({
            'success': False,
            'error': 'No fue posible consultar las fotografías.',
        }), 502


@reporte_bp.get('/reporte/api/fotos/<int:ot_id>')
@login_required
@roles_required('admin', 'editor')
def api_obtener_fotos_drive(ot_id):
    ot = db.session.get(CatalogoOT, ot_id)
    if ot is None:
        return jsonify({
            'success': False,
            'error': 'La OT no existe.',
        }), 404

    service = get_drive_service()
    if service is None:
        return jsonify({
            'success': False,
            'error': 'No fue posible conectar con Google Drive.',
        }), 503

    try:
        folder_found, images = get_unique_images_for_ot(
            service,
            str(ot.ot).strip(),
        )
        if not folder_found:
            return jsonify({'success': True, 'fotos': []})

        return jsonify({
            'success': True,
            'fotos': [
                {
                    'id': image['id'],
                    'nombre': image.get('name') or 'Fotografía',
                    'thumbnail': _thumbnail_url(image),
                }
                for image in images
            ],
        })
    except Exception:
        current_app.logger.exception(
            'photo_gallery_load_failed',
            extra={'ot_id': ot_id, 'ot_code': ot.ot},
        )
        return jsonify({
            'success': False,
            'error': 'Ocurrió un error al consultar las fotografías.',
        }), 502


@reporte_bp.post('/reporte/generar')
@login_required
@roles_required('admin', 'editor')
@limiter.limit(
    REPORT_RATE_LIMIT,
    methods=['POST'],
    key_func=_report_rate_limit_key,
)
def generar_reporte_pdf():
    if Image is None:
        return 'Pillow no está disponible en el servidor.', 500

    try:
        raw_ot_id = request.form.get('ot_id')
        structure_custom = request.form.get('estructura_custom')
        date_custom = request.form.get('fecha_custom')
        raw_selected_keys = request.form.getlist('selected_images')

        if not raw_ot_id:
            return 'Falta ot_id.', 400
        if not raw_selected_keys:
            return 'No se seleccionaron imágenes.', 400
        if len(raw_selected_keys) > MAX_REPORT_IMAGES:
            return (
                f'Solo se permiten {MAX_REPORT_IMAGES} imágenes por reporte.',
                413,
            )

        try:
            ot_id = int(raw_ot_id)
        except (TypeError, ValueError):
            return 'El identificador de la OT no es válido.', 400

        if (
            structure_custom
            and len(structure_custom.strip()) > MAX_REPORT_TEXT_LENGTH
        ):
            return 'La descripción del reporte es demasiado extensa.', 400
        if date_custom and len(date_custom.strip()) > 20:
            return 'La fecha del reporte no es válida.', 400

        try:
            selected_images = _parse_selected_images(raw_selected_keys)
        except ValueError as error:
            return str(error), 400

        if len(selected_images) > MAX_REPORT_IMAGES:
            return (
                f'Solo se permiten {MAX_REPORT_IMAGES} imágenes por reporte.',
                413,
            )

        local_images = [item for item in selected_images if item['is_local']]
        if len(local_images) > MAX_REPORT_LOCAL_IMAGES:
            return (
                f'Solo se permiten {MAX_REPORT_LOCAL_IMAGES} imágenes locales '
                'por reporte.',
                413,
            )

        ot_object = db.session.get(CatalogoOT, ot_id)
        if ot_object is None:
            return 'La OT no existe.', 404

        drive_service = get_drive_service()
        if drive_service is None:
            return 'No fue posible conectar con Google Drive.', 503

        folder_found, available_images = get_unique_images_for_ot(
            drive_service,
            str(ot_object.ot).strip(),
        )
        if not folder_found:
            return 'No se encontró la carpeta de fotografías de esta OT.', 404

        available_by_id = {
            str(image.get('id')): image
            for image in available_images
            if image.get('id')
        }

        drive_selected_ids = {
            item['image_id']
            for item in selected_images
            if not item['is_local']
        }
        unauthorized_ids = drive_selected_ids.difference(available_by_id)
        if unauthorized_ids:
            current_app.logger.warning(
                'report_image_not_in_ot',
                extra={
                    'ot_id': ot_id,
                    'user_id': current_user.get_id(),
                    'invalid_count': len(unauthorized_ids),
                },
            )
            return (
                'Una o más imágenes no pertenecen a la carpeta de esta OT.',
                409,
            )

        client_images = {}
        client_total_bytes = 0
        local_total_bytes = 0
        estimated_total_bytes = 0

        for item in selected_images:
            image_id = item['image_id']
            client_value = request.form.get(f'b64_{image_id}')

            if item['is_local'] and not client_value:
                return 'Una imagen local no contiene datos.', 400

            if client_value:
                try:
                    image_bytes, _ = _decode_client_image(client_value)
                    # Abrirla ahora evita enviar archivos inválidos a los hilos.
                    test_image = _open_validated_image(image_bytes)
                    test_image.close()
                except ValueError as error:
                    return str(error), 413

                client_images[image_id] = image_bytes
                client_total_bytes += len(image_bytes)
                estimated_total_bytes += len(image_bytes)
                if item['is_local']:
                    local_total_bytes += len(image_bytes)
                continue

            metadata = available_by_id[image_id]
            mime_type = str(metadata.get('mimeType') or '')
            declared_size = int(metadata.get('size') or 0)
            if not mime_type.startswith('image/'):
                return 'Uno de los archivos seleccionados no es una imagen.', 422
            if declared_size <= 0 or declared_size > MAX_REPORT_IMAGE_BYTES:
                return 'Una imagen supera el tamaño permitido.', 413
            estimated_total_bytes += declared_size

        if client_total_bytes > MAX_REPORT_TOTAL_BYTES:
            return 'Las imágenes enviadas superan el límite total permitido.', 413
        if local_total_bytes > MAX_REPORT_LOCAL_TOTAL_BYTES:
            return 'Las imágenes locales superan el límite total permitido.', 413
        if estimated_total_bytes > MAX_REPORT_TOTAL_BYTES:
            return (
                'El conjunto de imágenes supera el tamaño total permitido.',
                413,
            )

        report_ot = ot_object.to_dict()
        if structure_custom:
            report_ot['descripcion'] = structure_custom.strip()
        if date_custom:
            report_ot['fecha_iniciado'] = date_custom.strip()

        flask_app = current_app._get_current_object()

        def process_image(item):
            image_id = item['image_id']
            process_name = item['process_name']
            with flask_app.app_context():
                try:
                    if image_id in client_images:
                        image = _open_validated_image(client_images[image_id])
                        encoded, encoded_size = _prepare_report_image(
                            image,
                            already_cropped=True,
                        )
                        image.close()
                    else:
                        thread_service = get_drive_service()
                        if thread_service is None:
                            raise RuntimeError(
                                'No fue posible crear el cliente de Drive.'
                            )
                        image_bytes, _ = download_drive_image(
                            thread_service,
                            image_id,
                        )
                        image = _open_validated_image(image_bytes)
                        encoded, encoded_size = _prepare_report_image(image)
                        image.close()

                    return {
                        'ok': True,
                        'process_name': process_name,
                        'image_id': image_id,
                        'encoded_size': encoded_size,
                        'image': {
                            'url': f'data:image/jpeg;base64,{encoded}',
                            'rotate': False,
                        },
                    }
                except Exception as error:
                    current_app.logger.exception(
                        'report_image_processing_failed',
                        extra={
                            'ot_id': ot_id,
                            'image_id': image_id,
                            'error_type': type(error).__name__,
                        },
                    )
                    return {
                        'ok': False,
                        'image_id': image_id,
                    }

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(REPORT_WORKERS, len(selected_images)),
        ) as executor:
            results = list(executor.map(process_image, selected_images))

        failed_results = [result for result in results if not result['ok']]
        if failed_results:
            return (
                f'No se pudieron procesar {len(failed_results)} imágenes. '
                'Revisa que sigan disponibles y dentro de los límites.',
                422,
            )

        rendered_image_bytes = sum(
            result['encoded_size'] for result in results
        )
        if rendered_image_bytes > MAX_REPORT_RENDERED_TOTAL_BYTES:
            current_app.logger.warning(
                'report_rendered_payload_too_large',
                extra={
                    'ot_id': ot_id,
                    'image_count': len(results),
                    'rendered_image_bytes': rendered_image_bytes,
                    'rendered_limit_bytes': MAX_REPORT_RENDERED_TOTAL_BYTES,
                },
            )
            return (
                'Las fotografías optimizadas todavía superan el tamaño seguro '
                'del reporte. Selecciona menos fotografías e inténtalo de nuevo.',
                413,
            )

        processes_map = {}
        for result in results:
            process_name = result['process_name']
            processes_map.setdefault(
                process_name,
                {'nombre': process_name, 'imagenes': []},
            )['imagenes'].append(result['image'])

        final_processes = []
        raw_material_key = next(
            (
                key
                for key in processes_map
                if 'MATERIA PRIMA' in key.upper()
            ),
            None,
        )
        if raw_material_key:
            final_processes.append(processes_map.pop(raw_material_key))
        final_processes.extend(processes_map.values())

        if not final_processes:
            return 'No se pudo procesar ninguna imagen seleccionada.', 422

        current_app.logger.info(
            'report_generated',
            extra={
                'ot_id': ot_id,
                'user_id': current_user.get_id(),
                'image_count': len(selected_images),
                'local_image_count': len(local_images),
                'rendered_image_bytes': rendered_image_bytes,
            },
        )

        return render_template(
            'reporte_plantilla.html',
            ot=report_ot,
            procesos=final_processes,
            logo_data_uri=get_logo_base64(),
            fecha_hoy=datetime.datetime.now().strftime('%d/%m/%Y'),
        )
    except Exception:
        current_app.logger.exception(
            'report_generation_failed',
            extra={'user_id': current_user.get_id()},
        )
        return 'Ocurrió un error interno al generar el reporte.', 500
