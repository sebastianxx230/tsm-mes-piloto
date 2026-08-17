import io
import os
import re
import traceback
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required
from googleapiclient.errors import HttpError
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename
from utils.auth import roles_required
from db_config import db
from models.catalogo_ot import CatalogoOT
from models.produccion import BitacoraOT, ComponenteOT, FotoSeguimiento, PackingList
from utils.production_metrics import (
    PROCESS_DEFINITIONS,
    clamped_ratio,
    component_progress,
    process_settings,
    quantity_weighted_average,
)
from utils.tracking_schema import (
    TrackingSchemaError,
    ensure_tracking_storage_schema,
)

gestion_ot_bp = Blueprint('gestion_ot_bp', __name__, template_folder='../templates')

LIMA_TIMEZONE = timezone(timedelta(hours=-5), name='America/Lima')
ALLOWED_OT_STATES = {'En Proceso', 'No Empezado', 'Terminado'}
OT_CODE_PATTERN = re.compile(r'^[A-Z0-9][A-Z0-9._/-]{2,49}$')
MAX_TRACKING_PHOTOS = max(1, int(os.environ.get('MAX_TRACKING_PHOTOS', '12')))
MAX_TRACKING_PHOTO_UPLOAD_BYTES = max(
    512 * 1024,
    int(os.environ.get(
        'MAX_TRACKING_PHOTO_UPLOAD_BYTES',
        str(3 * 1024 * 1024),
    )),
)
DRIVE_IMAGE_ID_PATTERN = re.compile(r'^[A-Za-z0-9_-]{1,150}$')
ALLOWED_TRACKING_PHOTO_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
TRACKING_PHOTO_MIME_TYPES = {
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.webp': 'image/webp',
}


def _validation_error(message, status=400):
    return jsonify({'success': False, 'error': message}), status


def _clean_text(value, field_name, *, required=False, max_length=255):
    if value is None:
        value = ''
    if not isinstance(value, str):
        raise ValueError(f'{field_name} debe ser texto.')
    value = value.strip()
    if required and not value:
        raise ValueError(f'{field_name} es obligatorio.')
    if len(value) > max_length:
        raise ValueError(f'{field_name} no puede superar {max_length} caracteres.')
    return value


def _validate_ot_payload(data):
    if not isinstance(data, dict):
        raise ValueError('El cuerpo JSON es obligatorio y debe ser un objeto.')

    modo = data.get('modo')
    if modo not in {'create', 'edit'}:
        raise ValueError('El modo debe ser create o edit.')

    ot_code = _clean_text(data.get('ot'), 'El código de OT', required=True, max_length=50).upper()
    if not OT_CODE_PATTERN.fullmatch(ot_code):
        raise ValueError('El código de OT solo admite letras, números, punto, guion, guion bajo o barra.')

    cliente = _clean_text(data.get('cliente'), 'El cliente', required=True, max_length=100)
    descripcion = _clean_text(data.get('descripcion'), 'La descripción', max_length=5000)

    fecha_raw = _clean_text(data.get('fecha_iniciado'), 'La fecha de inicio', required=True, max_length=10)
    try:
        fecha_iniciado = date.fromisoformat(fecha_raw)
    except ValueError as exc:
        raise ValueError('La fecha de inicio debe tener formato AAAA-MM-DD y ser válida.') from exc

    estado = _clean_text(data.get('estado'), 'El estado', required=True, max_length=30)
    if estado not in ALLOWED_OT_STATES:
        raise ValueError('El estado indicado no está permitido.')

    expected_version = None
    if modo == 'edit':
        try:
            expected_version = int(data.get('expected_version'))
        except (TypeError, ValueError):
            raise ValueError('Actualiza el catálogo antes de editar esta OT.') from None
        if expected_version < 1:
            raise ValueError('La versión de la OT no es válida.')

    return {
        'modo': modo,
        'ot': ot_code,
        'cliente': cliente,
        'fecha_iniciado': fecha_iniciado,
        'descripcion': descripcion,
        'estado': estado,
        'expected_version': expected_version,
    }

