"""Store the Drive photos published in production tracking."""

from alembic import op
import sqlalchemy as sa


revision = '20260731_0004'
down_revision = '20260731_0003'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'fotos_seguimiento',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ot_id', sa.Integer(), nullable=False),
        sa.Column('drive_file_id', sa.String(length=150), nullable=False),
        sa.Column('nombre', sa.String(length=255), nullable=False),
        sa.Column('orden', sa.Integer(), nullable=False),
        sa.Column('actualizado_por_id', sa.Integer(), nullable=True),
        sa.Column('fecha_actualizacion', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ['actualizado_por_id'],
            ['usuarios.id'],
            ondelete='SET NULL',
        ),
        sa.ForeignKeyConstraint(
            ['ot_id'],
            ['catalogo_ot.item'],
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'ot_id',
            'drive_file_id',
            name='uq_fotos_seguimiento_ot_drive',
        ),
    )
    op.create_index(
        'ix_fotos_seguimiento_ot_orden',
        'fotos_seguimiento',
        ['ot_id', 'orden'],
        unique=False,
    )


def downgrade():
    op.drop_index(
        'ix_fotos_seguimiento_ot_orden',
        table_name='fotos_seguimiento',
    )
    op.drop_table('fotos_seguimiento')
