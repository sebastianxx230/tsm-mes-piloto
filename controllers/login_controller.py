import os

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_limiter.util import get_remote_address
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash

from extensions import limiter
from models.usuario import Usuario


login_bp = Blueprint('login_bp', __name__)
LOGIN_RATE_LIMIT = os.environ.get('LOGIN_RATE_LIMIT', '5 per minute')


def _login_rate_limit_key():
    username = request.form.get('username', '').strip().lower()
    return f'{get_remote_address()}:{username or "anonymous"}'


@login_bp.route('/', methods=['GET', 'POST'])
@limiter.limit(LOGIN_RATE_LIMIT, methods=['POST'], key_func=_login_rate_limit_key)
def login():
    if current_user.is_authenticated:
        return redirect(url_for('gestion_ot_bp.catalogo_ot'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '')
        user = Usuario.get_by_username(username)

        if user and check_password_hash(user.password_hash, password):
            if user.activo:
                login_user(user)
                session.permanent = True
                return redirect(url_for('gestion_ot_bp.catalogo_ot'))
            flash('Tu cuenta está desactivada. Contacta al administrador.', 'error')
        else:
            flash('Usuario o contraseña incorrectos.', 'error')

    return render_template('login.html')


@login_bp.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    flash('Sesión cerrada correctamente.', 'success')
    return redirect(url_for('login_bp.login'))