@gestion_ot_bp.route('/catalogo-ot')
@login_required
def catalogo_ot():
    ots = []
    ots_db = []
    today_lima = datetime.now(LIMA_TIMEZONE).date()
    try:
        ots_db = (
            CatalogoOT.query.filter_by(archivado=False)
            .order_by(CatalogoOT.item.desc())
            .all()
        )
        for ot in ots_db:
            ot_data = ot.to_dict()
            ot_data['is_current_year'] = bool(
                ot.fecha_iniciado and ot.fecha_iniciado.year == today_lima.year
            )
            ots.append(ot_data)
    except Exception:
        current_app.logger.exception('catalog_load_failed')

    current_year_ots = [
        ot for ot in ots_db
        if ot.fecha_iniciado and ot.fecha_iniciado.year == today_lima.year
    ]
    counts = {
        'total_anio': len(current_year_ots),
        'proceso': sum(ot.estado == 'En Proceso' for ot in current_year_ots),
        'terminado': sum(ot.estado == 'Terminado' for ot in current_year_ots),
        'noempezado': sum(ot.estado == 'No Empezado' for ot in current_year_ots),
    }
    stats = {
        'total_mes': sum(
            ot.fecha_iniciado.month == today_lima.month for ot in current_year_ots
        ),
        'proceso_recientes': sum(
            ot.estado == 'En Proceso'
            and 0 <= (today_lima - ot.fecha_iniciado).days <= 3
            for ot in current_year_ots
        ),
    }

    return render_template(
        'catalogo_ot.html',
        ots=ots,
        counts=counts,
        stats=stats,
        current_year=today_lima.year,
    )

@gestion_ot_bp.route('/catalogo-ot/guardar', methods=['POST'])
@login_required
@roles_required('admin', 'editor')
def guardar_ot():
    try:
        data = _validate_ot_payload(request.get_json(silent=True))
        modo = data['modo']

        if modo == 'create':
            if CatalogoOT.query.filter_by(ot=data['ot']).first():
                return _validation_error('Ya existe una OT con ese código.', 409)
            nueva_ot = CatalogoOT(
                ot=data['ot'],
                cliente=data['cliente'],
                fecha_iniciado=data['fecha_iniciado'],
                descripcion=data['descripcion'],
                estado=data['estado'],
            )
            db.session.add(nueva_ot)
            msg = "OT creada exitosamente."

        else:
            ot_editar = (
                CatalogoOT.query.filter_by(ot=data['ot'], archivado=False)
                .with_for_update()
                .first()
            )

            if ot_editar:
                if int(ot_editar.version or 1) != data['expected_version']:
                    db.session.rollback()
                    return jsonify({
                        'success': False,
                        'error': 'Otra persona modificó esta OT. Actualiza la página antes de guardar.',
                        'current_version': ot_editar.version,
                    }), 409
                ot_editar.cliente = data['cliente']
                ot_editar.fecha_iniciado = data['fecha_iniciado']
                ot_editar.descripcion = data['descripcion']
                ot_editar.estado = data['estado']
                ot_editar.incrementar_version()
                msg = "OT actualizada exitosamente."
            else:
                return jsonify({'success': False, 'error': 'La OT especificada no existe.'}), 404

        db.session.commit()
        saved_ot = nueva_ot if modo == 'create' else ot_editar
        return jsonify({
            'success': True,
            'message': msg,
            'version': saved_ot.version,
        })

    except ValueError as exc:
        return _validation_error(str(exc))
    except IntegrityError:
        db.session.rollback()
        return _validation_error('Ya existe una OT con ese código.', 409)
    except Exception:
        db.session.rollback()
        current_app.logger.exception('catalog_save_failed')
        return jsonify({'success': False, 'error': 'Ocurrió un error interno al guardar la OT.'}), 500

