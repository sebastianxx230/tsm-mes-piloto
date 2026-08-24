import os
import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from db_config import db
from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from utils.auth import permission_required

from models.catalogo_ot import CatalogoOT
from models.produccion import (
    AvanceElementoProceso,
    BitacoraOT,
    ComponenteOT,
    ImportacionPackingList,
    PackingList,
    PersonalProduccion,
    ProcesoProduccion,
    RutaProceso,
    RutaProduccion,
    utc_now,
)
from utils.production_schema import ensure_production_storage_schema
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
    'fecha_realizacion',
    'fecha_inicio_real',
    'fecha_termino_real',
    'categoria',
    'subcategoria',
    'unidad',
    'ubicacion',
    'perfil',
    'material',
    'longitud_mm',
    'area_unitaria_m2',
    'area_total_m2',
    'peso_unitario_kg',
    'peso_total_kg',
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
    'fecha_realizacion': 'fecha de fabricación',
    'fecha_inicio_real': 'fecha de inicio del elemento',
    'fecha_termino_real': 'fecha de término del elemento',
    'categoria': 'categoría',
    'subcategoria': 'subcategoría',
    'unidad': 'unidad',
    'ubicacion': 'ubicación',
    'perfil': 'perfil',
    'material': 'material',
    'longitud_mm': 'longitud técnica',
    'area_unitaria_m2': 'área unitaria',
    'area_total_m2': 'área total',
    'peso_unitario_kg': 'peso unitario',
    'peso_total_kg': 'peso total',
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
    'perneria',
    'otro',
}

ALLOWED_ITEM_CATEGORIES = {
    'FABRICACION',
    'PERNERIA',
    'SUMINISTRO',
    'OTRO',
}

LEGACY_PROCESS_FIELDS = {
    'hab': 'hab_real',
    'arm': 'arm_real',
    'sol': 'sol_real',
    'lim': 'lim_real',
    'lib': 'lib_real',
    'gal': 'gal_real',
    'are': 'are_real',
    'pin': 'pin_real',
    'des': 'des_real',
}

PROCESS_NAMES = {
    'hab': 'Habilitado',
    'arm': 'Armado',
    'sol': 'Soldadura',
    'lim': 'Limpieza',
    'lib': 'Liberación',
    'gal': 'Galvanizado',
    'are': 'Arenado',
    'pin': 'Pintado',
    'des': 'Despacho',
}

