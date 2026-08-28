import re
import traceback

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func
from werkzeug.security import generate_password_hash

from db_config import db
from models.usuario import (
    LEGACY_ROLE_ASSIGNMENTS,
    RolSistema,
    Usuario,
)
from utils.auth import permission_required
from utils.rbac_catalog import ROLE_KEYS


admin_bp = Blueprint('admin_bp', __name__, template_folder='../templates')

USERNAME_PATTERN = re.compile(r'^[a-z0-9._-]{3,50}$')
MIN_PASSWORD_LENGTH = 8


def _validate_identity(nombre, username):
    if not nombre or len(nombre) > 100:
        return 'El nombre es obligatorio y no puede superar 100 caracteres.'
    if not USERNAME_PATTERN.fullmatch(username):
        return (
            'El usuario debe tener entre 3 y 50 caracteres y solo puede usar '
            'letras minúsculas, números, punto, guion o guion bajo.'
        )
    return None


def _username_exists(username, excluded_user_id=None):
    query = Usuario.query.filter(func.lower(Usuario.username) == username)
    if excluded_user_id is not None:
        query = query.filter(Usuario.id != excluded_user_id)
    return query.first() is not None


def _requested_role_keys():
    keys = list(dict.fromkeys(
        key.strip()
        for key in request.form.getlist('roles')
        if key.strip()
    ))
    # Compatibilidad con formularios y clientes V1 durante la transición.
    legacy_role = request.form.get('rol', '').strip().lower()
    if not keys and legacy_role:
        keys = sorted(LEGACY_ROLE_ASSIGNMENTS.get(legacy_role, set()))
    return keys


def _resolve_roles(keys):
    if not keys or not set(keys).issubset(ROLE_KEYS):
        return None
    roles = (
        RolSistema.query
        .filter(RolSistema.clave.in_(keys), RolSistema.activo.is_(True))
        .order_by(RolSistema.nombre.asc())
        .all()
    )
    return roles if len(roles) == len(set(keys)) else None


def _legacy_role_for(keys):
    keys = set(keys)
    if 'produccion_oficina' in keys:
        return 'editor'
    return 'viewer'


def _active_system_admin_count():
    return sum(
        user.activo and user.has_role('administrador_sistema')
        for user in Usuario.query.all()
    )


@admin_bp.route('/admin/usuarios')
@login_required
@permission_required('users.manage')
def usuarios():
    users = Usuario.query.order_by(Usuario.activo.desc(), Usuario.nombre.asc()).all()
    roles = RolSistema.query.filter_by(activo=True).order_by(RolSistema.nombre.asc()).all()
    stats = {
        'total': len(users),
        'active': sum(1 for user in users if user.activo),
        'admins': sum(user.has_role('administrador_sistema') for user in users),
        'office': sum(user.has_role('produccion_oficina') for user in users),
        'plant': sum(user.has_role('produccion_planta') for user in users),
    }
    return render_template(
        'admin_usuarios.html',
        users=users,
        roles=roles,
        stats=stats,
        min_password_length=MIN_PASSWORD_LENGTH,
    )


@admin_bp.route('/admin/usuarios/crear', methods=['POST'])
@login_required
@permission_required('users.manage')
def crear_usuario():
    nombre = request.form.get('nombre', '').strip()
    username = request.form.get('username', '').strip().lower()
    role_keys = _requested_role_keys()
    roles = _resolve_roles(role_keys)
    password = request.form.get('password', '')
    password_confirmation = request.form.get('password_confirmation', '')

    validation_error = _validate_identity(nombre, username)
    if validation_error:
        flash(validation_error, 'error')
        return redirect(url_for('admin_bp.usuarios'))
    if roles is None:
        flash('Selecciona al menos un rol funcional válido.', 'error')
        return redirect(url_for('admin_bp.usuarios'))
    if len(password) < MIN_PASSWORD_LENGTH:
        flash(f'La contraseña debe tener al menos {MIN_PASSWORD_LENGTH} caracteres.', 'error')
        return redirect(url_for('admin_bp.usuarios'))
    if password != password_confirmation:
        flash('La confirmación de contraseña no coincide.', 'error')
        return redirect(url_for('admin_bp.usuarios'))
    if _username_exists(username):
        flash('El nombre de usuario ya está registrado.', 'error')
        return redirect(url_for('admin_bp.usuarios'))

    try:
        user = Usuario(
            nombre=nombre,
            username=username,
            rol=_legacy_role_for(role_keys),
            activo=True,
            password_hash=generate_password_hash(password),
            roles=roles,
        )
        db.session.add(user)
        db.session.commit()
        flash(f'Acceso creado para {nombre}.', 'success')
    except Exception:
        db.session.rollback()
        traceback.print_exc()
        flash('Ocurrió un error al crear el usuario.', 'error')
    return redirect(url_for('admin_bp.usuarios'))


@admin_bp.route('/admin/usuarios/<int:user_id>/actualizar', methods=['POST'])
@login_required
@permission_required('users.manage')
def actualizar_usuario(user_id):
    user = db.session.get(Usuario, user_id)
    if user is None:
        flash('El usuario solicitado no existe.', 'error')
        return redirect(url_for('admin_bp.usuarios'))

    nombre = request.form.get('nombre', '').strip()
    username = request.form.get('username', '').strip().lower()
    role_keys = _requested_role_keys()
    roles = _resolve_roles(role_keys)
    activo = request.form.get('activo') == '1'
    new_password = request.form.get('new_password', '')

    validation_error = _validate_identity(nombre, username)
    if validation_error:
        flash(validation_error, 'error')
        return redirect(url_for('admin_bp.usuarios'))
    if roles is None:
        flash('Selecciona al menos un rol funcional válido.', 'error')
        return redirect(url_for('admin_bp.usuarios'))
    if _username_exists(username, excluded_user_id=user.id):
        flash('El nombre de usuario ya está registrado.', 'error')
        return redirect(url_for('admin_bp.usuarios'))
    if new_password and len(new_password) < MIN_PASSWORD_LENGTH:
        flash(f'La nueva contraseña debe tener al menos {MIN_PASSWORD_LENGTH} caracteres.', 'error')
        return redirect(url_for('admin_bp.usuarios'))

    existing_keys = {role.clave for role in user.roles}
    if user.id == current_user.id and (set(role_keys) != existing_keys or not activo):
        flash('No puedes cambiar tus propios roles ni desactivar tu cuenta.', 'error')
        return redirect(url_for('admin_bp.usuarios'))

    removes_system_admin = (
        user.activo
        and 'administrador_sistema' in existing_keys
        and ('administrador_sistema' not in role_keys or not activo)
    )
    if removes_system_admin and _active_system_admin_count() <= 1:
        flash('Debe permanecer al menos un administrador del sistema activo.', 'error')
        return redirect(url_for('admin_bp.usuarios'))

    try:
        user.nombre = nombre
        user.username = username
        user.rol = _legacy_role_for(role_keys)
        user.roles = roles
        user.activo = activo
        if new_password:
            user.password_hash = generate_password_hash(new_password)
        db.session.commit()
        flash(f'Acceso de {nombre} actualizado.', 'success')
    except Exception:
        db.session.rollback()
        traceback.print_exc()
        flash('Ocurrió un error al actualizar el usuario.', 'error')
    return redirect(url_for('admin_bp.usuarios'))