@gestion_ot_bp.route('/catalogo-ot/eliminar/<int:id>', methods=['POST'])
@login_required # Protege la ruta
@roles_required('admin')
def eliminar_ot(id):
    try:
        payload = request.get_json(silent=True) or {}
        try:
            expected_version = int(payload.get('expected_version'))
        except (TypeError, ValueError):
            return _validation_error('Actualiza el catálogo antes de archivar esta OT.', 428)
        ot_eliminar = db.session.get(CatalogoOT, id, with_for_update=True)

        if ot_eliminar and not ot_eliminar.archivado:
            if int(ot_eliminar.version or 1) != expected_version:
                db.session.rollback()
                return jsonify({
                    'success': False,
                    'error': 'Otra persona modificó esta OT. Actualiza la página antes de archivarla.',
                    'current_version': ot_eliminar.version,
                }), 409
            ot_eliminar.archivado = True
            ot_eliminar.fecha_archivado = datetime.now(timezone.utc).replace(tzinfo=None)
            ot_eliminar.archivado_por_id = current_user.id
            ot_eliminar.incrementar_version()
            db.session.commit()
            return jsonify({'success': True, 'archived': True})
        else:
            return jsonify({'success': False, 'error': 'La OT que intentas eliminar no existe.'}), 404

    except Exception:
        db.session.rollback()
        current_app.logger.exception('work_order_archive_failed', extra={'ot_id': id})
        return jsonify({'success': False, 'error': 'Ocurrió un error interno al archivar la OT.'}), 500


@gestion_ot_bp.route('/produccion/<int:id>')
@login_required
def produccion(id):
    if current_user.rol == 'viewer':
        ot = db.session.get(CatalogoOT, id)
        if not ot or ot.archivado:
            return "OT no encontrada", 404
        return redirect(url_for('gestion_ot_bp.seguimiento', ot_code=ot.ot))

    return _render_production(id)


@gestion_ot_bp.put('/api/produccion/ot/<int:id>/fecha-termino')
@login_required
@roles_required('admin', 'editor')
def actualizar_fecha_termino(id):
    try:
        data = request.get_json(silent=True) or {}
        raw_value = str(data.get('fecha_termino') or '').strip()
        ot = db.session.get(CatalogoOT, id, with_for_update=True)
        if ot is None or ot.archivado:
            return jsonify({'success': False, 'error': 'La OT no existe.'}), 404

        try:
            expected_version = int(data.get('expected_version'))
        except (TypeError, ValueError):
            return _validation_error('Actualiza la pantalla antes de cambiar la fecha.', 428)
        if int(ot.version or 1) != expected_version:
            db.session.rollback()
            return jsonify({
                'success': False,
                'error': 'Otra persona modificó esta OT. Actualiza la pantalla.',
                'current_version': ot.version,
            }), 409

        if raw_value:
            try:
                new_date = date.fromisoformat(raw_value)
            except ValueError:
                return jsonify({'success': False, 'error': 'La fecha debe tener formato AAAA-MM-DD.'}), 400
            if ot.fecha_iniciado and new_date < ot.fecha_iniciado:
                return jsonify({'success': False, 'error': 'La fecha de término no puede ser anterior al inicio.'}), 400
        else:
            new_date = None

        ot.fecha_termino = new_date
        ot.incrementar_version()
        db.session.add(BitacoraOT(
            ot_id=ot.item,
            usuario_id=current_user.id,
            usuario_nombre=getattr(current_user, 'nombre', f'Usuario {current_user.id}'),
            mensaje=(
                f'Actualizó la fecha de término a {new_date.strftime("%d/%m/%Y")}.'
                if new_date else 'Quitó la fecha de término.'
            ),
            tipo='audit',
        ))
        db.session.commit()
        return jsonify({
            'success': True,
            'fecha_termino': new_date.isoformat() if new_date else '',
            'fecha_termino_display': new_date.strftime('%d/%m/%Y') if new_date else 'Sin fecha',
            'version': ot.version,
        })
    except Exception:
        db.session.rollback()
        current_app.logger.exception('work_order_end_date_update_failed', extra={'ot_id': id})
        return jsonify({'success': False, 'error': 'No se pudo actualizar la fecha de término.'}), 500


def _render_tracking_page(work_order):
    tracking = _build_tracking_summary(work_order.item)
    return render_template(
        'seguimiento.html',
        ot=work_order,
        tracking=tracking,
        max_tracking_photos=MAX_TRACKING_PHOTOS,
    )


