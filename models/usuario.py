from db_config import db
from flask_login import UserMixin


usuario_roles = db.Table(
    'usuario_roles',
    db.Column(
        'usuario_id',
        db.Integer,
        db.ForeignKey('usuarios.id', ondelete='CASCADE'),
        primary_key=True,
    ),
    db.Column(
        'rol_id',
        db.Integer,
        db.ForeignKey('roles_sistema.id', ondelete='CASCADE'),
        primary_key=True,
    ),
)

rol_permisos = db.Table(
    'rol_permisos',
    db.Column(
        'rol_id',
        db.Integer,
        db.ForeignKey('roles_sistema.id', ondelete='CASCADE'),
        primary_key=True,
    ),
    db.Column(
        'permiso_id',
        db.Integer,
        db.ForeignKey('permisos_sistema.id', ondelete='CASCADE'),
        primary_key=True,
    ),
)


class RolSistema(db.Model):
    """Rol funcional V2; puede asignarse junto con otros roles al usuario."""

    __tablename__ = 'roles_sistema'

    id = db.Column(db.Integer, primary_key=True)
    clave = db.Column(db.String(50), unique=True, nullable=False)
    nombre = db.Column(db.String(100), nullable=False)
    descripcion = db.Column(db.Text, nullable=True)
    activo = db.Column(
        db.Boolean,
        nullable=False,
        default=True,
        server_default='true',
    )
    permisos = db.relationship(
        'PermisoSistema',
        secondary=rol_permisos,
        lazy='select',
        back_populates='roles',
    )

    def to_dict(self):
        return {
            'id': self.id,
            'clave': self.clave,
            'nombre': self.nombre,
            'descripcion': self.descripcion,
            'activo': self.activo,
            'permisos': sorted(permission.clave for permission in self.permisos),
        }


class PermisoSistema(db.Model):
    """Permiso atómico que desacopla autorización de un nombre de rol."""

    __tablename__ = 'permisos_sistema'

    id = db.Column(db.Integer, primary_key=True)
    clave = db.Column(db.String(80), unique=True, nullable=False)
    nombre = db.Column(db.String(120), nullable=False)
    descripcion = db.Column(db.Text, nullable=True)
    roles = db.relationship(
        'RolSistema',
        secondary=rol_permisos,
        lazy='select',
        back_populates='permisos',
    )


class Usuario(db.Model, UserMixin):
    __tablename__ = 'usuarios'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    rol = db.Column(db.String(20), nullable=False) # 'admin', 'editor', 'viewer'
    activo = db.Column(db.Boolean, default=True)
    nombre = db.Column(db.String(100), nullable=False)
    roles = db.relationship(
        'RolSistema',
        secondary=usuario_roles,
        lazy='select',
        backref=db.backref('usuarios', lazy='select'),
    )

    LEGACY_ROLE_ALIASES = {
        'admin': {'administrador_sistema'},
        'editor': {'produccion_oficina'},
        'viewer': {'produccion_planta'},
    }

    LEGACY_PERMISSION_FALLBACK = {
        'admin': {
            'users.manage', 'roles.manage', 'permissions.manage',
            'settings.manage', 'audit.view',
        },
        'editor': {
            'ot.view', 'ot.create', 'ot.edit',
            'production.view', 'production.summary.view', 'production.edit',
            'production.process.edit', 'production.personnel.assign',
            'warehouse.view', 'documents.view', 'documents.upload',
            'documents.publish', 'photos.view', 'photos.upload',
            'photos.publish', 'reports.view', 'reports.generate',
            'reports.export',
            'produccion.ver', 'produccion.editar', 'reportes.generar',
        },
        'viewer': {
            'ot.view', 'production.view', 'production.summary.view',
            'documents.view', 'photos.view', 'reports.view',
            'produccion.ver',
        },
    }

    @property
    def role_keys(self):
        assigned = {
            role.clave
            for role in self.roles
            if role.activo
        }
        if self.rol:
            assigned.add(self.rol)
        return assigned

    def has_role(self, *role_keys):
        assigned = self.role_keys
        for requested in role_keys:
            if requested in assigned:
                return True
            aliases = self.LEGACY_ROLE_ALIASES.get(requested, set())
            if aliases & assigned:
                return True
        return False

    def has_permission(self, permission_key):
        for role in self.roles:
            if role.activo and any(
                    permission.clave in {permission_key, '*'}
                    for permission in role.permisos
            ):
                return True
        fallback = self.LEGACY_PERMISSION_FALLBACK.get(self.rol, set())
        return '*' in fallback or permission_key in fallback

    @staticmethod
    def get_by_id(user_id):
        return db.session.get(Usuario, int(user_id))

    @staticmethod
    def get_by_username(username):
        return Usuario.query.filter_by(username=username).first()


LEGACY_ROLE_ASSIGNMENTS = {
    'admin': {'administrador_sistema', 'produccion_oficina'},
    'editor': {'produccion_oficina'},
    'viewer': {'produccion_planta'},
}


def sync_legacy_role_assignments(user):
    """Alinea el selector V1 con roles V2 sin borrar roles especializados."""
    compatibility_keys = set().union(*LEGACY_ROLE_ASSIGNMENTS.values())
    desired_keys = LEGACY_ROLE_ASSIGNMENTS.get(user.rol, set())
    preserved = [
        role for role in user.roles
        if role.clave not in compatibility_keys
    ]
    desired = (
        RolSistema.query.filter(RolSistema.clave.in_(desired_keys)).all()
        if desired_keys
        else []
    )
    user.roles = preserved + desired
