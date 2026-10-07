"""Initial migration with pgvector

Revision ID: 001_initial
Revises: 
Create Date: 2026-10-06 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    Vector = None

revision: str = '001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Habilitar extensión pgvector si estamos en PostgreSQL
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # Tabla products
    op.create_table(
        'products',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('nombre', sa.String(150), nullable=False),
        sa.Column('categoria', sa.Enum('tubos', 'planchas', 'perfiles', 'fierros', 'accesorios', name='productcategoryenum'), nullable=False),
        sa.Column('acabado', sa.Enum('negro', 'galvanizado', 'ninguno', name='productacabadoenum'), nullable=True),
        sa.Column('medida', sa.String(100), nullable=True),
        sa.Column('espesor', sa.String(50), nullable=True),
        sa.Column('descripcion_corta', sa.Text(), nullable=True),
        sa.Column('ficha_tecnica', sa.Text(), nullable=True),
        sa.Column('precio_unitario', sa.Numeric(10, 2), nullable=False),
        sa.Column('stock_disponible', sa.Integer(), server_default='0', nullable=False),
        sa.Column('imagen_url', sa.Text(), nullable=True),
        sa.Column('activo', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('embedding', Vector(1536) if Vector and bind.dialect.name == "postgresql" else sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_products_categoria', 'products', ['categoria'])
    op.create_index('ix_products_activo', 'products', ['activo'])

    # Tabla orders
    op.create_table(
        'orders',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('codigo', sa.String(20), nullable=False, unique=True),
        sa.Column('cliente_nombre', sa.String(150), nullable=False),
        sa.Column('cliente_telefono', sa.String(50), nullable=False),
        sa.Column('cliente_correo', sa.String(150), nullable=False),
        sa.Column('direccion', sa.Text(), nullable=True),
        sa.Column('recojo_en_tienda', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('observaciones', sa.Text(), nullable=True),
        sa.Column('estado', sa.Enum('pendiente', 'confirmado', 'entregado', 'cancelado', name='orderestadoenum'), server_default='pendiente', nullable=False),
        sa.Column('subtotal', sa.Numeric(10, 2), nullable=False),
        sa.Column('igv', sa.Numeric(10, 2), nullable=False),
        sa.Column('total', sa.Numeric(10, 2), nullable=False),
        sa.Column('acepto_privacidad', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_orders_codigo', 'orders', ['codigo'])

    # Tabla order_items
    op.create_table(
        'order_items',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('order_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('orders.id', ondelete='CASCADE'), nullable=False),
        sa.Column('product_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('products.id'), nullable=False),
        sa.Column('nombre_snapshot', sa.String(150), nullable=False),
        sa.Column('cantidad', sa.Integer(), nullable=False),
        sa.Column('precio_unitario_snapshot', sa.Numeric(10, 2), nullable=False),
    )

    # Tabla chat_logs
    op.create_table(
        'chat_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('id_conversacion', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('rol', sa.Enum('user', 'assistant', name='chatrolenum'), nullable=False),
        sa.Column('mensaje_texto', sa.Text(), nullable=False),
        sa.Column('longitud_mensaje', sa.Integer(), nullable=False),
        sa.Column('contiene_palabra_clave_producto', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('intencion_etiquetada', sa.Integer(), nullable=True),
    )
    op.create_index('ix_chat_logs_id_conversacion', 'chat_logs', ['id_conversacion'])

    # Tabla claims
    op.create_table(
        'claims',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('codigo_seguimiento', sa.String(30), nullable=False, unique=True),
        sa.Column('nombre', sa.String(150), nullable=False),
        sa.Column('documento', sa.String(20), nullable=False),
        sa.Column('telefono', sa.String(50), nullable=False),
        sa.Column('correo', sa.String(150), nullable=False),
        sa.Column('direccion', sa.Text(), nullable=False),
        sa.Column('tipo_bien', sa.Enum('producto', 'servicio', name='claimtipobienenum'), nullable=False),
        sa.Column('monto_reclamado', sa.Numeric(10, 2), nullable=True),
        sa.Column('descripcion_bien', sa.Text(), nullable=False),
        sa.Column('tipo', sa.Enum('reclamo', 'queja', name='claimtipoenum'), nullable=False),
        sa.Column('detalle', sa.Text(), nullable=False),
        sa.Column('pedido_consumidor', sa.Text(), nullable=False),
        sa.Column('fecha', sa.DateTime(timezone=True), nullable=False),
        sa.Column('estado', sa.Enum('pendiente', 'en_proceso', 'atendido', name='claimestadoenum'), server_default='pendiente', nullable=False),
    )
    op.create_index('ix_claims_codigo_seguimiento', 'claims', ['codigo_seguimiento'])

    # Tabla users
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('email', sa.String(150), nullable=False, unique=True),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('rol', sa.Enum('admin', name='userrolenum'), server_default='admin', nullable=False),
        sa.Column('activo', sa.Boolean(), server_default='true', nullable=False),
    )
    op.create_index('ix_users_email', 'users', ['email'])


def downgrade() -> None:
    op.drop_table('users')
    op.drop_table('claims')
    op.drop_table('chat_logs')
    op.drop_table('order_items')
    op.drop_table('orders')
    op.drop_table('products')

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        sa.Enum(name='userrolenum').drop(bind, checkfirst=True)
        sa.Enum(name='claimestadoenum').drop(bind, checkfirst=True)
        sa.Enum(name='claimtipoenum').drop(bind, checkfirst=True)
        sa.Enum(name='claimtipobienenum').drop(bind, checkfirst=True)
        sa.Enum(name='chatrolenum').drop(bind, checkfirst=True)
        sa.Enum(name='orderestadoenum').drop(bind, checkfirst=True)
        sa.Enum(name='productacabadoenum').drop(bind, checkfirst=True)
        sa.Enum(name='productcategoryenum').drop(bind, checkfirst=True)