DECIMAL_ITEM_FIELDS = {
    'longitud_mm': (14, 3),
    'area_unitaria_m2': (14, 4),
    'area_total_m2': (14, 4),
    'peso_unitario_kg': (14, 4),
    'peso_total_kg': (14, 4),
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


@produccion_bp.before_request
def _prepare_production_schema():
    ensure_production_storage_schema()


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


def _coerce_optional_decimal(
        value,
        field_name,
        precision=14,
        scale=4,
        minimum=Decimal('0'),
):
    if value is None or value == '':
        return None
    if isinstance(value, bool):
        raise ValidationError(f'El campo {field_name} debe ser numérico.')
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError(
            f'El campo {field_name} debe ser numérico.'
        ) from None
    if not parsed.is_finite() or parsed < minimum:
        raise ValidationError(
            f'El campo {field_name} debe ser mayor o igual a {minimum}.'
        )
    maximum = (Decimal(10) ** (precision - scale)) - (
        Decimal(10) ** -scale
    )
    if parsed > maximum:
        raise ValidationError(
            f'El campo {field_name} supera el máximo permitido.'
        )
    quantum = Decimal(1).scaleb(-scale)
    return parsed.quantize(quantum, rounding=ROUND_HALF_UP)


def _canonical_ot_code(value):
    """Normaliza OT 26-098, 26-0098 y 2026-0098 al código oficial."""
    raw = unicodedata.normalize('NFKC', str(value or '')).upper().strip()
    if not raw:
        return ''
    match = re.search(
        r'(?:\bOT\b|N[º°O.]?\s*O\.?\s*T\.?)?\s*'
        r'(20\d{2}|\d{2})\s*[-_/]\s*(\d{1,4})\b',
        raw,
    )
    if not match:
        return raw
    year = match.group(1)
    if len(year) == 2:
        year = f'20{year}'
    return f'{year}-{int(match.group(2)):04d}'


def _validate_import_ot(
        work_order,
        detected_codes,
        source_file=None,
        mismatch_confirmed=False,
):
    if detected_codes is None:
        return []
    if not isinstance(detected_codes, list):
        raise ValidationError('Los códigos OT detectados no son válidos.')
    canonical_codes = []
    for raw_code in detected_codes[:20]:
        code = _canonical_ot_code(raw_code)
        if code and code not in canonical_codes:
            canonical_codes.append(code)
    expected = _canonical_ot_code(work_order.ot)
    mismatches = [code for code in canonical_codes if code != expected]
    if mismatches:
        file_code = _canonical_ot_code(source_file)
        can_accept_stale_header = (
            mismatch_confirmed
            and file_code == expected
            and len(canonical_codes) == 1
        )
        if not can_accept_stale_header:
            raise ValidationError(
                'El Excel no corresponde a esta OT. Se esperaba '
                f'{expected}, pero se detectó {", ".join(mismatches)}.'
            )
    return canonical_codes, bool(mismatches)


def _classification(component_type, requested_category=None):
    legacy_type = str(component_type or 'fabricacion').strip().lower()
    requested = str(requested_category or '').strip().upper()
    if requested:
        if requested not in ALLOWED_ITEM_CATEGORIES:
            raise ValidationError('La categoría del elemento no es válida.')
        category = requested
    elif legacy_type in {'fab', 'fabricacion'}:
        category = 'FABRICACION'
    elif legacy_type in {'p_template', 'p_torre', 'perneria'}:
        category = 'PERNERIA'
    elif legacy_type in {'c_vida', 'vientos', 'suministro'}:
        category = 'SUMINISTRO'
    else:
        category = 'OTRO'

    subtype = {
        'p_template': 'TEMPLATE',
        'p_torre': 'TORRE',
        'c_vida': 'CABLE_DE_VIDA',
        'vientos': 'SISTEMA_DE_VIENTOS',
    }.get(legacy_type)
    return category, subtype


def _validated_import_metadata(data):
    raw = data.get('import_meta') or {}
    if not isinstance(raw, dict):
        raise ValidationError('Los metadatos de importación no son válidos.')
    warnings = raw.get('advertencias') or []
    if not isinstance(warnings, list):
        raise ValidationError('Las advertencias de importación no son válidas.')
    mismatch_confirmed = raw.get('ot_diferencia_confirmada', False)
    if not isinstance(mismatch_confirmed, bool):
        raise ValidationError(
            'La confirmación de diferencia de OT no es válida.'
        )
    return {
        'schema_version': _coerce_optional_int(
            raw.get('schema_version'),
            'schema_version',
            minimum=1,
            maximum=10,
        ) or 1,
        'archivo': _coerce_text(raw.get('archivo'), 'archivo', 255),
        'hoja': _coerce_text(raw.get('hoja'), 'hoja', 100),
        'site': _coerce_text(raw.get('site'), 'site', 150),
        'ruta_codigo': _coerce_text(
            raw.get('ruta_codigo'), 'ruta_codigo', 40
        ).upper(),
        'ot_detectadas': raw.get('ot_detectadas') or [],
        'ot_diferencia_confirmada': mismatch_confirmed,
        'advertencias': [
            _coerce_text(item, 'advertencia', 500)
            for item in warnings[:50]
            if str(item or '').strip()
        ],
    }


def _coerce_text(value, field_name, maximum, required=False):
    parsed = '' if value is None else str(value).strip()
    if required and not parsed:
        raise ValidationError(f'El campo {field_name} es obligatorio.')
    if len(parsed) > maximum:
        raise ValidationError(
            f'El campo {field_name} supera el máximo de {maximum} caracteres.'
        )
    return parsed


def _coerce_optional_date(value, field_name):
    if value is None or value == '':
        return None
    if not isinstance(value, str):
        raise ValidationError(f'El campo {field_name} debe ser una fecha.')
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise ValidationError(
            f'El campo {field_name} debe tener formato AAAA-MM-DD.'
        ) from None


def _validate_real_period(start_value, end_value):
    start_date = _coerce_optional_date(start_value, 'fecha_inicio_real')
    end_date = _coerce_optional_date(end_value, 'fecha_termino_real')
    if start_date and end_date and end_date < start_date:
        raise ValidationError(
            'La fecha real de término no puede ser anterior al inicio.'
        )
    return start_date, end_date


def _personnel_key(value):
    normalized = unicodedata.normalize('NFKD', str(value or ''))
    without_accents = ''.join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )
    return re.sub(r'\s+', ' ', without_accents).strip().casefold()


