"""Create the initial TSM schema."""

from alembic import op
import sqlalchemy as sa


revision = '20260730_0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'catalogo_ot',
        sa.Column('item', sa.Integer(), nullable=False),
        sa.Column('ot', sa.String(length=50), nullable=False),
        sa.Column('cliente', sa.String(length=100), nullable=False),
        sa.Column('fecha_iniciado', sa.Date(), nullable=False),
        sa.Column('descripcion', sa.Text(), nullable=True),
        sa.Column('estado', sa.String(length=30), nullable=True),
        sa.PrimaryKeyConstraint('item'),
        sa.UniqueConstraint('ot'),
    )
    op.create_table(
        'usuarios',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(length=50), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('rol', sa.String(length=20), nullable=False),
        sa.Column('activo', sa.Boolean(), nullable=True),
        sa.Column('nombre', sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('username'),
    )
    op.create_table(
        'packing_lists',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ot_id', sa.Integer(), nullable=False),
        sa.Column('nombre', sa.String(length=150), nullable=False),
        sa.Column('orden', sa.Integer(), nullable=True),
        sa.Column('fecha_creacion', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['ot_id'], ['catalogo_ot.item'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'bitacora_ot',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ot_id', sa.Integer(), nullable=False),
        sa.Column('usuario_id', sa.Integer(), nullable=True),
        sa.Column('usuario_nombre', sa.String(length=100), nullable=True),
        sa.Column('mensaje', sa.Text(), nullable=False),
        sa.Column('tipo', sa.String(length=50), nullable=True),
        sa.Column('fecha_creacion', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['ot_id'], ['catalogo_ot.item'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'componentes_ot',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('pl_id', sa.Integer(), nullable=False),
        sa.Column('marca', sa.String(length=100), nullable=False),
        sa.Column('cantidad', sa.Integer(), nullable=False),
        sa.Column('descripcion', sa.Text(), nullable=True),
        sa.Column('longitud', sa.String(length=50), nullable=True),
        sa.Column('tipo', sa.String(length=20), nullable=True),
        sa.Column('estado_suministro', sa.String(length=30), nullable=True),
        sa.Column('operario', sa.String(length=100), nullable=True),
        sa.Column('hab_real', sa.Integer(), nullable=True),
        sa.Column('arm_real', sa.Integer(), nullable=True),
        sa.Column('sol_real', sa.Integer(), nullable=True),
        sa.Column('lim_real', sa.Integer(), nullable=True),
        sa.Column('lib_real', sa.Integer(), nullable=True),
        sa.Column('gal_real', sa.Integer(), nullable=True),
        sa.Column('are_real', sa.Integer(), nullable=True),
        sa.Column('pin_real', sa.Integer(), nullable=True),
        sa.Column('des_real', sa.Integer(), nullable=True),
        sa.Column('alerta', sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(['pl_id'], ['packing_lists.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('componentes_ot')
    op.drop_table('bitacora_ot')
    op.drop_table('packing_lists')
    op.drop_table('usuarios')
    op.drop_table('catalogo_ot')
