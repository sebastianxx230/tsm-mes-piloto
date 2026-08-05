import os

from db_config import db
from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from utils.auth import roles_required

from models.catalogo_ot import CatalogoOT
from models.produccion import BitacoraOT, ComponenteOT, PackingList, utc_now
from utils.production_metrics import (
    normalize_active_processes,
    normalize_process_weights,
    process_settings,
)


produccion_bp = Blueprint('produccion_bp', __name__)

EDITABLE_COMPONENT_FIELDS = {
    'marca',
    'cantidad',
    'descripcion',
    'longitud',
    'tipo',
    'estado_suministro',
    'operario',
    'hab_real',
    'arm_real',
    'sol_real',
    'lim_real',
    'lib_real',
    'gal_real',
    'are_real',
    'pin_real',
    'des_real',
    'alerta',
}

PROCESS_FIELDS = {
    'hab_real',
    'arm_real',
    'sol_real',
    'lim_real',
    'lib_real',
    'gal_real',
    'are_real',
    'pin_real',
    'des_real',
}

AUDIT_FIELD_LABELS = {
    'marca': 'marca',
    'cantidad': 'cantidad',
    'descripcion': 'descripción',
    'longitud': 'longitud',
    'tipo': 'tipo',
    'estado_suministro': 'estado de suministro',
    'operario': 'personal asignado',
    'hab_real': 'avance habilitado',
    'arm_real': 'avance armado',
    'sol_real': 'avance soldado',
    'lim_real': 'avance limpieza',
    'lib_real': 'avance liberación',
    'gal_real': 'avance galvanizado',
    'are_real': 'avance arenado',
    'pin_real': 'avance pintado',
    'des_real': 'avance despacho',
    'alerta': 'alerta',
}

ALLOWED_COMPONENT_TYPES = {
    'fab',
    'fabricacion',
    'p_template',
    'p_torre',
    'c_vida',
    'vientos',
    'suministro',
}

ALLOWED_SUPPLY_STATES = {
    'Pendiente',
    'No requerido',
    'En compra',
    'Comprado',
    'En almacén',
    'Despachado',
}

MIN_TRACKING_CODE_LENGTH = 2
MAX_TRACKING_RESULTS = 200
MAX_IMPORT_COMPONENTS = max(
    1,
    int(os.environ.get('MAX_IMPORT_COMPONENTS', '5000')),
)
MAX_MESSAGE_LENGTH = max(
    100,
    int(os.environ.get('MAX_MESSAGE_LENGTH', '2000')),
)
REQUIRE_IMPORT_VERSION = os.environ.get(
    'REQUIRE_IMPORT_VERSION',
    'True',
).lower() == 'true'
REQUIRE_COMPONENT_VERSION = os.environ.get(
    'REQUIRE_COMPONENT_VERSION',
    'True',
).lower() == 'true'


class ValidationError(ValueError):
    pass


def _get_json_object():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError('El cuerpo JSON no es válido.')
    return data


def _coerce_int(value, field_name, minimum=0, maximum=1_000_000):
    if isinstance(value, bool):
        raise ValidationError(f'El campo {field_name} debe ser numérico.')
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValidationError(
            f'El campo {field_name} debe ser numérico.'
        ) from None
    if parsed < minimum or parsed > maximum:
        raise ValidationError(
            f'El campo {field_name} debe estar entre {minimum} y {maximum}.'
        )
    return parsed


def _coerce_optional_int(value, field_name, minimum=0, maximum=1_000_000):
    if value is None or value == '':
        return None
    return _coerce_int(
        value,
        field_name,
        minimum=minimum,
        maximum=maximum,
    )


def _coerce_text(value, field_name, maximum, required=False):
    parsed = '' if value is None else str(value).strip()
    if required and not parsed:
        raise ValidationError(f'El campo {field_name} es obligatorio.')
    if len(parsed) > maximum:
        raise ValidationError(
            f'El campo {field_name} supera el máximo de {maximum} caracteres.'
        )
    return parsed


def _packing_list_name(value):
    return _coerce_text(
        value,
        'nombre',
        150,
        required=True,
    ).upper()