def _get_or_create_personnel(name):
    clean_name = _coerce_text(name, 'nombre del personal', 120, required=True)
    key = _personnel_key(clean_name)
    if not key:
        raise ValidationError('El nombre del personal no es válido.')

    person = PersonalProduccion.query.filter_by(nombre_clave=key).first()
    if person is None:
        person = PersonalProduccion(
            nombre=clean_name,
            nombre_clave=key,
        )
        db.session.add(person)
        db.session.flush()
    return person


def _canonicalize_personnel_assignments(raw_value):
    raw_value = _coerce_text(raw_value, 'operario', 500)
    if not raw_value:
        return ''

    canonical_segments = []
    for raw_segment in raw_value.split('|'):
        segment = raw_segment.strip()
        if not segment:
            continue
        if ':' in segment:
            process_key, raw_names = segment.split(':', 1)
            process_key = process_key.strip().lower()
        else:
            process_key, raw_names = 'general', segment

        names = []
        seen = set()
        for raw_name in re.split(r'[,;\n]+', raw_names):
            raw_name = raw_name.strip()
            if not raw_name:
                continue
            person = _get_or_create_personnel(raw_name)
            if person.nombre_clave in seen:
                continue
            seen.add(person.nombre_clave)
            names.append(person.nombre)
        if names:
            canonical_segments.append(
                f'{process_key}:{", ".join(names)}'
            )

    canonical = '|'.join(canonical_segments)
    if len(canonical) > 500:
        raise ValidationError(
            'La asignación de personal supera el máximo de 500 caracteres.'
        )
    return canonical


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
    if field_name == 'categoria':
        parsed = _coerce_text(value, field_name, 30, required=True).upper()
        if parsed not in ALLOWED_ITEM_CATEGORIES:
            raise ValidationError('La categoría del elemento no es válida.')
        return parsed
    if field_name == 'subcategoria':
        return _coerce_text(value, field_name, 50).upper() or None
    if field_name == 'unidad':
        return _coerce_text(value, field_name, 20, required=True).upper()
    if field_name == 'ubicacion':
        return _coerce_text(value, field_name, 255)
    if field_name == 'perfil':
        return _coerce_text(value, field_name, 150)
    if field_name == 'material':
        return _coerce_text(value, field_name, 150)
    if field_name in DECIMAL_ITEM_FIELDS:
        precision, scale = DECIMAL_ITEM_FIELDS[field_name]
        return _coerce_optional_decimal(
            value,
            field_name,
            precision=precision,
            scale=scale,
        )
    if field_name == 'operario':
        return _canonicalize_personnel_assignments(value)
    if field_name == 'fecha_realizacion':
        return _coerce_optional_date(value, field_name)
    if field_name in {'fecha_inicio_real', 'fecha_termino_real'}:
        parsed = _coerce_optional_date(value, field_name)
        start_date = parsed if field_name == 'fecha_inicio_real' else component.fecha_inicio_real
        end_date = parsed if field_name == 'fecha_termino_real' else component.fecha_termino_real
        if start_date and end_date and end_date < start_date:
            raise ValidationError(
                'La fecha de término del elemento no puede ser anterior al inicio.'
            )
        return parsed
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
        if field_name != 'des_real' and (value is None or value == ''):
            return None
        return _coerce_int(
            value,
            field_name,
            minimum=0,
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

    category, inferred_subcategory = _classification(
        component_type,
        component.get('categoria'),
    )
    subcategory = _coerce_text(
        component.get('subcategoria') or inferred_subcategory,
        'subcategoria',
        50,
    ).upper() or None

    supply_state = _coerce_text(
        component.get('estado_suministro', 'No requerido'),
        'estado_suministro',
        30,
        required=True,
    )
    if supply_state not in ALLOWED_SUPPLY_STATES:
        raise ValidationError('El estado de suministro no es válido.')

    quantity = _coerce_int(component.get('cantidad', 0), 'cantidad')

    decimals = {}
    for field_name, (precision, scale) in DECIMAL_ITEM_FIELDS.items():
        decimals[field_name] = _coerce_optional_decimal(
            component.get(field_name),
            field_name,
            precision=precision,
            scale=scale,
        )
    if decimals['longitud_mm'] is None:
        raw_length = component.get('longitud')
        try:
            decimals['longitud_mm'] = _coerce_optional_decimal(
                raw_length,
                'longitud_mm',
                precision=14,
                scale=3,
            )
        except ValidationError:
            decimals['longitud_mm'] = None

    quantity_decimal = Decimal(quantity)
    if (
            decimals['area_total_m2'] is None
            and decimals['area_unitaria_m2'] is not None
    ):
        decimals['area_total_m2'] = (
            decimals['area_unitaria_m2'] * quantity_decimal
        ).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
    if (
            decimals['peso_total_kg'] is None
            and decimals['peso_unitario_kg'] is not None
    ):
        decimals['peso_total_kg'] = (
            decimals['peso_unitario_kg'] * quantity_decimal
        ).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)

    def progress_value(source_name, target_name):
        default = 0 if target_name == 'des_real' else None
        raw_value = component.get(source_name, default)
        if target_name != 'des_real' and (
                raw_value is None or raw_value == '' or raw_value == -1
        ):
            return None
        return _coerce_int(
            raw_value,
            target_name,
            minimum=0,
            maximum=quantity,
        )

    alert = component.get('alerta', False)
    if not isinstance(alert, bool):
        raise ValidationError(
            'El campo alerta debe ser verdadero o falso.'
        )

    element_start = _coerce_optional_date(
        component.get('fecha_inicio_real'),
        'fecha_inicio_real',
    )
    element_end = _coerce_optional_date(
        component.get('fecha_termino_real')
        or component.get('fecha_realizacion'),
        'fecha_termino_real',
    )
    if element_start and element_end and element_end < element_start:
        raise ValidationError(
            'La fecha de término del elemento no puede ser anterior al inicio.'
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
        'categoria': category,
        'subcategoria': subcategory,
        'unidad': _coerce_text(
            component.get('unidad') or 'UND',
            'unidad',
            20,
            required=True,
        ).upper(),
        'ubicacion': _coerce_text(
            component.get('ubicacion'), 'ubicacion', 255
        ),
        'perfil': _coerce_text(component.get('perfil'), 'perfil', 150),
        'material': _coerce_text(
            component.get('material'), 'material', 150
        ),
        **decimals,
        'fila_origen': _coerce_optional_int(
            component.get('fila_origen'),
            'fila_origen',
            minimum=1,
            maximum=1_000_000,
        ),
        'ruta_codigo': _coerce_text(
            component.get('ruta_codigo'),
            'ruta_codigo',
            40,
        ).upper() or None,
        'tipo': component_type,
        'estado_suministro': supply_state,
        'operario': _canonicalize_personnel_assignments(
            component.get('operario', '')
        ),
        'fecha_realizacion': _coerce_optional_date(
            component.get('fecha_realizacion'),
            'fecha_realizacion',
        ),
        'fecha_inicio_real': element_start,
        'fecha_termino_real': element_end,
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


@produccion_bp.get('/api/produccion/personal')
@login_required
def listar_personal_produccion():
    personnel = (
        PersonalProduccion.query.filter_by(activo=True)
        .order_by(func.lower(PersonalProduccion.nombre).asc())
        .all()
    )
    return jsonify({
        'success': True,
        'personal': [person.to_dict() for person in personnel],
    })


@produccion_bp.post('/api/produccion/personal')
@login_required
@permission_required('production.personnel.assign')
def crear_personal_produccion():
    try:
        data = _get_json_object()
        name = _coerce_text(
            data.get('nombre'),
            'nombre del personal',
            120,
            required=True,
        )
        key = _personnel_key(name)
        existing = PersonalProduccion.query.filter_by(nombre_clave=key).first()
        if existing is not None:
            if not existing.activo:
                existing.activo = True
                db.session.commit()
            return jsonify({
                'success': True,
                'created': False,
                'person': existing.to_dict(),
            })

        person = PersonalProduccion(nombre=name, nombre_clave=key)
        db.session.add(person)
        db.session.commit()
        return jsonify({
            'success': True,
            'created': True,
            'person': person.to_dict(),
        }), 201
    except ValidationError as error:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(error)}), 400
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': 'Esa persona ya está registrada.',
        }), 409
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            'production_personnel_create_failed',
            extra={'user_id': current_user.get_id()},
        )
        return jsonify({
            'success': False,
            'error': 'No fue posible registrar a la persona.',
        }), 500


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
@permission_required('production.edit')
def crear_pl():
    try:
        data = _get_json_object()
        ot_id = _coerce_int(data.get('ot_id'), 'ot_id', minimum=1)
        name = _packing_list_name(data.get('nombre'))
        real_start, real_end = _validate_real_period(
            data.get('fecha_inicio_real'),
            data.get('fecha_termino_real'),
        )

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
            fecha_inicio_real=real_start,
            fecha_termino_real=real_end,
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
@permission_required('production.edit')
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


