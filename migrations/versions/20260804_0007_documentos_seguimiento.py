"""Add selected tracking documents.

Revision ID: 20260804_0007
Revises: 20260804_0006
"""

from alembic import op
import sqlalchemy as sa


revision = '20260804_0007'
down_revision = '20260804_0006'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'documentos_seguimiento',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ot_id', sa.Integer(), nullable=False),
        sa.Column('categoria', sa.String(length=20), nullable=False),
        sa.Column('drive_file_id', sa.String(length=150), nullable=False),
        sa.Column('drive_folder_id', sa.String(length=150), nullable=False),
        sa.Column('nombre', sa.String(length=255), nullable=False),
        sa.Column('mime_type', sa.String(length=150), nullable=False),
        sa.Column('tamano', sa.BigInteger(), nullable=True),
        sa.Column('carpeta_nombre', sa.String(length=255), nullable=False),
        sa.Column('actualizado_por_id', sa.Integer(), nullable=True),
        sa.Column(
            'fecha_actualizacion',
            sa.DateTime(),
            server_default=sa.text('NOW()'),
            nullable=False,
        ),
        sa.CheckConstraint(
            "categoria IN ('planos', 'otros')",
            name='ck_documentos_seguimiento_categoria',
        ),
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
            'categoria',
            name='uq_documentos_seguimiento_ot_categoria',
        ),
    )
    op.create_index(
        'ix_documentos_seguimiento_ot_categoria',
        'documentos_seguimiento',
        ['ot_id', 'categoria'],
        unique=False,
    )


def downgrade():
    op.drop_index(
        'ix_documentos_seguimiento_ot_categoria',
        table_name='documentos_seguimiento',
    )
    op.drop_table('documentos_seguimiento')