def _packing_list_name_exists(ot_id, name, excluded_id=None):
    query = PackingList.query.filter(
        PackingList.ot_id == ot_id,
        PackingList.archivado.is_(False),
        func.lower(PackingList.nombre) == name.lower(),
        )
    if excluded_id is not None:
        query = query.filter(PackingList.id != excluded_id)
    return query.first() is not None


def _locked_packing_lists_for_ot(ot_id):
    statement = (
        select(PackingList)
        .where(
            PackingList.ot_id == ot_id,
            PackingList.archivado.is_(False),
        )
        .order_by(PackingList.orden.asc(), PackingList.id.asc())
        .with_for_update()
    )
    return list(db.session.execute(statement).scalars())


def _apply_packing_list_order(packing_lists, ordered_ids=None):
    if ordered_ids is None:
        ordered = sorted(
            packing_lists,
            key=lambda item: (item.orden, item.id),
        )
    else:
        by_id = {packing_list.id: packing_list for packing_list in packing_lists}
        ordered = [by_id[packing_list_id] for packing_list_id in ordered_ids]

    # La restricción UNIQUE (ot_id, orden) exige liberar primero los valores
    # actuales. Usamos valores temporales positivos para respetar también el
    # CHECK que prohíbe órdenes negativos.
    temporary_base = max(
        (packing_list.orden for packing_list in packing_lists),
        default=-1,
    ) + len(ordered) + 1
    for index, packing_list in enumerate(ordered):
        packing_list.orden = temporary_base + index
    db.session.flush()

    for index, packing_list in enumerate(ordered):
        packing_list.orden = index
    db.session.flush()


def _validate_component_value(component, field_name, value):
    if field_name not in EDITABLE_COMPONENT_FIELDS:
        raise ValidationError('El campo solicitado no se puede editar.')

    if field_name == 'marca':
        return _coerce_text(value, field_name, 100, required=True)
    if field_name == 'descripcion':
        return _coerce_text(value, field_name, 5000)
    if field_name == 'longitud':
        return _coerce_text(value, field_name, 50)
    if field_name == 'operario':
        return _coerce_text(value, field_name, 500)
    if field_name == 'cantidad':
        quantity = _coerce_int(value, field_name)
        current_progress = [
            getattr(component, process_field) or 0
            for process_field in PROCESS_FIELDS
            if process_field != 'des_real'
        ]
        if any(progress > quantity for progress in current_progress):
            raise ValidationError(
                'La cantidad no puede ser menor que el avance ya registrado.'
            )
        if (component.des_real or 0) > quantity:
            raise ValidationError(
                'La cantidad no puede ser menor que el despacho registrado.'
            )
        return quantity
    if field_name in PROCESS_FIELDS:
        minimum = 0 if field_name == 'des_real' else -1
        return _coerce_int(
            value,
            field_name,
            minimum=minimum,
            maximum=max(component.cantidad or 0, 0),
        )
    if field_name == 'tipo':
        parsed = _coerce_text(value, field_name, 20, required=True)
        if parsed not in ALLOWED_COMPONENT_TYPES:
            raise ValidationError('El tipo de elemento no es válido.')
        return parsed
    if field_name == 'estado_suministro':
        parsed = _coerce_text(value, field_name, 30, required=True)
        if parsed not in ALLOWED_SUPPLY_STATES:
            raise ValidationError('El estado de suministro no es válido.')
        return parsed
    if field_name == 'alerta':
        if not isinstance(value, bool):
            raise ValidationError(
                'El campo alerta debe ser verdadero o falso.'
            )
        return value
    raise ValidationError('El campo solicitado no se puede editar.')


