"""Add end date and expand operator assignments.

Revision ID: 20260804_0006
Revises: 20260804_0005
"""
from alembic import op
import sqlalchemy as sa

revision = '20260804_0006'
down_revision = '20260804_0005'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('catalogo_ot', sa.Column('fecha_termino', sa.Date(), nullable=True))
    op.alter_column('componentes_ot', 'operario', existing_type=sa.String(length=100), type_=sa.String(length=500), existing_nullable=False)

def downgrade():
    op.alter_column('componentes_ot', 'operario', existing_type=sa.String(length=500), type_=sa.String(length=100), existing_nullable=False)
    op.drop_column('catalogo_ot', 'fecha_termino')
