from datetime import datetime, timezone
import enum
import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Uuid as UUID,
)
from sqlalchemy.orm import relationship
from sqlalchemy.types import JSON, TypeDecorator

from app.db.base import Base

try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    Vector = None


class SafeVector(TypeDecorator):
    """Tipo decorado seguro para soportar pgvector en PostgreSQL y JSON/Text en SQLite para tests."""

    impl = Vector(1536) if Vector is not None else JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql" and Vector is not None:
            return dialect.type_descriptor(Vector(1536))
        return dialect.type_descriptor(JSON())


class ProductCategoryEnum(str, enum.Enum):
    tubos = "tubos"
    planchas = "planchas"
    perfiles = "perfiles"
    fierros = "fierros"
    accesorios = "accesorios"


class ProductAcabadoEnum(str, enum.Enum):
    negro = "negro"
    galvanizado = "galvanizado"
    ninguno = "ninguno"


class OrderEstadoEnum(str, enum.Enum):
    pendiente = "pendiente"
    confirmado = "confirmado"
    entregado = "entregado"
    cancelado = "cancelado"


class ChatRolEnum(str, enum.Enum):
    user = "user"
    assistant = "assistant"


class ClaimTipoBienEnum(str, enum.Enum):
    producto = "producto"
    servicio = "servicio"


class ClaimTipoEnum(str, enum.Enum):
    reclamo = "reclamo"
    queja = "queja"


class ClaimEstadoEnum(str, enum.Enum):
    pendiente = "pendiente"
    en_proceso = "en_proceso"
    atendido = "atendido"


class UserRolEnum(str, enum.Enum):
    admin = "admin"


class Product(Base):
    __tablename__ = "products"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nombre = Column(String(150), nullable=False)
    categoria = Column(Enum(ProductCategoryEnum), nullable=False, index=True)
    acabado = Column(Enum(ProductAcabadoEnum), nullable=True)
    medida = Column(String(100), nullable=True)
    espesor = Column(String(50), nullable=True)
    descripcion_corta = Column(Text, nullable=True)
    ficha_tecnica = Column(Text, nullable=True)
    precio_unitario = Column(Numeric(10, 2), nullable=False)
    stock_disponible = Column(Integer, default=0, nullable=False)
    imagen_url = Column(Text, nullable=True)
    activo = Column(Boolean, default=True, nullable=False, index=True)
    embedding = Column(SafeVector(), nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class Order(Base):
    __tablename__ = "orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    codigo = Column(String(20), unique=True, nullable=False, index=True)
    cliente_nombre = Column(String(150), nullable=False)
    cliente_telefono = Column(String(50), nullable=False)
    cliente_correo = Column(String(150), nullable=False)
    direccion = Column(Text, nullable=True)
    recojo_en_tienda = Column(Boolean, default=False, nullable=False)
    observaciones = Column(Text, nullable=True)
    estado = Column(
        Enum(OrderEstadoEnum), default=OrderEstadoEnum.pendiente, nullable=False
    )
    subtotal = Column(Numeric(10, 2), nullable=False)
    igv = Column(Numeric(10, 2), nullable=False)
    total = Column(Numeric(10, 2), nullable=False)
    acepto_privacidad = Column(Boolean, nullable=False)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    items = relationship(
        "OrderItem", back_populates="order", cascade="all, delete-orphan"
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id = Column(
        UUID(as_uuid=True), ForeignKey("products.id"), nullable=False
    )
    nombre_snapshot = Column(String(150), nullable=False)
    cantidad = Column(Integer, nullable=False)
    precio_unitario_snapshot = Column(Numeric(10, 2), nullable=False)

    order = relationship("Order", back_populates="items")
    product = relationship("Product")


class ChatLog(Base):
    __tablename__ = "chat_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    id_conversacion = Column(UUID(as_uuid=True), nullable=False, index=True)
    timestamp = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    rol = Column(Enum(ChatRolEnum), nullable=False)
    mensaje_texto = Column(Text, nullable=False)
    longitud_mensaje = Column(Integer, nullable=False)
    contiene_palabra_clave_producto = Column(
        Boolean, default=False, nullable=False
    )
    intencion_etiquetada = Column(Integer, nullable=True)


class Claim(Base):
    __tablename__ = "claims"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    codigo_seguimiento = Column(
        String(30), unique=True, nullable=False, index=True
    )
    nombre = Column(String(150), nullable=False)
    documento = Column(String(20), nullable=False)
    telefono = Column(String(50), nullable=False)
    correo = Column(String(150), nullable=False)
    direccion = Column(Text, nullable=False)
    tipo_bien = Column(Enum(ClaimTipoBienEnum), nullable=False)
    monto_reclamado = Column(Numeric(10, 2), nullable=True)
    descripcion_bien = Column(Text, nullable=False)
    tipo = Column(Enum(ClaimTipoEnum), nullable=False)
    detalle = Column(Text, nullable=False)
    pedido_consumidor = Column(Text, nullable=False)
    fecha = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    estado = Column(
        Enum(ClaimEstadoEnum), default=ClaimEstadoEnum.pendiente, nullable=False
    )


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(150), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    rol = Column(Enum(UserRolEnum), default=UserRolEnum.admin, nullable=False)
    activo = Column(Boolean, default=True, nullable=False)