def _validate_import_component(component):
    if not isinstance(component, dict):
        raise ValidationError('Cada elemento debe ser un objeto JSON.')

    component_type = _coerce_text(
        component.get('tipo', 'fabricacion'),
        'tipo',
        20,
        required=True,
    )
    if component_type not in ALLOWED_COMPONENT_TYPES:
        raise ValidationError('El tipo de elemento no es válido.')

    supply_state = _coerce_text(
        component.get('estado_suministro', 'No requerido'),
        'estado_suministro',
        30,
        required=True,
    )
    if supply_state not in ALLOWED_SUPPLY_STATES:
        raise ValidationError('El estado de suministro no es válido.')

    quantity = _coerce_int(component.get('cantidad', 0), 'cantidad')

    def progress_value(source_name, target_name):
        minimum = 0 if target_name == 'des_real' else -1
        return _coerce_int(
            component.get(source_name, 0),
            target_name,
            minimum=minimum,
            maximum=quantity,
        )

    alert = component.get('alerta', False)
    if not isinstance(alert, bool):
        raise ValidationError(
            'El campo alerta debe ser verdadero o falso.'
        )

    return {
        'marca': _coerce_text(
            component.get('marca', 'S/M'),
            'marca',
            100,
            required=True,
        ),
        'cantidad': quantity,
        'descripcion': _coerce_text(
            component.get('descripcion', ''),
            'descripcion',
            5000,
        ),
        'longitud': _coerce_text(
            component.get('longitud', '0.0'),
            'longitud',
            50,
        ),
        'tipo': component_type,
        'estado_suministro': supply_state,
        'operario': _coerce_text(
            component.get('operario', ''),
            'operario',
            500,
        ),
        'hab_real': progress_value('hab', 'hab_real'),
        'arm_real': progress_value('arm', 'arm_real'),
        'sol_real': progress_value('sol', 'sol_real'),
        'lim_real': progress_value('lim', 'lim_real'),
        'lib_real': progress_value('lib', 'lib_real'),
        'gal_real': progress_value('gal', 'gal_real'),
        'are_real': progress_value('are', 'are_real'),
        'pin_real': progress_value('pin', 'pin_real'),
        'des_real': progress_value('des', 'des_real'),
        'alerta': alert,
    }


def _packing_list_etag(packing_list):
    return (
        f'packing-list-{packing_list.id}-'
        f'v{int(packing_list.version or 1)}'
    )


def _version_headers(response, packing_list):
    response.headers['X-Packing-List-Version'] = str(
        packing_list.version or 1
    )
    if packing_list.fecha_actualizacion:
        response.headers['X-Packing-List-Updated-At'] = (
            packing_list.fecha_actualizacion.isoformat()
        )
    response.set_etag(_packing_list_etag(packing_list))
    response.headers['Cache-Control'] = 'private, no-cache'
    return response


@produccion_bp.get('/api/produccion/packing_lists/<int:ot_id>')
@login_required
def obtener_pls(ot_id):
    work_order = db.session.get(CatalogoOT, ot_id)
    if work_order is None or work_order.archivado:
        return jsonify({
            'success': False,
            'error': 'La OT no existe.',
        }), 404

    packing_lists = (
        PackingList.query.filter_by(ot_id=ot_id, archivado=False)
        .order_by(PackingList.orden.asc(), PackingList.id.asc())
        .all()
    )
    return jsonify([packing_list.to_dict() for packing_list in packing_lists])


@produccion_bp.post('/api/produccion/packing_lists')
@login_required
@roles_required('admin', 'editor')
def crear_pl():
    try:
        data = _get_json_object()
        ot_id = _coerce_int(data.get('ot_id'), 'ot_id', minimum=1)
        name = _packing_list_name(data.get('nombre'))

        work_order = db.session.get(
            CatalogoOT,
            ot_id,
            with_for_update=True,
        )
        if work_order is None or work_order.archivado:
            return jsonify({
                'success': False,
                'error': 'La OT no existe.',
            }), 404

        packing_lists = _locked_packing_lists_for_ot(ot_id)
        if _packing_list_name_exists(ot_id, name):
            return jsonify({
                'success': False,
                'error': 'Ya existe una packing list con ese nombre en la OT.',
            }), 409

        max_order = db.session.execute(
            select(func.max(PackingList.orden)).where(PackingList.ot_id == ot_id)
        ).scalar_one_or_none()
        next_order = int(max_order if max_order is not None else -1) + 1
        new_packing_list = PackingList(
            ot_id=ot_id,
            nombre=name,
            orden=next_order,
        )
        db.session.add(new_packing_list)
        db.session.flush()

        db.session.add(BitacoraOT(
            ot_id=ot_id,
            usuario_id=current_user.id,
            usuario_nombre=getattr(
                current_user,
                'nombre',
                f'Usuario {current_user.id}',
            ),
            mensaje=f'Creó la packing list {name}.',
            tipo='audit',
        ))
        db.session.commit()
        return jsonify({
            'success': True,
            'pl': new_packing_list.to_dict(),
        }), 201
    except ValidationError as error:
        return jsonify({'success': False, 'error': str(error)}), 400
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': (
                'No fue posible crear la packing list porque el orden o el '
                'nombre ya está siendo utilizado.'
            ),
        }), 409
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            'packing_list_create_failed',
            extra={'user_id': current_user.get_id()},
        )
        return jsonify({
            'success': False,
            'error': 'Ocurrió un error interno al crear la packing list.',
        }), 500


