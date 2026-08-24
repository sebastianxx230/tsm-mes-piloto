from functools import wraps
from flask import abort, flash, redirect, url_for
from flask_login import current_user


def _ensure_authorization_schema():
    # Importación local para evitar un ciclo al cargar modelos/controladores.
    from utils.production_schema import ensure_production_storage_schema
    ensure_production_storage_schema()

def roles_required(*roles):
    """Decorador para proteger rutas según el rol del usuario"""
    def wrapper(fn):
        @wraps(fn)
        def decorated_view(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('login_bp.login'))
            _ensure_authorization_schema()
            has_role = getattr(current_user, 'has_role', None)
            is_allowed = (
                has_role(*roles)
                if callable(has_role)
                else current_user.rol in roles
            )
            if not is_allowed:
                abort(403)  # Lanza un error 403 Forbidden (Acceso Denegado)
            return fn(*args, **kwargs)
        return decorated_view
    return wrapper


def permission_required(permission):
    """Protege nuevas rutas V2 mediante permisos, con respaldo V1 seguro."""
    def wrapper(fn):
        @wraps(fn)
        def decorated_view(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('login_bp.login'))
            _ensure_authorization_schema()
            has_permission = getattr(current_user, 'has_permission', None)
            if not callable(has_permission) or not has_permission(permission):
                abort(403)
            return fn(*args, **kwargs)
        return decorated_view
    return wrapper