@produccion_bp.put('/api/produccion/packing_lists/<int:pl_id>/periodo')
@login_required
@permission_required('production.edit')
def actualizar_periodo_pl(pl_id):
    try:
        data = _get_json_object()
        expected_version = _coerce_optional_int(
            data.get('expected_version'),
            'expected_version',
            minimum=1,
        )
        if expected_version is None:
            raise ValidationError(
                'Actualiza la pantalla antes de modificar las fechas.'
            )
        real_start, real_end = _validate_real_period(
            data.get('fecha_inicio_real'),
            data.get('fecha_termino_real'),
        )
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
        if int(packing_list.version or 1) != expected_version:
            db.session.rollback()
            return jsonify({
                'success': False,
                'error': 'Otra persona modificó este lote. Actualiza la pantalla.',
                'current_version': packing_list.version,
            }), 409

        packing_list.fecha_inicio_real = real_start
        packing_list.fecha_termino_real = real_end
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
                f'Actualizó las fechas históricas de {packing_list.nombre}: '
                f'{real_start.strftime("%d/%m/%Y") if real_start else "sin inicio"} '
                f'a {real_end.strftime("%d/%m/%Y") if real_end else "sin término"}.'
            ),
            tipo='audit',
        ))
        db.session.commit()
        response = jsonify({
            'success': True,
            'pl': packing_list.to_dict(),
            'version': packing_list.version,
        })
        return _version_headers(response, packing_list)
    except ValidationError as error:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(error)}), 400
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            'packing_list_period_update_failed',
            extra={'packing_list_id': pl_id},
        )
        return jsonify({
            'success': False,
            'error': 'No fue posible actualizar las fechas históricas del lote.',
        }), 500


