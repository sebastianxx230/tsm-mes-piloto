"""Expand V2 RBAC to functional MES permissions.

Revision ID: 20260824_0014
Revises: 20260821_0013
"""

from alembic import op
import sqlalchemy as sa

from utils.rbac_catalog import PERMISSION_SEED, ROLE_SEED


revision = '20260824_0014'
down_revision = '20260821_0013'
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    permission_ids = {}
    for key, name in PERMISSION_SEED:
        connection.execute(
            sa.text(
                'INSERT INTO permisos_sistema (clave, nombre) '
                'VALUES (:clave, :nombre) '
                'ON CONFLICT (clave) DO UPDATE SET nombre = EXCLUDED.nombre'
            ),
            {'clave': key, 'nombre': name},
        )
        permission_ids[key] = connection.execute(
            sa.text('SELECT id FROM permisos_sistema WHERE clave = :clave'),
            {'clave': key},
        ).scalar_one()

    for role_key, role_name, permissions in ROLE_SEED:
        connection.execute(
            sa.text(
                'INSERT INTO roles_sistema (clave, nombre, activo) '
                'VALUES (:clave, :nombre, true) '
                'ON CONFLICT (clave) DO UPDATE SET '
                'nombre = EXCLUDED.nombre, activo = true'
            ),
            {'clave': role_key, 'nombre': role_name},
        )
        role_id = connection.execute(
            sa.text('SELECT id FROM roles_sistema WHERE clave = :clave'),
            {'clave': role_key},
        ).scalar_one()
        connection.execute(
            sa.text('DELETE FROM rol_permisos WHERE rol_id = :rol_id'),
            {'rol_id': role_id},
        )
        for permission_key in permissions:
            connection.execute(
                sa.text(
                    'INSERT INTO rol_permisos (rol_id, permiso_id) '
                    'VALUES (:rol_id, :permiso_id)'
                ),
                {
                    'rol_id': role_id,
                    'permiso_id': permission_ids[permission_key],
                },
            )


def downgrade():
    # No se eliminan permisos para no romper asignaciones posteriores.
    pass