@gestion_ot_bp.route('/seguimiento/ot/<path:ot_code>')
@login_required
def seguimiento(ot_code):
    try:
        normalized_code = str(ot_code or '').strip().upper()
        ot = CatalogoOT.query.filter_by(ot=normalized_code, archivado=False).first()
        if not ot or ot.archivado:
            return "OT no encontrada", 404

        return _render_tracking_page(ot)
    except Exception:
        traceback.print_exc()
        return "Error interno del servidor", 500


@gestion_ot_bp.route('/seguimiento/<int:id>')
@login_required
def seguimiento_legacy(id):
    ot = db.session.get(CatalogoOT, id)
    if not ot or ot.archivado:
        return "OT no encontrada", 404
    return redirect(
        url_for('gestion_ot_bp.seguimiento', ot_code=ot.ot),
        code=302,
    )


@gestion_ot_bp.route('/api/seguimiento/<int:id>')
@login_required
def seguimiento_data(id):
    work_order = db.session.get(CatalogoOT, id)
    if work_order is None or work_order.archivado:
        return jsonify({'success': False, 'error': 'La OT no existe.'}), 404

    try:
        return jsonify(_build_tracking_summary(id))
    except Exception:
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': 'No se pudo actualizar el seguimiento.',
        }), 500


def _tracking_photo_dict(photo):
    data = photo.to_dict()
    data['image_url'] = url_for(
        'gestion_ot_bp.seguimiento_photo_image',
        photo_id=photo.id,
    )
    return data


def _read_tracking_photo_upload(file_storage):
    original_name = Path(str(file_storage.filename or '')).name.strip()
    extension = Path(original_name).suffix.lower()
    if not original_name or extension not in ALLOWED_TRACKING_PHOTO_EXTENSIONS:
        raise ValueError('Sube una fotografía JPG, PNG o WEBP.')

    safe_name = secure_filename(original_name)
    if not safe_name:
        raise ValueError('El nombre de la fotografía no es válido.')

    content = file_storage.stream.read(MAX_TRACKING_PHOTO_UPLOAD_BYTES + 1)
    if not content:
        raise ValueError('La fotografía está vacía.')
    if len(content) > MAX_TRACKING_PHOTO_UPLOAD_BYTES:
        raise OverflowError(
            f'La fotografía supera el límite de '
            f'{MAX_TRACKING_PHOTO_UPLOAD_BYTES // (1024 * 1024)} MB.'
        )
    return safe_name, TRACKING_PHOTO_MIME_TYPES[extension], content


@gestion_ot_bp.post('/api/seguimiento/<int:id>/fotos/subir')
@login_required
@roles_required('admin')
def subir_foto_seguimiento(id):
    ot = db.session.get(CatalogoOT, id)
    if ot is None or ot.archivado:
        return _validation_error('La OT no existe.', 404)

    file_storage = request.files.get('file')
    if file_storage is None:
        return _validation_error('Selecciona una fotografía para subir.')

    try:
        filename, mime_type, content = _read_tracking_photo_upload(file_storage)
    except OverflowError as error:
        return _validation_error(str(error), 413)
    except ValueError as error:
        return _validation_error(str(error))

    from controllers.reporte_fotografico_controller import (
        DRIVE_PHOTOS_FOLDER_NAME,
        ensure_ot_category_folder,
        get_drive_service,
        invalidate_photo_count_cache,
        upload_drive_file,
    )

    service = get_drive_service()
    if service is None:
        return _validation_error('No fue posible conectar con Google Drive.', 503)

    try:
        folder = ensure_ot_category_folder(
            service,
            str(ot.ot).strip(),
            DRIVE_PHOTOS_FOLDER_NAME,
        )
        uploaded = upload_drive_file(
            service,
            folder['category_folder_id'],
            filename,
            mime_type,
            content,
        )
        invalidate_photo_count_cache(id)

        try:
            db.session.add(BitacoraOT(
                ot_id=id,
                usuario_id=current_user.id,
                usuario_nombre=getattr(current_user, 'nombre', 'Administrador'),
                mensaje=f'Subió {filename} a FOTOGRAFIAS en Google Drive.',
                tipo='audit',
            ))
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception(
                'tracking_photo_upload_audit_failed',
                extra={'ot_id': id},
            )

        return jsonify({
            'success': True,
            'photo': {
                'id': uploaded['id'],
                'nombre': uploaded.get('name') or filename,
            },
        }), 201
    except HttpError as error:
        status = int(getattr(getattr(error, 'resp', None), 'status', 0) or 0)
        current_app.logger.warning(
            'tracking_photo_drive_upload_rejected',
            extra={'ot_id': id, 'status': status},
        )
        if status in {401, 403}:
            return _validation_error(
                'La cuenta de servicio necesita permiso de Editor en la carpeta de Drive.',
                403,
            )
        return _validation_error('Google Drive rechazó la fotografía.', 502)
    except ValueError as error:
        return _validation_error(str(error), 400)
    except Exception:
        current_app.logger.exception(
            'tracking_photo_upload_failed',
            extra={'ot_id': id},
        )
        return _validation_error(
            'No fue posible subir la fotografía a Google Drive.',
            502,
        )


