import os
import re
from datetime import timedelta
from flask import Flask, jsonify, redirect, request, url_for
from whitenoise import WhiteNoise
from dotenv import load_dotenv
from db_config import db
from controllers.perfil_controller import perfil_bp
from extensions import limiter, migrate
from flask_login import LoginManager
from flask_wtf.csrf import CSRFError, CSRFProtect
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.pool import NullPool
from utils.logging_config import configure_structured_logging
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv()


def _normalize_database_url(raw_value):
    """Normalize common dashboard copy/paste formats without logging secrets."""
    if not raw_value:
        raise ValueError("DATABASE_URL no encontrada.")

    value = raw_value.strip().lstrip('\ufeff')
    if value.upper().startswith('DATABASE_URL='):
        value = value.split('=', 1)[1].strip()

    value = value.strip('"\'')
    if not value.startswith(('postgresql://', 'postgres://', 'sqlite:')):
        match = re.search(r'postgres(?:ql)?://[^\s\'\"]+', value)
        if match:
            value = match.group(0).rstrip(';')

    if value.startswith('postgres://'):
        value = value.replace('postgres://', 'postgresql://', 1)

    try:
        make_url(value)
    except ArgumentError as exc:
        raise ValueError(
            'DATABASE_URL tiene un formato invalido; pegue solo la connection string.'
        ) from exc

    return value


def _classify_database_error(error):
    """Return a safe diagnostic code without exposing the database URL."""
    messages = []
    current = error
    visited = set()

    while current is not None and id(current) not in visited:
        visited.add(id(current))
        messages.append(str(current).lower())
        current = getattr(current, 'orig', None) or getattr(current, '__cause__', None)

    message = ' '.join(messages)

    if any(marker in message for marker in (
        'password authentication failed',
        'authentication failed',
        'tenant or user not found',
    )):
        return 'authentication_failed'
    if any(marker in message for marker in (
        'could not translate host name',
        'name or service not known',
        'nodename nor servname provided',
        'getaddrinfo failed',
    )):
        return 'dns_failed'
    if 'connection refused' in message:
        return 'connection_refused'
    if any(marker in message for marker in ('timeout expired', 'timed out', 'connection timeout')):
        return 'connection_timeout'
    if 'database' in message and 'does not exist' in message:
        return 'database_not_found'
    if 'role' in message and 'does not exist' in message:
        return 'role_not_found'
    if any(marker in message for marker in ('invalid connection option', 'invalid dsn')):
        return 'invalid_connection_option'
    if any(marker in message for marker in ('ssl error', 'certificate verify failed')):
        return 'ssl_error'
    if any(marker in message for marker in ('network is unreachable', 'network unreachable')):
        return 'network_unavailable'

    return 'connection_failed'


def _env_flag(name, default=False):
    """Parse a boolean environment flag and fail closed on unknown values."""
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {'1', 'true', 'yes', 'on'}


app = Flask(
    __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/static'
)

proxy_hops = max(0, int(os.environ.get('TRUST_PROXY_HOPS', '1')))
app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=proxy_hops,
    x_proto=proxy_hops,
    x_host=proxy_hops,
    x_prefix=proxy_hops,
)

app.wsgi_app = WhiteNoise(app.wsgi_app, root='static/', prefix='static/')

secret_key = os.environ.get('SECRET_KEY')
if not secret_key:
    raise RuntimeError('SECRET_KEY no está configurada')
is_production = (
    os.environ.get('APP_ENV', '').lower() == 'production'
    or os.environ.get('VERCEL_ENV', '').lower() == 'production'
)
if is_production and len(secret_key) < 32:
    raise RuntimeError('SECRET_KEY debe tener al menos 32 caracteres en producción')
app.config['SECRET_KEY'] = secret_key
app.config['SESSION_COOKIE_PATH'] = '/'

session_hours = max(1, int(os.environ.get('SESSION_LIFETIME_HOURS', '10')))
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=session_hours)
app.config['SESSION_REFRESH_EACH_REQUEST'] = True
app.config['WTF_CSRF_TIME_LIMIT'] = session_hours * 60 * 60
app.config['WTF_CSRF_SSL_STRICT'] = os.environ.get(
    'WTF_CSRF_SSL_STRICT',
    'True' if is_production else 'False',
).lower() == 'true'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get(
    'SESSION_COOKIE_SECURE',
    'True',
).lower() == 'true'
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True

is_vercel = bool(os.environ.get('VERCEL'))
default_upload_mb = 4 if is_vercel else 50
max_content_mb = max(1, int(os.environ.get('MAX_CONTENT_MB', str(default_upload_mb))))
app.config['MAX_CONTENT_LENGTH'] = max_content_mb * 1024 * 1024
app.config['MAX_FORM_MEMORY_SIZE'] = max_content_mb * 1024 * 1024
app.config['RATELIMIT_STORAGE_URI'] = os.environ.get(
    'RATELIMIT_STORAGE_URI',
    'memory://',
)
app.config['RATELIMIT_HEADERS_ENABLED'] = True

