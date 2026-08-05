"""Add indexes used by catalog, production, and tracking queries."""

from alembic import op


revision = '20260730_0002'
down_revision = '20260730_0001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index('ix_catalogo_ot_fecha_iniciado', 'catalogo_ot', ['fecha_iniciado'])
    op.create_index('ix_catalogo_ot_estado', 'catalogo_ot', ['estado'])
    op.create_index('ix_packing_lists_ot_orden', 'packing_lists', ['ot_id', 'orden'])
    op.create_index('ix_componentes_ot_pl_id', 'componentes_ot', ['pl_id'])
    op.create_index('ix_componentes_ot_marca', 'componentes_ot', ['marca'])
    op.create_index('ix_bitacora_ot_ot_fecha', 'bitacora_ot', ['ot_id', 'fecha_creacion'])


def downgrade():
    op.drop_index('ix_bitacora_ot_ot_fecha', table_name='bitacora_ot')
    op.drop_index('ix_componentes_ot_marca', table_name='componentes_ot')
    op.drop_index('ix_componentes_ot_pl_id', table_name='componentes_ot')
    op.drop_index('ix_packing_lists_ot_orden', table_name='packing_lists')
    op.drop_index('ix_catalogo_ot_estado', table_name='catalogo_ot')
    op.drop_index('ix_catalogo_ot_fecha_iniciado', table_name='catalogo_ot')