@produccion_bp.post('/api/produccion/packing_lists/reordenar')
@login_required
@permission_required('production.edit')
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
@permission_required('production.edit')
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


@produccion_bp.get('/api/produccion/rutas')
@login_required
def listar_rutas_produccion():
    routes = (
        RutaProduccion.query.filter_by(activo=True)
        .order_by(RutaProduccion.nombre.asc())
        .all()
    )
    return jsonify({
        'success': True,
        'rutas': [route.to_dict(include_processes=True) for route in routes],
    })


def _route_steps(route):
    if route is None:
        return []
    return (
        RutaProceso.query.filter_by(ruta_id=route.id)
        .order_by(RutaProceso.orden.asc())
        .all()
    )


def _initialize_legacy_route_progress(component_data, route_steps):
    """Mantiene la matriz V1 alineada durante la transición a procesos V2."""
    applicable = {step.proceso.codigo for step in route_steps}
    for process_code, field_name in LEGACY_PROCESS_FIELDS.items():
        if process_code == 'des':
            component_data[field_name] = max(
                int(component_data.get(field_name) or 0),
                0,
            )
        elif process_code in applicable:
            raw_value = component_data.get(field_name)
            component_data[field_name] = (
                max(int(raw_value), 0)
                if raw_value not in (None, '', -1)
                else None
            )
        else:
            component_data[field_name] = None

    # Si varios procesos fueron informados en el Excel/borrador, el avance de
    # un paso posterior nunca puede superar a un paso anterior ya informado.
    required = 0
    for step in reversed(route_steps):
        if step.proceso.codigo == 'des':
            continue
        field_name = LEGACY_PROCESS_FIELDS.get(step.proceso.codigo)
        value = component_data.get(field_name) if field_name else None
        if value is None or int(value) <= 0:
            continue
        if int(value) < required:
            component_data[field_name] = required
        else:
            required = int(value)


