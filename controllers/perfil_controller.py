from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash

from db_config import db
from models.usuario import Usuario

import traceback


perfil_bp = Blueprint('perfil_bp', __name__, template_folder='../templates')


@perfil_bp.route('/mi-perfil', methods=['GET', 'POST'])
@login_required
def mi_perfil():
    if request.method == 'POST':
        nuevo_nombre = request.form.get('nombre', '').strip()
        nuevo_username = request.form.get('username', '').strip().lower()

        if not nuevo_nombre or not nuevo_username:
            flash('El nombre y el usuario son obligatorios.', 'error')
            return redirect(url_for('perfil_bp.mi_perfil'))

        if len(nuevo_username) < 3:
            flash('El nombre de usuario debe tener al menos 3 caracteres.', 'error')
            return redirect(url_for('perfil_bp.mi_perfil'))

        if ' ' in nuevo_username:
            flash('El nombre de usuario no puede contener espacios.', 'error')
            return redirect(url_for('perfil_bp.mi_perfil'))

        try:
            usuario_existente = Usuario.query.filter(
                Usuario.username == nuevo_username,
                Usuario.id != current_user.id
            ).first()

            if usuario_existente:
                flash('Ese nombre de usuario ya está en uso por otra persona.', 'error')
                return redirect(url_for('perfil_bp.mi_perfil'))

            usuario = db.session.get(Usuario, current_user.id)

            if not usuario:
                flash('No se encontró el usuario.', 'error')
                return redirect(url_for('perfil_bp.mi_perfil'))

            usuario.nombre = nuevo_nombre
            usuario.username = nuevo_username

            db.session.commit()

            flash('Perfil actualizado correctamente.', 'success')
            return redirect(url_for('perfil_bp.mi_perfil'))

        except Exception:
            db.session.rollback()
            traceback.print_exc()
            flash('Ocurrió un error al actualizar el perfil.', 'error')
            return redirect(url_for('perfil_bp.mi_perfil'))

    return render_template('mi_perfil.html')


@perfil_bp.route('/mi-perfil/cambiar-password', methods=['GET', 'POST'])
@login_required
def cambiar_password():
    if request.method == 'POST':
        password_actual = request.form.get('password_actual', '')
        password_nueva = request.form.get('password_nueva', '')
        password_confirmacion = request.form.get('password_confirmacion', '')

        if not password_actual or not password_nueva or not password_confirmacion:
            flash('Completa todos los campos obligatorios.', 'error')
            return redirect(url_for('perfil_bp.cambiar_password'))

        if not check_password_hash(current_user.password_hash, password_actual):
            flash('La contraseña actual no es correcta.', 'error')
            return redirect(url_for('perfil_bp.cambiar_password'))

        if len(password_nueva) < 8:
            flash('La nueva contraseña debe tener al menos 8 caracteres.', 'error')
            return redirect(url_for('perfil_bp.cambiar_password'))

        if password_nueva != password_confirmacion:
            flash('La confirmación no coincide con la nueva contraseña.', 'error')
            return redirect(url_for('perfil_bp.cambiar_password'))

        try:
            usuario = db.session.get(Usuario, current_user.id)

            if not usuario:
                flash('No se encontró el usuario.', 'error')
                return redirect(url_for('perfil_bp.mi_perfil'))

            usuario.password_hash = generate_password_hash(password_nueva)

            db.session.commit()

            flash('Contraseña actualizada correctamente.', 'success')
            return redirect(url_for('perfil_bp.mi_perfil'))

        except Exception:
            db.session.rollback()
            traceback.print_exc()
            flash('Ocurrió un error al actualizar la contraseña.', 'error')
            return redirect(url_for('perfil_bp.cambiar_password'))

    return render_template('cambiar_password.html')