@gestion_ot_bp.put('/api/seguimiento/<int:id>/fotos')
@login_required
@roles_required('admin')
def guardar_fotos_seguimiento(id):
    try:
        ensure_tracking_storage_schema()
        ot = db.session.get(CatalogoOT, id)
    except TrackingSchemaError:
        db.session.rollback()
        return _validation_error(
            'No fue posible preparar el almacenamiento de fotografías. '
            'Vuelve a intentarlo en un momento.',
            503,
        )
    except Exception as error:
        db.session.rollback()
        current_app.logger.exception(
            'tracking_photo_lookup_failed exception_type=%s',
            type(error).__name__,
            extra={'ot_id': id},
        )
        return _validation_error(
            'No fue posible consultar la OT antes de guardar las fotografías.',
            500,
        )

    if ot is None or ot.archivado:
        return _validation_error('La OT no existe.', 404)

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not isinstance(payload.get('photos'), list):
        return _validation_error('La selección de fotografías no es válida.')

    raw_photos = payload['photos']
    if len(raw_photos) > MAX_TRACKING_PHOTOS:
        return _validation_error(
            f'Solo puedes publicar hasta {MAX_TRACKING_PHOTOS} fotografías.',
            413,
        )

    selected_ids = []
    for item in raw_photos:
        if not isinstance(item, dict):
            return _validation_error('La selección de fotografías no es válida.')
        image_id = str(item.get('id') or '').strip()
        if not DRIVE_IMAGE_ID_PATTERN.fullmatch(image_id):
            return _validation_error('Una fotografía tiene un identificador no válido.')
        if image_id not in selected_ids:
            selected_ids.append(image_id)

    try:
        if not selected_ids:
            FotoSeguimiento.query.filter_by(ot_id=id).delete(synchronize_session=False)
            db.session.commit()
            return jsonify({'success': True, 'photos': []})

        from controllers.reporte_fotografico_controller import (
            get_drive_service,
            get_unique_images_for_ot,
        )

        drive_service = get_drive_service()
        if drive_service is None:
            return _validation_error('No fue posible conectar con Google Drive.', 503)

        folder_found, available_images = get_unique_images_for_ot(
            drive_service,
            str(ot.ot).strip(),
        )
        available_by_id = {
            str(image.get('id')): image
            for image in available_images
            if image.get('id')
        }
        if not folder_found:
            return _validation_error('No se encontró la carpeta de fotografías de esta OT.', 404)
        if any(image_id not in available_by_id for image_id in selected_ids):
            return _validation_error(
                'Una de las fotografías ya no pertenece a la carpeta de esta OT.',
                409,
            )

        FotoSeguimiento.query.filter_by(ot_id=id).delete(synchronize_session=False)
        for order, image_id in enumerate(selected_ids):
            image = available_by_id[image_id]
            image_name = str(image.get('name') or f'Fotografía {order + 1}').strip()
            db.session.add(FotoSeguimiento(
                ot_id=id,
                drive_file_id=image_id,
                nombre=image_name[:255],
                orden=order,
                actualizado_por_id=current_user.id,
            ))

        db.session.commit()
        saved_photos = (
            FotoSeguimiento.query.filter_by(ot_id=id)
            .order_by(FotoSeguimiento.orden.asc(), FotoSeguimiento.id.asc())
            .all()
        )
        return jsonify({
            'success': True,
            'photos': [_tracking_photo_dict(photo) for photo in saved_photos],
        })
    except Exception as error:
        db.session.rollback()
        current_app.logger.exception(
            'tracking_photos_save_failed exception_type=%s',
            type(error).__name__,
            extra={'ot_id': id},
        )
        return jsonify({
            'success': False,
            'error': 'No fue posible guardar las fotografías de seguimiento.',
        }), 500


