"""Add normalized V2 roles and permissions with V1 compatibility.

Revision ID: 20260821_0013
Revises: 20260821_0012
"""

from alembic import op
import sqlalchemy as sa


revision = '20260821_0013'
down_revision = '20260821_0012'
branch_labels = None
depends_on = None


PERMISSIONS = (
    ('sistema.administrar', 'Administrar sistema'),
    ('produccion.ver', 'Consultar producción'),
    ('produccion.editar', 'Registrar producción'),
    ('reportes.generar', 'Generar reportes'),
    ('planeamiento.editar', 'Gestionar planeamiento'),
    ('almacen.editar', 'Gestionar almacén'),
    ('logistica.editar', 'Gestionar logística'),
    ('calidad.editar', 'Gestionar calidad'),
    ('comercial.ver', 'Consultar información comercial'),
    ('gerencia.ver', 'Consultar indicadores gerenciales'),
    ('administracion.ver', 'Consultar indicadores administrativos'),
)

ROLES = (
    ('administrador_sistema', 'Administrador del sistema', ('*',)),
    ('produccion_oficina', 'Producción Oficina', (
        'produccion.ver', 'produccion.editar', 'reportes.generar',
    )),
    ('produccion_planta', 'Producción Planta', ('produccion.ver',)),
    ('planeamiento', 'Planeamiento', (
        'produccion.ver', 'planeamiento.editar',
    )),
    ('almacen', 'Almacén', ('produccion.ver', 'almacen.editar')),
    ('logistica', 'Logística', ('produccion.ver', 'logistica.editar')),
    ('calidad', 'Calidad', ('produccion.ver', 'calidad.editar')),
    ('comercial', 'Comercial', ('produccion.ver', 'comercial.ver')),
    ('gerencia', 'Gerencia', ('produccion.ver', 'gerencia.ver')),
    ('administracion', 'Administración', (
        'produccion.ver', 'administracion.ver',
    )),
)


def _tables(connection):
    return set(sa.inspect(connection).get_table_names())


def _seed(connection):
    permission_ids = {}
    for key, name in PERMISSIONS:
        permission_id = connection.execute(
            sa.text('SELECT id FROM permisos_sistema WHERE clave = :clave'),
            {'clave': key},
        ).scalar()
        if permission_id is None:
            connection.execute(
                sa.text(
                    'INSERT INTO permisos_sistema (clave, nombre) '
                    'VALUES (:clave, :nombre)'
                ),
                {'clave': key, 'nombre': name},
            )
            permission_id = connection.execute(
                sa.text(
                    'SELECT id FROM permisos_sistema WHERE clave = :clave'
                ),
                {'clave': key},
            ).scalar_one()
        permission_ids[key] = permission_id

    role_ids = {}
    for key, name, permissions in ROLES:
        role_id = connection.execute(
            sa.text('SELECT id FROM roles_sistema WHERE clave = :clave'),
            {'clave': key},
        ).scalar()
        if role_id is None:
            connection.execute(
                sa.text(
                    'INSERT INTO roles_sistema (clave, nombre, activo) '
                    'VALUES (:clave, :nombre, true)'
                ),
                {'clave': key, 'nombre': name},
            )
            role_id = connection.execute(
                sa.text('SELECT id FROM roles_sistema WHERE clave = :clave'),
                {'clave': key},
            ).scalar_one()
        role_ids[key] = role_id

        keys = tuple(permission_ids) if permissions == ('*',) else permissions
        for permission_key in keys:
            permission_id = permission_ids[permission_key]
            exists = connection.execute(
                sa.text(
                    'SELECT 1 FROM rol_permisos '
                    'WHERE rol_id = :rol_id AND permiso_id = :permiso_id'
                ),
                {'rol_id': role_id, 'permiso_id': permission_id},
            ).scalar()
            if not exists:
                connection.execute(
                    sa.text(
                        'INSERT INTO rol_permisos (rol_id, permiso_id) '
                        'VALUES (:rol_id, :permiso_id)'
                    ),
                    {'rol_id': role_id, 'permiso_id': permission_id},
                )

    legacy_mapping = {
        'admin': ('administrador_sistema', 'produccion_oficina'),
        'editor': ('produccion_oficina',),
        'viewer': ('produccion_planta',),
    }
    for user_id, legacy_role in connection.execute(
            sa.text('SELECT id, rol FROM usuarios')
    ).all():
        for role_key in legacy_mapping.get(legacy_role, ()):
            role_id = role_ids[role_key]
            exists = connection.execute(
                sa.text(
                    'SELECT 1 FROM usuario_roles '
                    'WHERE usuario_id = :usuario_id AND rol_id = :rol_id'
                ),
                {'usuario_id': user_id, 'rol_id': role_id},
            ).scalar()
            if not exists:
                connection.execute(
                    sa.text(
                        'INSERT INTO usuario_roles (usuario_id, rol_id) '
                        'VALUES (:usuario_id, :rol_id)'
                    ),
                    {'usuario_id': user_id, 'rol_id': role_id},
                )


def upgrade():
    connection = op.get_bind()
    tables = _tables(connection)

    if 'roles_sistema' not in tables:
        op.create_table(
            'roles_sistema',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('clave', sa.String(length=50), nullable=False),
            sa.Column('nombre', sa.String(length=100), nullable=False),
            sa.Column('descripcion', sa.Text(), nullable=True),
            sa.Column(
                'activo',
                sa.Boolean(),
                server_default=sa.text('true'),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('clave'),
        )

    tables = _tables(connection)
    if 'permisos_sistema' not in tables:
        op.create_table(
            'permisos_sistema',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('clave', sa.String(length=80), nullable=False),
            sa.Column('nombre', sa.String(length=120), nullable=False),
            sa.Column('descripcion', sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('clave'),
        )

    tables = _tables(connection)
    if 'usuario_roles' not in tables:
        op.create_table(
            'usuario_roles',
            sa.Column('usuario_id', sa.Integer(), nullable=False),
            sa.Column('rol_id', sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(
                ['rol_id'],
                ['roles_sistema.id'],
                name='fk_usuario_roles_rol',
                ondelete='CASCADE',
            ),
            sa.ForeignKeyConstraint(
                ['usuario_id'],
                ['usuarios.id'],
                name='fk_usuario_roles_usuario',
                ondelete='CASCADE',
            ),
            sa.PrimaryKeyConstraint('usuario_id', 'rol_id'),
        )

    tables = _tables(connection)
    if 'rol_permisos' not in tables:
        op.create_table(
            'rol_permisos',
            sa.Column('rol_id', sa.Integer(), nullable=False),
            sa.Column('permiso_id', sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(
                ['permiso_id'],
                ['permisos_sistema.id'],
                name='fk_rol_permisos_permiso',
                ondelete='CASCADE',
            ),
            sa.ForeignKeyConstraint(
                ['rol_id'],
                ['roles_sistema.id'],
                name='fk_rol_permisos_rol',
                ondelete='CASCADE',
            ),
            sa.PrimaryKeyConstraint('rol_id', 'permiso_id'),
        )

    _seed(connection)


def downgrade():
    op.drop_table('rol_permisos')
    op.drop_table('usuario_roles')
    op.drop_table('permisos_sistema')
    op.drop_table('roles_sistema')
