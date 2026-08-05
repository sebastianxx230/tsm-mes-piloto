import re
import traceback

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func
from werkzeug.security import generate_password_hash

from db_config import db
from models.usuario import Usuario
from utils.auth import roles_required


admin_bp = Blueprint('admin_bp', __name__, template_folder='../templates')

ALLOWED_ROLES = {'admin', 'editor', 'viewer'}
USERNAME_PATTERN = re.compile(r'^[a-z0-9._-]{3,50}$')
MIN_PASSWORD_LENGTH = 8


def _validate_identity(nombre, username, rol):
    if not nombre or len(nombre) > 100:
        return 'El nombre es obligatorio y no puede superar 100 caracteres.'
    if not USERNAME_PATTERN.fullmatch(username):
        return (
            'El usuario debe tener entre 3 y 50 caracteres y solo puede usar '
            'letras minúsculas, números, punto, guion o guion bajo.'
        )
    if rol not in ALLOWED_ROLES:
        return 'El rol seleccionado no es válido.'
    return None


def _username_exists(username, excluded_user_id=None):
    query = Usuario.query.filter(func.lower(Usuario.username) == username)
    if excluded_user_id is not None:
        query = query.filter(Usuario.id != excluded_user_id)
    return query.first() is not None


def _active_admin_count():
    return Usuario.query.filter_by(rol='admin', activo=True).count()


@admin_bp.route('/admin/usuarios')
@login_required
@roles_required('admin')
def usuarios():
    users = Usuario.query.order_by(Usuario.activo.desc(), Usuario.nombre.asc()).all()
    stats = {
        'total': len(users),
        'active': sum(1 for user in users if user.activo),
        'admins': sum(1 for user in users if user.rol == 'admin'),
        'editors': sum(1 for user in users if user.rol == 'editor'),
        'viewers': sum(1 for user in users if user.rol == 'viewer'),
    }
    return render_template(
        'admin_usuarios.html',
        users=users,
        stats=stats,
        min_password_length=MIN_PASSWORD_LENGTH,
    )


@admin_bp.route('/admin/usuarios/crear', methods=['POST'])
@login_required
@roles_required('admin')
def crear_usuario():
    nombre = request.form.get('nombre', '').strip()
    username = request.form.get('username', '').strip().lower()
    rol = request.form.get('rol', '').strip().lower()
    password = request.form.get('password', '')
    password_confirmation = request.form.get('password_confirmation', '')

    validation_error = _validate_identity(nombre, username, rol)
    if validation_error:
        flash(validation_error, 'error')
        return redirect(url_for('admin_bp.usuarios'))
    if len(password) < MIN_PASSWORD_LENGTH:
        flash(
            f'La contraseña debe tener al menos {MIN_PASSWORD_LENGTH} caracteres.',
            'error',
        )
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
            rol=rol,
            activo=True,
            password_hash=generate_password_hash(password),
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
@roles_required('admin')
def actualizar_usuario(user_id):
    user = db.session.get(Usuario, user_id)
    if user is None:
        flash('El usuario solicitado no existe.', 'error')
        return redirect(url_for('admin_bp.usuarios'))

    nombre = request.form.get('nombre', '').strip()
    username = request.form.get('username', '').strip().lower()
    rol = request.form.get('rol', '').strip().lower()
    activo = request.form.get('activo') == '1'
    new_password = request.form.get('new_password', '')

    validation_error = _validate_identity(nombre, username, rol)
    if validation_error:
        flash(validation_error, 'error')
        return redirect(url_for('admin_bp.usuarios'))
    if _username_exists(username, excluded_user_id=user.id):
        flash('El nombre de usuario ya está registrado.', 'error')
        return redirect(url_for('admin_bp.usuarios'))
    if new_password and len(new_password) < MIN_PASSWORD_LENGTH:
        flash(
            f'La nueva contraseña debe tener al menos {MIN_PASSWORD_LENGTH} caracteres.',
            'error',
        )
        return redirect(url_for('admin_bp.usuarios'))

    if user.id == current_user.id and (rol != user.rol or not activo):
        flash('No puedes cambiar tu propio rol ni desactivar tu propia cuenta.', 'error')
        return redirect(url_for('admin_bp.usuarios'))

    removes_active_admin = (
        user.rol == 'admin'
        and user.activo
        and (rol != 'admin' or not activo)
    )
    if removes_active_admin and _active_admin_count() <= 1:
        flash('Debe permanecer al menos un administrador activo.', 'error')
        return redirect(url_for('admin_bp.usuarios'))

    try:
        user.nombre = nombre
        user.username = username
        user.rol = rol
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