@gestion_ot_bp.get('/seguimiento/fotos/<int:photo_id>/imagen')
@login_required
def seguimiento_photo_image(photo_id):
    photo = db.session.get(FotoSeguimiento, photo_id)
    if photo is None:
        return 'Fotografía no encontrada.', 404

    try:
        from controllers.reporte_fotografico_controller import (
            download_drive_image,
            get_drive_service,
        )

        drive_service = get_drive_service()
        if drive_service is None:
            return 'No fue posible conectar con Google Drive.', 503

        image_bytes, mime_type = download_drive_image(
            drive_service,
            photo.drive_file_id,
        )
        response = send_file(
            io.BytesIO(image_bytes),
            mimetype=mime_type,
            download_name=photo.nombre,
            max_age=3600,
        )
        response.headers['Cache-Control'] = 'private, max-age=3600'
        return response
    except ValueError:
        return 'La fotografía no está disponible.', 422
    except Exception:
        current_app.logger.exception(
            'tracking_photo_download_failed',
            extra={'photo_id': photo_id, 'ot_id': photo.ot_id},
        )
        return 'No fue posible cargar la fotografía.', 502


def _render_production(id):
    try:
        ot = db.session.get(CatalogoOT, id)
        if not ot or ot.archivado:
            return "OT no encontrada", 404

        return render_template('produccion.html', ot=ot, read_only=False)
    except Exception:
        traceback.print_exc()
        return "Error interno del servidor", 500


TRACKING_PROCESSES = PROCESS_DEFINITIONS


def _clamped_ratio(value, quantity):
    return clamped_ratio(value, quantity)


def _component_progress(component, weights=None, active_processes=None):
    if weights is None or active_processes is None:
        work_order = component.packing_list.ot_rel
        weights, active_processes = process_settings(work_order)
    return component_progress(component, weights, active_processes)


def _operator_assignments(raw_value):
    if not raw_value:
        return []

    assignments = []
    for value in raw_value.split('|'):
        value = value.strip()
        if not value:
            continue
        if ':' in value:
            process_key, operator_name = value.split(':', 1)
            process_key = process_key.strip()
            operator_name = operator_name.strip()
        else:
            process_key, operator_name = 'general', value
        if operator_name:
            names = [
                name.strip()
                for name in re.split(r'[,;\n]+', operator_name)
                if name.strip()
            ]
            for name in names:
                assignments.append((process_key, name))
    return assignments


def _tracking_audit_dict(event):
    data = event.to_dict()

    def replace_term(match):
        source = match.group(0)
        replacement = 'elementos' if source.casefold().endswith('s') else 'elemento'
        return replacement.capitalize() if source[:1].isupper() else replacement

    data['mensaje'] = re.sub(
        r'\bcomponentes?\b',
        replace_term,
        data.get('mensaje') or '',
        flags=re.IGNORECASE,
        )
    return data