@produccion_bp.put('/api/produccion/packing_lists/<int:pl_id>')
@login_required
@roles_required('admin')
def renombrar_pl(pl_id):
    try:
        data = _get_json_object()
        new_name = _packing_list_name(data.get('nombre'))
        packing_list = db.session.get(
            PackingList,
            pl_id,
            with_for_update=True,
        )
        if packing_list is None or packing_list.archivado:
            return jsonify({
                'success': False,
                'error': 'La packing list no existe.',
            }), 404

        if _packing_list_name_exists(
                packing_list.ot_id,
                new_name,
                excluded_id=packing_list.id,
        ):
            return jsonify({
                'success': False,
                'error': 'Ya existe una packing list con ese nombre en la OT.',
            }), 409

        previous_name = packing_list.nombre
        if previous_name == new_name:
            return jsonify({
                'success': True,
                'pl': packing_list.to_dict(),
            })

        packing_list.nombre = new_name
        packing_list.incrementar_version()
        db.session.add(BitacoraOT(
            ot_id=packing_list.ot_id,
            usuario_id=current_user.id,
            usuario_nombre=getattr(
                current_user,
                'nombre',
                f'Usuario {current_user.id}',
            ),
            mensaje=(
                f'Renombró la packing list {previous_name} a {new_name}.'
            ),
            tipo='audit',
        ))
        db.session.commit()
        return jsonify({
            'success': True,
            'pl': packing_list.to_dict(),
        })
    except ValidationError as error:
        return jsonify({'success': False, 'error': str(error)}), 400
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': 'Ya existe una packing list con ese nombre.',
        }), 409
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            'packing_list_rename_failed',
            extra={'packing_list_id': pl_id},
        )
        return jsonify({
            'success': False,
            'error': 'Ocurrió un error interno al renombrar la packing list.',
        }), 500


@produccion_bp.post('/api/produccion/packing_lists/reordenar')
@login_required
@roles_required('admin', 'editor')
def reordenar_pls():
    try:
        data = _get_json_object()
        raw_order = data.get('orden', [])
        if not isinstance(raw_order, list) or not raw_order:
            raise ValidationError(
                'El orden debe contener al menos una packing list.'
            )

        ordered_ids = [
            _coerce_int(
                packing_list_id,
                'packing_list_id',
                minimum=1,
            )
            for packing_list_id in raw_order
        ]
        if len(ordered_ids) != len(set(ordered_ids)):
            raise ValidationError(
                'El orden contiene identificadores repetidos.'
            )

        first_packing_list = db.session.get(PackingList, ordered_ids[0])
        if first_packing_list is None or first_packing_list.archivado:
            raise ValidationError('Una o más packing lists no existen.')

        packing_lists = _locked_packing_lists_for_ot(
            first_packing_list.ot_id
        )
        existing_ids = {item.id for item in packing_lists}
        if set(ordered_ids) != existing_ids:
            raise ValidationError(
                'Debes enviar todas las packing lists de la misma OT.'
            )

        _apply_packing_list_order(packing_lists, ordered_ids)
        db.session.commit()
        return jsonify({'success': True})
    except ValidationError as error:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(error)}), 400
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': 'No fue posible guardar el nuevo orden.',
        }), 409
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            'packing_list_reorder_failed',
            extra={'user_id': current_user.get_id()},
        )
        return jsonify({
            'success': False,
            'error': 'Ocurrió un error interno al reordenar las packing lists.',
        }), 500