def _normalized_process_rows(component, route_steps, process_catalog, user_id):
    route_order = {
        step.proceso.codigo: step.orden
        for step in route_steps
    }
    applicable = set(route_order)
    rows = []
    for process in process_catalog:
        is_applicable = process.codigo in applicable
        legacy_field = LEGACY_PROCESS_FIELDS.get(process.codigo)
        legacy_value = getattr(component, legacy_field, None) if legacy_field else None
        completed = (
            max(int(legacy_value), 0)
            if is_applicable and legacy_value is not None
            else None
        )
        rows.append(AvanceElementoProceso(
            componente_id=component.id,
            proceso_id=process.id,
            orden=route_order.get(process.codigo, process.orden),
            aplica=is_applicable,
            cantidad_completada=completed,
            actualizado_por_id=user_id,
        ))
    return rows


def _sync_normalized_process_progress(component, field_name, value, user_id):
    """Replica una edición V1 en el avance normalizado durante la transición."""
    if field_name not in PROCESS_FIELDS:
        return
    process_code = next(
        (
            code
            for code, legacy_field in LEGACY_PROCESS_FIELDS.items()
            if legacy_field == field_name
        ),
        None,
    )
    if process_code is None:
        return
    process = ProcesoProduccion.query.filter_by(codigo=process_code).first()
    if process is None:
        return
    progress = AvanceElementoProceso.query.filter_by(
        componente_id=component.id,
        proceso_id=process.id,
    ).one_or_none()
    if progress is None:
        return

    completed = None if value is None else max(int(value), 0)
    progress.cantidad_completada = completed
    if completed is not None and completed > 0 and progress.fecha_inicio is None:
        progress.fecha_inicio = date.today()
    if completed is not None and completed >= max(component.cantidad or 0, 0):
        progress.fecha_fin = date.today()
    elif completed is None or completed < max(component.cantidad or 0, 0):
        progress.fecha_fin = None
    progress.actualizado_por_id = user_id
    progress.fecha_actualizacion = utc_now()


def _component_process_sequence(component):
    """Devuelve la secuencia aplicable sin confundir NULL con N/A."""
    if component.ruta_id:
        steps = (
            RutaProceso.query.filter_by(ruta_id=component.ruta_id)
            .order_by(RutaProceso.orden.asc())
            .all()
        )
        sequence = [step.proceso.codigo for step in steps]
        if sequence:
            return sequence
    return ['hab', 'arm', 'sol', 'lim', 'lib', 'gal', 'are', 'pin', 'des']


def _apply_process_sequence_rules(component, field_name, value, user_id):
    """Valida el flujo y eleva pasos previos que ya tenían avance."""
    if field_name == 'des_real' or value is None or int(value) <= 0:
        return {}
    process_code = next(
        (code for code, field in LEGACY_PROCESS_FIELDS.items() if field == field_name),
        None,
    )
    sequence = [code for code in _component_process_sequence(component) if code != 'des']
    if process_code not in sequence:
        return {}

    position = sequence.index(process_code)
    for later_code in sequence[position + 1:]:
        later_field = LEGACY_PROCESS_FIELDS[later_code]
        later_value = getattr(component, later_field)
        if later_value is not None and int(later_value) > int(value):
            raise ValidationError(
                f'{PROCESS_NAMES[process_code]} no puede quedar en {value}: '
                f'{PROCESS_NAMES[later_code]} ya registra {later_value}.'
            )

    adjusted = {}
    for previous_code in sequence[:position]:
        previous_field = LEGACY_PROCESS_FIELDS[previous_code]
        previous_value = getattr(component, previous_field)
        # Un proceso vacío/0 puede omitirse. Solo un avance positivo ya
        # informado participa en la regla de continuidad.
        if previous_value is None or int(previous_value) <= 0:
            continue
        if int(previous_value) < int(value):
            setattr(component, previous_field, int(value))
            _sync_normalized_process_progress(
                component,
                previous_field,
                int(value),
                user_id,
            )
            adjusted[previous_field] = int(value)
    return adjusted


