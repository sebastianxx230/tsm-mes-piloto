"""Add a case-insensitive index for global element tracking."""

from alembic import op


revision = '20260731_0003'
down_revision = '20260730_0002'
branch_labels = None
depends_on = None


def upgrade():
    dialect = op.get_bind().dialect.name
    if dialect == 'postgresql':
        # varchar_pattern_ops lets lower(marca) use the same index for both
        # equality and anchored prefix searches such as "ES-%".
        op.execute(
            'CREATE INDEX ix_componentes_ot_marca_lower_pattern '
            'ON componentes_ot (lower(marca) varchar_pattern_ops)'
        )
    else:
        op.execute(
            'CREATE INDEX ix_componentes_ot_marca_lower_pattern '
            'ON componentes_ot (lower(marca))'
        )


def downgrade():
    op.drop_index(
        'ix_componentes_ot_marca_lower_pattern',
        table_name='componentes_ot',
    )