@produccion_bp.delete('/api/produccion/packing_lists/<int:pl_id>')
@login_required
@roles_required('admin')
def eliminar_pl(pl_id):
    try:
        packing_list = db.session.get(
            PackingList,
            pl_id,
            with_for_update=True,
        )
        if packing_list is None or packing_list.archivado:
            return jsonify({
                'success': False,
                'error': 'La packing list no existe.',
            }), 404

        ot_id = packing_list.ot_id
        packing_list_name = packing_list.nombre
        max_order = db.session.execute(
            select(func.max(PackingList.orden)).where(PackingList.ot_id == ot_id)
        ).scalar_one_or_none()
        packing_list.orden = int(max_order if max_order is not None else -1) + 1
        packing_list.archivado = True
        packing_list.fecha_archivado = utc_now()
        packing_list.archivado_por_id = current_user.id
        packing_list.incrementar_version()
        db.session.flush()

        remaining = _locked_packing_lists_for_ot(ot_id)
        _apply_packing_list_order(remaining)
        db.session.add(BitacoraOT(
            ot_id=ot_id,
            usuario_id=current_user.id,
            usuario_nombre=getattr(
                current_user,
                'nombre',
                f'Usuario {current_user.id}',
            ),
            mensaje=(
                f'Archivó la packing list {packing_list_name} y conservó sus elementos.'
            ),
            tipo='audit',
        ))
        db.session.commit()
        return jsonify({'success': True})
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            'packing_list_delete_failed',
            extra={'packing_list_id': pl_id},
        )
        return jsonify({
            'success': False,
            'error': 'Ocurrió un error interno al eliminar la packing list.',
        }), 500


@produccion_bp.post('/api/produccion/importar')
@login_required
@roles_required('admin', 'editor')
def importar_excel():
    try:
        data = _get_json_object()
        packing_list_id = _coerce_int(
            data.get('pl_id'),
            'pl_id',
            minimum=1,
        )
        expected_version = _coerce_optional_int(
            data.get('expected_version'),
            'expected_version',
            minimum=1,
        )
        components = data.get('componentes', [])

        if not isinstance(components, list) or not components:
            return jsonify({
                'success': False,
                'error': 'La importación no contiene elementos.',
            }), 400
        if len(components) > MAX_IMPORT_COMPONENTS:
            return jsonify({
                'success': False,
                'error': (
                    'La importación supera el máximo de '
                    f'{MAX_IMPORT_COMPONENTS} elementos.'
                ),
            }), 413
        if REQUIRE_IMPORT_VERSION and expected_version is None:
            return jsonify({
                'success': False,
                'error': (
                    'Debes actualizar la pantalla antes de reemplazar los '
                    'elementos de esta packing list.'
                ),
            }), 428

        validated_components = [
            _validate_import_component(component)
            for component in components
        ]

        packing_list = db.session.get(
            PackingList,
            packing_list_id,
            with_for_update=True,
        )
        if packing_list is None or packing_list.archivado:
            return jsonify({
                'success': False,
                'error': 'La packing list no existe.',
            }), 404

        current_version = int(packing_list.version or 1)
        if (
                expected_version is not None
                and expected_version != current_version
        ):
            db.session.rollback()
            return jsonify({
                'success': False,
                'error': (
                    'Otra persona modificó esta packing list. Actualiza la '
                    'pantalla y revisa los cambios antes de importar.'
                ),
                'current_version': current_version,
            }), 409

        previous_count = ComponenteOT.query.filter_by(
            pl_id=packing_list_id
        ).count()
        ComponenteOT.query.filter_by(
            pl_id=packing_list_id
        ).delete(synchronize_session=False)

        db.session.add_all([
            ComponenteOT(
                pl_id=packing_list_id,
                **component,
            )
            for component in validated_components
        ])

        packing_list.incrementar_version()
        db.session.add(BitacoraOT(
            ot_id=packing_list.ot_id,
            usuario_id=current_user.id,
            usuario_nombre=getattr(
                current_user,
                'nombre',
                f'Usuario {current_user.id}',
            ),
            mensaje=(
                f'Reemplazó {previous_count} elementos por '
                f'{len(validated_components)} elementos en la packing list '
                f'{packing_list.nombre}.'
            ),
            tipo='audit',
        ))
        db.session.commit()

        if expected_version is None:
            current_app.logger.warning(
                'packing_list_import_without_version',
                extra={
                    'packing_list_id': packing_list_id,
                    'user_id': current_user.get_id(),
                },
            )

        response = jsonify({
            'success': True,
            'message': 'Importación guardada correctamente.',
            'version': packing_list.version,
            'replaced_count': previous_count,
            'imported_count': len(validated_components),
        })
        return _version_headers(response, packing_list)
    except ValidationError as error:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(error)}), 400
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': 'La importación contiene datos que violan la integridad.',
        }), 409
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            'packing_list_import_failed',
            extra={'user_id': current_user.get_id()},
        )
        return jsonify({
            'success': False,
            'error': 'Ocurrió un error interno al importar los elementos.',
        }), 500