db_url = _normalize_database_url(os.environ.get('DATABASE_URL'))

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
if is_vercel:
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': NullPool,
        'pool_pre_ping': True,
    }
else:
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
        'pool_size': max(1, int(os.environ.get('DB_POOL_SIZE', '5'))),
        'max_overflow': max(0, int(os.environ.get('DB_MAX_OVERFLOW', '5'))),
    }

db.init_app(app)
migrate.init_app(app, db)
limiter.init_app(app)
csrf = CSRFProtect(app)
configure_structured_logging(app)
if is_production and app.config['RATELIMIT_STORAGE_URI'] == 'memory://':
    app.logger.warning('production_rate_limit_uses_local_memory')

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login_bp.login'
login_manager.login_message = "Por favor, inicia sesión para acceder a TSM."
login_manager.login_message_category = "error"


def _expects_json_response():
    return (
        request.path.startswith('/api/')
        or request.path.startswith('/reporte/api/')
        or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or request.accept_mimetypes.best == 'application/json'
    )


@login_manager.unauthorized_handler
def unauthorized():
    message = 'Tu sesión venció. Inicia sesión nuevamente y repite la operación.'
    if _expects_json_response():
        return jsonify({
            'success': False,
            'error': message,
            'code': 'authentication_required',
        }), 401
    return redirect(url_for('login_bp.login', next=request.url))

# --- AÑADIDO: Importamos los modelos DESPUÉS de inicializar la app ---
from models.usuario import Usuario
from models.catalogo_ot import CatalogoOT
from models.produccion import PackingList, ComponenteOT, BitacoraOT, FotoSeguimiento
from models.documento_seguimiento import DocumentoSeguimiento

@login_manager.user_loader
def load_user(user_id):
    user = Usuario.get_by_id(user_id)
    return user if user and user.activo else None

# --- Importamos y registramos los blueprints ---
from controllers.gestion_ot_controller import gestion_ot_bp
from controllers.reporte_fotografico_controller import reporte_bp
from controllers.login_controller import login_bp
from controllers.produccion_controller import produccion_bp
from controllers.admin_controller import admin_bp
from controllers.documentos_seguimiento_controller import documentos_seguimiento_bp

app.register_blueprint(login_bp)
app.register_blueprint(gestion_ot_bp)
app.register_blueprint(reporte_bp)
app.register_blueprint(perfil_bp)
app.register_blueprint(produccion_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(documentos_seguimiento_bp)


def _database_unavailable_reason():
    """Return None when PostgreSQL is reachable, otherwise a safe reason code."""
    try:
        db.session.execute(text('SELECT 1'))
    except Exception as error:
        reason = _classify_database_error(error)
        db.session.rollback()
        app.logger.error(
            'database_connectivity_failed reason=%s exception_type=%s',
            reason,
            type(error).__name__,
        )
        return reason
    return None


if is_production and _env_flag('CHECK_DATABASE_ON_STARTUP'):
    with app.app_context():
        startup_database_error = _database_unavailable_reason()
        if startup_database_error:
            raise RuntimeError(
                f'PostgreSQL no esta disponible al iniciar ({startup_database_error}).'
            ) from None


@app.get('/health/live')
@limiter.exempt
def health_live():
    """Liveness probe that does not keep a scale-to-zero database awake."""
    return jsonify({'status': 'ok', 'service': 'tsm-mes'})


@app.get('/health')
@app.get('/health/ready')
@limiter.exempt
def health():
    """Comprueba que la aplicación y PostgreSQL están disponibles."""
    try:
        db.session.execute(text('SELECT 1'))
    except Exception as error:
        reason = _classify_database_error(error)
        db.session.rollback()
        app.logger.error(
            'healthcheck_database_failed reason=%s exception_type=%s',
            reason,
            type(error).__name__,
        )
        return jsonify({
            'status': 'unhealthy',
            'database': 'unavailable',
            'reason': reason,
        }), 503

    return jsonify({'status': 'ok', 'database': 'available'})


@app.errorhandler(429)
def ratelimit_exceeded(_error):
    message = 'Demasiados intentos. Espera un momento antes de volver a intentarlo.'
    if _expects_json_response():
        return jsonify({'success': False, 'error': message}), 429
    return message, 429


@app.errorhandler(CSRFError)
def csrf_error(error):
    message = 'Tu sesión de seguridad venció. Actualiza la página e inténtalo nuevamente.'
    app.logger.warning('csrf_validation_failed', extra={'reason': error.description})
    if _expects_json_response():
        return jsonify({'success': False, 'error': message, 'code': 'csrf_expired'}), 400
    return message, 400


@app.after_request
def set_security_headers(response):
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    response.headers.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
    if is_production and request.is_secure:
        response.headers.setdefault(
            'Strict-Transport-Security',
            'max-age=31536000; includeSubDomains',
        )
    return response

@app.route('/')
def index():
    return redirect(url_for('gestion_ot_bp.catalogo_ot'))

if __name__ == '__main__':
    modo_debug = os.environ.get('FLASK_DEBUG', 'False') == 'True'
    app.run(host='0.0.0.0', port=5000, debug=modo_debug)