@produccion_bp.post('/api/produccion/importar')
@login_required
@permission_required('production.edit')
def importar_excel():
    try:
        data = _get_json_object()
        import_metadata = _validated_import_metadata(data)
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
        has_real_period = (
            'fecha_inicio_real' in data
            or 'fecha_termino_real' in data
        )
        if has_real_period:
            real_start, real_end = _validate_real_period(
                data.get('fecha_inicio_real'),
                data.get('fecha_termino_real'),
            )
        else:
            real_start = real_end = None

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

        work_order = db.session.get(CatalogoOT, packing_list.ot_id)
        if work_order is None or work_order.archivado:
            return jsonify({
                'success': False,
                'error': 'La OT de la packing list no existe.',
            }), 404

        detected_codes, stale_ot_header_confirmed = _validate_import_ot(
            work_order,
            import_metadata['ot_detectadas'],
            source_file=import_metadata['archivo'],
            mismatch_confirmed=(
                import_metadata['ot_diferencia_confirmada']
            ),
        )
        if stale_ot_header_confirmed:
            expected_ot = _canonical_ot_code(work_order.ot)
            detected_ot = ', '.join(detected_codes)
            import_metadata['advertencias'].append(
                'Se confirmó manualmente la importación para '
                f'{expected_ot}; el encabezado del Excel indica '
                f'{detected_ot}.'
            )

        component_route_codes = {
            component['ruta_codigo']
            for component in validated_components
            if component['categoria'] == 'FABRICACION'
            and component['ruta_codigo']
        }
        if (
                not import_metadata['ruta_codigo']
                and len(component_route_codes) == 1
        ):
            import_metadata['ruta_codigo'] = next(iter(component_route_codes))
        elif (
                not import_metadata['ruta_codigo']
                and len(component_route_codes) > 1
        ):
            return jsonify({
                'success': False,
                'error': (
                    'La lista contiene más de una ruta. Selecciona una ruta '
                    'única antes de reemplazar los elementos.'
                ),
            }), 400

        route = None
        route_steps = []
        if import_metadata['ruta_codigo']:
            route = RutaProduccion.query.filter_by(
                codigo=import_metadata['ruta_codigo'],
                activo=True,
            ).one_or_none()
            if route is None:
                return jsonify({
                    'success': False,
                    'error': 'La ruta de fabricación seleccionada no existe.',
                }), 400
            route_steps = _route_steps(route)
            if not route_steps:
                return jsonify({
                    'success': False,
                    'error': 'La ruta seleccionada no contiene procesos.',
                }), 400

        fabrication_count = sum(
            component['categoria'] == 'FABRICACION'
            for component in validated_components
        )
        if (
                import_metadata['schema_version'] >= 2
                and fabrication_count
                and route is None
        ):
            return jsonify({
                'success': False,
                'error': (
                    'Selecciona una ruta para los elementos de fabricación.'
                ),
            }), 400

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

        previous_component_ids = [
            component_id
            for component_id, in db.session.query(ComponenteOT.id).filter_by(
                pl_id=packing_list_id
            ).all()
        ]
        previous_count = len(previous_component_ids)
        if previous_component_ids:
            AvanceElementoProceso.query.filter(
                AvanceElementoProceso.componente_id.in_(
                    previous_component_ids
                )
            ).delete(synchronize_session=False)
        ComponenteOT.query.filter_by(
            pl_id=packing_list_id
        ).delete(synchronize_session=False)

        import_record = ImportacionPackingList(
            pl_id=packing_list_id,
            archivo=import_metadata['archivo'] or None,
            hoja=import_metadata['hoja'] or None,
            ot_detectada=detected_codes[0] if detected_codes else None,
            cantidad_items=len(validated_components),
            advertencias=import_metadata['advertencias'],
            creado_por_id=current_user.id,
        )
        db.session.add(import_record)
        db.session.flush()

        new_components = []
        for component_data in validated_components:
            component_route = (
                route
                if component_data['categoria'] == 'FABRICACION'
                else None
            )
            if component_route is not None:
                _initialize_legacy_route_progress(
                    component_data,
                    route_steps,
                )
            component_values = dict(component_data)
            component_values.pop('ruta_codigo', None)
            component = ComponenteOT(
                pl_id=packing_list_id,
                ruta_id=component_route.id if component_route else None,
                importacion_id=import_record.id,
                **component_values,
            )
            db.session.add(component)
            new_components.append(component)
        db.session.flush()

        process_catalog = (
            ProcesoProduccion.query.filter_by(activo=True)
            .order_by(ProcesoProduccion.orden.asc())
            .all()
        )
        normalized_rows = []
        for component in new_components:
            if component.categoria != 'FABRICACION' or component.ruta_id is None:
                continue
            normalized_rows.extend(_normalized_process_rows(
                component,
                route_steps,
                process_catalog,
                current_user.id,
            ))
        db.session.add_all(normalized_rows)

        if has_real_period:
            packing_list.fecha_inicio_real = real_start
            packing_list.fecha_termino_real = real_end
        if import_metadata['schema_version'] >= 2:
            packing_list.site = import_metadata['site'] or None
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
                f'{packing_list.nombre}'
                + (f' con la ruta {route.nombre}.' if route else '.')
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

        fabrication_weight = sum(
            (
                component['peso_total_kg'] or Decimal('0')
                for component in validated_components
                if component['categoria'] == 'FABRICACION'
            ),
            Decimal('0'),
        )
        response = jsonify({
            'success': True,
            'message': 'Importación guardada correctamente.',
            'version': packing_list.version,
            'replaced_count': previous_count,
            'imported_count': len(validated_components),
            'import_id': import_record.id,
            'route': route.to_dict(include_processes=True) if route else None,
            'fabrication_weight_kg': float(fabrication_weight),
            'warnings': import_metadata['advertencias'],
            'pl': packing_list.to_dict(),
        })
        return _version_headers(response, packing_list)
    except ValidationError as error:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(error)}), 400
    except IntegrityError as error:
        db.session.rollback()
        constraint_name = getattr(
            getattr(error, 'orig', None),
            'diag',
            None,
        )
        current_app.logger.exception(
            'packing_list_import_integrity_failed constraint=%s',
            getattr(constraint_name, 'constraint_name', None),
            extra={'user_id': current_user.get_id()},
        )
        return jsonify({
            'success': False,
            'error': (
                'No se pudo guardar la importación. Recarga la página e '
                'inténtalo nuevamente.'
            ),
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
@permission_required('production.edit')
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

        component = db.session.execute(
            select(ComponenteOT)
            .where(ComponenteOT.id == component_id)
            .with_for_update(of=ComponenteOT)
        ).scalar_one_or_none()
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
        adjusted_fields = _apply_process_sequence_rules(
            component,
            field_name,
            validated_value,
            current_user.id,
        ) if field_name in PROCESS_FIELDS else {}
        if previous_value == validated_value and not adjusted_fields:
            response_payload = {
                'success': True,
                'version': packing_list.version,
            }
            if field_name in PROCESS_FIELDS:
                response_payload['adjusted_fields'] = {}
            response = jsonify(response_payload)
            return _version_headers(response, packing_list)

        setattr(component, field_name, validated_value)
        _sync_normalized_process_progress(
            component,
            field_name,
            validated_value,
            current_user.id,
        )
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
        response_payload = {
            'success': True,
            'version': packing_list.version,
        }
        if field_name in PROCESS_FIELDS:
            response_payload['adjusted_fields'] = adjusted_fields
        response = jsonify(response_payload)
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
@permission_required('production.process.edit')
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
@permission_required('messages.view')
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
@permission_required('messages.write')
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
@permission_required('messages.write')
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