@produccion_bp.get('/api/produccion/componentes/<int:pl_id>')
@login_required
def obtener_componentes(pl_id):
    try:
        packing_list = db.session.get(PackingList, pl_id)
        if packing_list is None or packing_list.archivado:
            return jsonify({
                'success': False,
                'error': 'La packing list no existe.',
            }), 404

        etag = _packing_list_etag(packing_list)
        if request.if_none_match and request.if_none_match.contains(etag):
            response = current_app.response_class(status=304)
            return _version_headers(response, packing_list)

        components = (
            ComponenteOT.query.filter_by(pl_id=pl_id)
            .order_by(ComponenteOT.id.asc())
            .all()
        )
        response = jsonify([
            component.to_dict()
            for component in components
        ])
        return _version_headers(response, packing_list)
    except Exception:
        current_app.logger.exception(
            'packing_list_components_load_failed',
            extra={'packing_list_id': pl_id},
        )
        return jsonify({
            'success': False,
            'error': 'Ocurrió un error al consultar los elementos.',
        }), 500


@produccion_bp.post('/api/produccion/actualizar_celda')
@login_required
@roles_required('admin', 'editor')
def actualizar_celda():
    try:
        data = _get_json_object()
        component_id = _coerce_int(data.get('id'), 'id', minimum=1)
        field_name = data.get('campo')

        if field_name not in EDITABLE_COMPONENT_FIELDS:
            return jsonify({
                'success': False,
                'error': 'El campo solicitado no se puede editar.',
            }), 400

        expected_version = _coerce_optional_int(
            data.get('expected_version'),
            'expected_version',
            minimum=1,
        )
        if REQUIRE_COMPONENT_VERSION and expected_version is None:
            return jsonify({
                'success': False,
                'error': 'Actualiza la pantalla antes de guardar este cambio.',
            }), 428

        component_pl_id = db.session.execute(
            select(ComponenteOT.pl_id).where(ComponenteOT.id == component_id)
        ).scalar_one_or_none()
        if component_pl_id is None:
            return jsonify({
                'success': False,
                'error': 'Elemento no encontrado.',
            }), 404

        packing_list = db.session.get(
            PackingList,
            component_pl_id,
            with_for_update=True,
        )
        if packing_list is None or packing_list.archivado:
            return jsonify({
                'success': False,
                'error': 'La packing list del elemento no existe.',
            }), 409
        current_version = int(packing_list.version or 1)
        if expected_version is not None and expected_version != current_version:
            db.session.rollback()
            return jsonify({
                'success': False,
                'error': 'Otra persona modificó esta packing list. Se recargarán los datos actuales.',
                'current_version': current_version,
            }), 409

        component = db.session.get(
            ComponenteOT,
            component_id,
            with_for_update=True,
        )
        if component is None or component.pl_id != packing_list.id:
            db.session.rollback()
            return jsonify({
                'success': False,
                'error': 'El elemento cambió mientras se guardaba. Actualiza la pantalla.',
            }), 409

        validated_value = _validate_component_value(
            component,
            field_name,
            data.get('valor'),
        )
        previous_value = getattr(component, field_name)
        if previous_value == validated_value:
            response = jsonify({'success': True, 'version': packing_list.version})
            return _version_headers(response, packing_list)

        setattr(component, field_name, validated_value)
        packing_list.incrementar_version()
        previous_text = str(
            previous_value if previous_value is not None else 'vacío'
        )[:120]
        current_text = str(
            validated_value if validated_value is not None else 'vacío'
        )[:120]
        db.session.add(BitacoraOT(
            ot_id=packing_list.ot_id,
            usuario_id=current_user.id,
            usuario_nombre=getattr(
                current_user,
                'nombre',
                f'Usuario {current_user.id}',
            ),
            mensaje=(
                f'Actualizó {AUDIT_FIELD_LABELS[field_name]} de '
                f'{previous_text} a {current_text} en el elemento '
                f'{component.marca}.'
            ),
            tipo='audit',
        ))
        db.session.commit()
        response = jsonify({'success': True, 'version': packing_list.version})
        return _version_headers(response, packing_list)
    except ValidationError as error:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(error)}), 400
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': 'El valor no cumple las restricciones de producción.',
        }), 409
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            'component_update_failed',
            extra={'user_id': current_user.get_id()},
        )
        return jsonify({
            'success': False,
            'error': 'Ocurrió un error interno al actualizar el elemento.',
        }), 500


