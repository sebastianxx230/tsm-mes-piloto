"""Add work-order versioning, process settings and archival.

Revision ID: 20260805_0009
Revises: 20260804_0008
"""

from alembic import op
import sqlalchemy as sa


revision = '20260805_0009'
down_revision = '20260804_0008'
branch_labels = None
depends_on = None


DEFAULT_WEIGHTS = '{"hab":12,"arm":24,"sol":28,"lim":12,"lib":6,"gal":6,"are":6,"pin":6,"des":0}'
DEFAULT_ACTIVE = '{"hab":true,"arm":true,"sol":true,"lim":true,"lib":true,"gal":true,"are":false,"pin":false,"des":true}'


def upgrade():
    op.add_column('catalogo_ot', sa.Column('version', sa.Integer(), server_default='1', nullable=False))
    op.add_column('catalogo_ot', sa.Column('process_weights', sa.JSON(), server_default=sa.text(f"'{DEFAULT_WEIGHTS}'::json"), nullable=False))
    op.add_column('catalogo_ot', sa.Column('active_processes', sa.JSON(), server_default=sa.text(f"'{DEFAULT_ACTIVE}'::json"), nullable=False))
    op.add_column('catalogo_ot', sa.Column('archivado', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('catalogo_ot', sa.Column('fecha_archivado', sa.DateTime(), nullable=True))
    op.add_column('catalogo_ot', sa.Column('archivado_por_id', sa.Integer(), nullable=True))
    op.add_column('catalogo_ot', sa.Column('fecha_actualizacion', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False))
    op.create_check_constraint('ck_catalogo_ot_version_positive', 'catalogo_ot', 'version >= 1')
    op.create_index('ix_catalogo_ot_archivado', 'catalogo_ot', ['archivado'])
    op.create_foreign_key('fk_catalogo_ot_archivado_por', 'catalogo_ot', 'usuarios', ['archivado_por_id'], ['id'], ondelete='SET NULL')
    op.add_column('packing_lists', sa.Column('archivado', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('packing_lists', sa.Column('fecha_archivado', sa.DateTime(), nullable=True))
    op.add_column('packing_lists', sa.Column('archivado_por_id', sa.Integer(), nullable=True))
    op.create_index('ix_packing_lists_archivado', 'packing_lists', ['archivado'])
    op.create_foreign_key('fk_packing_lists_archivado_por', 'packing_lists', 'usuarios', ['archivado_por_id'], ['id'], ondelete='SET NULL')


def downgrade():
    op.drop_constraint('fk_packing_lists_archivado_por', 'packing_lists', type_='foreignkey')
    op.drop_index('ix_packing_lists_archivado', table_name='packing_lists')
    for column in ('archivado_por_id', 'fecha_archivado', 'archivado'):
        op.drop_column('packing_lists', column)
    op.drop_constraint('fk_catalogo_ot_archivado_por', 'catalogo_ot', type_='foreignkey')
    op.drop_index('ix_catalogo_ot_archivado', table_name='catalogo_ot')
    op.drop_constraint('ck_catalogo_ot_version_positive', 'catalogo_ot', type_='check')
    for column in ('fecha_actualizacion', 'archivado_por_id', 'fecha_archivado', 'archivado', 'active_processes', 'process_weights', 'version'):
        op.drop_column('catalogo_ot', column)