def _tracking_process_breakdown(components, active_processes, weights):
    """Build the exact per-process state used by each tracking lot."""
    breakdown = []
    for key, name, field, _, accent_class in TRACKING_PROCESSES:
        is_active = bool(active_processes.get(key, False))
        ratios = []
        advanced_units = 0.0
        total_units = 0
        completed_count = 0
        in_progress_count = 0
        pending_count = 0

        for component in components:
            quantity = max(int(component.cantidad or 0), 0)
            ratio = _clamped_ratio(getattr(component, field), quantity)
            if ratio is None:
                continue

            ratios.append((ratio * 100.0, quantity))
            total_units += quantity
            advanced_units += ratio * quantity
            if ratio >= 0.9995:
                completed_count += 1
            elif ratio > 0:
                in_progress_count += 1
            else:
                pending_count += 1

        progress = round(quantity_weighted_average(ratios), 1) if ratios and is_active else 0.0
        if not is_active:
            status = 'No aplica'
        elif not ratios:
            status = 'Sin datos'
        elif progress >= 99.95:
            status = 'Completado'
        elif progress > 0:
            status = 'En proceso'
        else:
            status = 'Pendiente'

        rounded_advanced_units = round(advanced_units, 1)
        if rounded_advanced_units.is_integer():
            rounded_advanced_units = int(rounded_advanced_units)

        breakdown.append({
            'key': key,
            'name': name,
            'progress': progress,
            'status': status,
            'accent_class': accent_class,
            'active': is_active,
            'weight': weights.get(key, 0),
            'advanced_units': rounded_advanced_units,
            'total_units': total_units,
            'completed_count': completed_count,
            'in_progress_count': in_progress_count,
            'pending_count': pending_count,
            'applicable_count': len(ratios),
        })
    return breakdown