@produccion_bp.put('/api/produccion/ot/<int:ot_id>/configuracion-procesos')
@login_required
@roles_required('admin', 'editor')
def actualizar_configuracion_procesos(ot_id):
    try:
        data = _get_json_object()
        expected_version = _coerce_int(
            data.get('expected_version'),
            'expected_version',
            minimum=1,
        )
        work_order = db.session.get(CatalogoOT, ot_id, with_for_update=True)
        if work_order is None or work_order.archivado:
            return jsonify({'success': False, 'error': 'La OT no existe.'}), 404
        if int(work_order.version or 1) != expected_version:
            db.session.rollback()
            return jsonify({
                'success': False,
                'error': 'Otra persona modificó la configuración de esta OT. Actualiza la pantalla.',
                'current_version': work_order.version,
            }), 409

        current_weights, current_active = process_settings(work_order)
        requested_weights = data.get('weights', current_weights)
        requested_active = data.get('active_processes', current_active)
        if not isinstance(requested_weights, dict) or not isinstance(requested_active, dict):
            raise ValidationError('La configuración de procesos no es válida.')
        weights = normalize_process_weights(requested_weights)
        active_processes = normalize_active_processes(requested_active)
        active_weight = sum(
            weights[key]
            for key, enabled in active_processes.items()
            if enabled and key != 'des'
        )
        if active_weight <= 0:
            raise ValidationError('Debe existir al menos un proceso productivo con peso mayor a cero.')

        work_order.process_weights = weights
        work_order.active_processes = active_processes
        work_order.incrementar_version()
        db.session.add(BitacoraOT(
            ot_id=work_order.item,
            usuario_id=current_user.id,
            usuario_nombre=getattr(current_user, 'nombre', f'Usuario {current_user.id}'),
            mensaje='Actualizó la configuración de pesos y procesos de la OT.',
            tipo='audit',
        ))
        db.session.commit()
        return jsonify({
            'success': True,
            'version': work_order.version,
            'weights': weights,
            'active_processes': active_processes,
        })
    except ValidationError as error:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(error)}), 400
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            'process_configuration_update_failed',
            extra={'ot_id': ot_id, 'user_id': current_user.get_id()},
        )
        return jsonify({
            'success': False,
            'error': 'No se pudo guardar la configuración de procesos.',
        }), 500


@produccion_bp.get('/api/mensajes/<int:ot_id>')
@login_required
def obtener_mensajes(ot_id):
    if db.session.get(CatalogoOT, ot_id) is None:
        return jsonify({
            'success': False,
            'error': 'La OT no existe.',
        }), 404

    messages = (
        BitacoraOT.query.filter(
            BitacoraOT.ot_id == ot_id,
            or_(
                BitacoraOT.tipo == 'manual',
                BitacoraOT.tipo.is_(None),
                ),
            )
        .order_by(BitacoraOT.fecha_creacion.asc())
        .all()
    )
    return jsonify([message.to_dict() for message in messages])


