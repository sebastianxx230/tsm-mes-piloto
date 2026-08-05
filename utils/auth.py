from functools import wraps
from flask import abort, flash, redirect, url_for
from flask_login import current_user

def roles_required(*roles):
    """Decorador para proteger rutas según el rol del usuario"""
    def wrapper(fn):
        @wraps(fn)
        def decorated_view(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('login_bp.login'))
            if current_user.rol not in roles:
                abort(403)  # Lanza un error 403 Forbidden (Acceso Denegado)
            return fn(*args, **kwargs)
        return decorated_view
    return wrapper