def _build_tracking_summary(ot_id):
    ensure_tracking_storage_schema()
    work_order = db.session.get(CatalogoOT, ot_id)
    if work_order is None or work_order.archivado:
        raise ValueError('La OT no existe.')
    weights, active_processes = process_settings(work_order)
    packing_lists = (
        PackingList.query.filter_by(ot_id=ot_id, archivado=False)
        .order_by(PackingList.orden.asc(), PackingList.id.asc())
        .all()
    )
    packing_list_ids = [packing_list.id for packing_list in packing_lists]
    components_by_pl = {packing_list_id: [] for packing_list_id in packing_list_ids}
    if packing_list_ids:
        all_components = (
            ComponenteOT.query.filter(ComponenteOT.pl_id.in_(packing_list_ids))
            .order_by(ComponenteOT.pl_id.asc(), ComponenteOT.id.asc())
            .all()
        )
        for component in all_components:
            components_by_pl[component.pl_id].append(component)
    process_ratios = {process[0]: [] for process in TRACKING_PROCESSES}
    personnel = {}
    lots = []
    all_component_progress = []

    for packing_list in packing_lists:
        components = components_by_pl.get(packing_list.id, [])
        fabrication = [
            component for component in components
            if component.tipo in ('fab', 'fabricacion')
        ]
        component_progress = [
            _component_progress(component, weights, active_processes)
            for component in fabrication
        ]
        progress_with_quantity = [
            (progress, component.cantidad)
            for progress, component in zip(component_progress, fabrication)
        ]
        all_component_progress.extend(progress_with_quantity)

        for component in fabrication:
            for key, _, field, _, _ in TRACKING_PROCESSES:
                ratio = _clamped_ratio(getattr(component, field), component.cantidad)
                if ratio is not None:
                    process_ratios[key].append((ratio * 100.0, component.cantidad))

            for process_key, operator_name in _operator_assignments(component.operario):
                operator_key = operator_name.casefold()
                entry = personnel.setdefault(operator_key, {
                    'name': operator_name,
                    'processes': set(),
                    'elements': {},
                    'lots': set(),
                })
                entry['processes'].add(process_key)
                entry['lots'].add(packing_list.nombre)
                element_detail = entry['elements'].setdefault(component.id, {
                    'id': component.id,
                    'code': component.marca or f'Elemento {component.id}',
                    'brand': component.marca or '',
                    'description': component.descripcion or 'Sin descripción registrada',
                    'lot': packing_list.nombre,
                    'process_keys': set(),
                })
                element_detail['process_keys'].add(process_key)

        lot_progress = round(
            quantity_weighted_average(progress_with_quantity), 1
        ) if component_progress else 0.0
        completed_count = sum(progress >= 99.95 for progress in component_progress)
        in_progress_count = sum(0 < progress < 99.95 for progress in component_progress)
        pending_count = sum(progress <= 0 for progress in component_progress)
        if not component_progress:
            lot_status = 'Sin datos'
        elif completed_count == len(component_progress):
            lot_status = 'Completado'
        elif lot_progress > 0:
            lot_status = 'En proceso'
        else:
            lot_status = 'Pendiente'

        lots.append({
            'id': packing_list.id,
            'name': packing_list.nombre,
            'progress': lot_progress,
            'status': lot_status,
            'component_count': len(fabrication),
            'unit_count': sum(max(component.cantidad or 0, 0) for component in fabrication),
            'completed_count': completed_count,
            'in_progress_count': in_progress_count,
            'pending_count': pending_count,
            'processes': _tracking_process_breakdown(
                fabrication,
                active_processes,
                weights,
            ),
        })

    process_names = {key: name for key, name, _, _, _ in TRACKING_PROCESSES}
    personnel_list = []
    for entry in personnel.values():
        process_labels = [
            process_names.get(key, 'General')
            for key in sorted(entry['processes'])
        ]
        element_details = []
        for element in entry['elements'].values():
            element_processes = [
                process_names.get(key, 'General')
                for key in sorted(element['process_keys'])
            ]
            element_details.append({
                'id': element['id'],
                'code': element['code'],
                'brand': element['brand'],
                'description': element['description'],
                'lot': element['lot'],
                'processes': ', '.join(element_processes),
            })
        personnel_list.append({
            'name': entry['name'],
            'initials': ''.join(
                part[0] for part in entry['name'].split()[:2] if part
            ).upper() or 'OP',
            'processes': ', '.join(process_labels),
            'component_count': len(element_details),
            'lot_count': len(entry['lots']),
            'elements': element_details,
        })
    personnel_list.sort(key=lambda entry: entry['name'].casefold())

    processes = []
    for key, name, _, _, accent_class in TRACKING_PROCESSES:
        ratios = process_ratios[key]
        is_active = bool(active_processes.get(key, False))
        progress = round(quantity_weighted_average(ratios), 1) if ratios and is_active else 0.0
        if not is_active:
            status = 'No aplica'
        elif not ratios:
            status = 'Sin datos'
        elif progress >= 99.95:
            status = 'Completado'
        elif progress > 0:
            status = 'En proceso'
        else:
            status = 'Pendiente'
        processes.append({
            'key': key,
            'name': name,
            'progress': progress,
            'status': status,
            'accent_class': accent_class,
            'active': is_active,
            'weight': weights.get(key, 0),
        })

    overall_progress = round(
        quantity_weighted_average(all_component_progress), 1
    ) if all_component_progress else 0.0
    component_progress_values = [progress for progress, _ in all_component_progress]
    manual_messages = (
        BitacoraOT.query.filter(
            BitacoraOT.ot_id == ot_id,
            or_(BitacoraOT.tipo == 'manual', BitacoraOT.tipo.is_(None)),
            )
        .order_by(BitacoraOT.fecha_creacion.desc())
        .limit(50)
        .all()
    )
    audit_events = (
        BitacoraOT.query.filter_by(ot_id=ot_id, tipo='audit')
        .order_by(BitacoraOT.fecha_creacion.desc())
        .limit(50)
        .all()
    )
    tracking_photos = (
        FotoSeguimiento.query.filter_by(ot_id=ot_id)
        .order_by(FotoSeguimiento.orden.asc(), FotoSeguimiento.id.asc())
        .all()
    )

    return {
        'overall_progress': overall_progress,
        'component_count': len(component_progress_values),
        'unit_count': sum(max(int(quantity or 0), 0) for _, quantity in all_component_progress),
        'completed_count': sum(progress >= 99.95 for progress in component_progress_values),
        'in_progress_count': sum(0 < progress < 99.95 for progress in component_progress_values),
        'pending_count': sum(progress <= 0 for progress in component_progress_values),
        'lot_count': len(packing_lists),
        'lots': lots,
        'processes': processes,
        'personnel': personnel_list,
        'photos': [_tracking_photo_dict(photo) for photo in tracking_photos],
        'manual_messages': [message.to_dict() for message in manual_messages],
        'audit_events': [_tracking_audit_dict(event) for event in audit_events],
    }