@produccion_bp.post('/api/mensajes/enviar')
@login_required
@roles_required('admin', 'editor')
def enviar_mensaje():
    try:
        data = _get_json_object()
        ot_id = _coerce_int(data.get('ot_id'), 'ot_id', minimum=1)
        message = _coerce_text(
            data.get('mensaje'),
            'mensaje',
            MAX_MESSAGE_LENGTH,
            required=True,
        )
        if db.session.get(CatalogoOT, ot_id) is None:
            return jsonify({
                'success': False,
                'error': 'La OT no existe.',
            }), 404

        new_message = BitacoraOT(
            ot_id=ot_id,
            usuario_id=current_user.id,
            usuario_nombre=getattr(
                current_user,
                'nombre',
                f'Usuario {current_user.id}',
            ),
            mensaje=message,
            tipo='manual',
        )
        db.session.add(new_message)
        db.session.commit()
        return jsonify({
            'success': True,
            'mensaje': new_message.to_dict(),
        })
    except ValidationError as error:
        return jsonify({'success': False, 'error': str(error)}), 400
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            'message_create_failed',
            extra={'user_id': current_user.get_id()},
        )
        return jsonify({
            'success': False,
            'error': 'Ocurrió un error interno al enviar el mensaje.',
        }), 500


@produccion_bp.delete('/api/mensajes/eliminar/<int:msg_id>')
@login_required
@roles_required('admin')
def eliminar_mensaje(msg_id):
    try:
        message = db.session.get(BitacoraOT, msg_id)
        if message is None:
            return jsonify({
                'success': False,
                'error': 'El mensaje no existe.',
            }), 404
        if message.tipo not in (None, 'manual'):
            return jsonify({
                'success': False,
                'error': (
                    'Los eventos del historial no se eliminan desde Mensajes.'
                ),
            }), 403

        db.session.delete(message)
        db.session.commit()
        return jsonify({'success': True})
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            'message_delete_failed',
            extra={'message_id': msg_id},
        )
        return jsonify({
            'success': False,
            'error': 'Ocurrió un error interno al eliminar el mensaje.',
        }), 500


@produccion_bp.get('/api/produccion/buscar_codigo/<string:codigo>')
@login_required
def buscar_por_codigo(codigo):
    try:
        normalized_code = codigo.strip().lower()
        if not MIN_TRACKING_CODE_LENGTH <= len(normalized_code) <= 100:
            return jsonify({
                'error': (
                    f'Ingresa al menos {MIN_TRACKING_CODE_LENGTH} caracteres.'
                ),
            }), 400

        escaped_code = (
            normalized_code
            .replace('\\', '\\\\')
            .replace('%', '\\%')
            .replace('_', '\\_')
        )
        is_prefix_search = (
                normalized_code.endswith('-')
                or normalized_code.isalpha()
        )
        search_pattern = (
            f'{escaped_code}%'
            if is_prefix_search
            else escaped_code
        )
        brand_expression = func.lower(ComponenteOT.marca)

        results = (
            db.session.query(
                CatalogoOT.ot,
                CatalogoOT.estado,
                PackingList.nombre.label('pl_nombre'),
                ComponenteOT.marca,
                ComponenteOT.descripcion,
                ComponenteOT.cantidad,
            )
            .select_from(ComponenteOT)
            .join(PackingList, ComponenteOT.pl_id == PackingList.id)
            .join(CatalogoOT, PackingList.ot_id == CatalogoOT.item)
            .filter(
                brand_expression.like(
                    search_pattern,
                    escape='\\',
                )
            )
            .order_by(
                CatalogoOT.ot.desc(),
                PackingList.orden.asc(),
                PackingList.id.asc(),
                ComponenteOT.marca.asc(),
                ComponenteOT.id.asc(),
            )
            .limit(MAX_TRACKING_RESULTS + 1)
            .all()
        )

        truncated = len(results) > MAX_TRACKING_RESULTS
        response = jsonify([
            {
                'ot': row.ot,
                'estado': row.estado,
                'pl_nombre': row.pl_nombre,
                'marca': row.marca,
                'descripcion': row.descripcion,
                'cantidad': row.cantidad,
            }
            for row in results[:MAX_TRACKING_RESULTS]
        ])
        response.headers['X-Result-Limit'] = str(MAX_TRACKING_RESULTS)
        response.headers['X-Results-Truncated'] = (
            'true' if truncated else 'false'
        )
        return response
    except Exception:
        current_app.logger.exception(
            'component_code_search_failed',
            extra={'query_length': len(codigo)},
        )
        return jsonify({
            'error': 'Ocurrió un error al realizar la búsqueda.',
        }), 500
