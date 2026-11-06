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
    Date,
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
        if dialect.name == "postgresql":
            if Vector is None:
                raise RuntimeError("Falta instalar pgvector")
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
    flete_cotizado = "flete_cotizado"
    confirmado = "confirmado"
    despachado = "despachado"
    listo_para_recojo = "listo_para_recojo"
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
    cajero = "cajero"


class Product(Base):
    __tablename__ = "products"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nombre = Column(String(150), nullable=False)
    categoria = Column(Enum(ProductCategoryEnum), nullable=False, index=True)
    tipo = Column(String(100), nullable=True)
    forma = Column(String(50), nullable=True)
    acabado = Column(Enum(ProductAcabadoEnum), nullable=True)
    medida = Column(String(100), nullable=True)
    espesor = Column(String(50), nullable=True)
    descripcion_corta = Column(Text, nullable=True)
    ficha_tecnica = Column(Text, nullable=True)
    precio_unitario = Column(Numeric(10, 2), nullable=False)
    sku = Column(String(100), nullable=True, unique=True, index=True)
    precio_base_usd = Column(Numeric(12, 4), nullable=True)
    margen_pct = Column(Numeric(7, 3), nullable=True)
    stock_disponible = Column(Integer, default=0, nullable=False)
    stock_reservado = Column(Integer, default=0, nullable=False)
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


class ExchangeRate(Base):
    __tablename__ = "exchange_rates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fecha = Column(Date, nullable=False, index=True)
    moneda = Column(String(3), nullable=False, default="USD")
    valor_venta = Column(Numeric(12, 6), nullable=False)
    fuente = Column(String(50), nullable=False)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class PricingSettings(Base):
    __tablename__ = "pricing_settings"

    id = Column(Integer, primary_key=True, default=1)
    margen_global_pct = Column(Numeric(7, 3), nullable=False, default=20)
    costo_incluye_igv = Column(Boolean, nullable=False, default=False)
    redondeo = Column(Integer, nullable=False, default=5)


class CategoryMargin(Base):
    __tablename__ = "margen_por_categoria"

    id = Column(Integer, primary_key=True, autoincrement=True)
    categoria = Column(String(50), nullable=False, unique=True)
    margen_pct = Column(Numeric(7, 3), nullable=False)


class ProductImportHistory(Base):
    __tablename__ = "product_import_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    usuario_email = Column(String(150), nullable=False)
    source_name = Column(String(255), nullable=True)
    nuevos = Column(Integer, nullable=False, default=0)
    actualizados = Column(Integer, nullable=False, default=0)
    errores = Column(Integer, nullable=False, default=0)
    indexing_status = Column(String(20), nullable=False, default="queued")
    indexing_total = Column(Integer, nullable=False, default=0)
    indexing_completed = Column(Integer, nullable=False, default=0)
    indexing_error = Column(Text, nullable=True)


class Quote(Base):
    __tablename__ = "quotes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    codigo = Column(String(18), unique=True, nullable=False, index=True)
    subtotal = Column(Numeric(12, 2), nullable=False)
    igv = Column(Numeric(12, 2), nullable=False)
    total = Column(Numeric(12, 2), nullable=False)
    tipo_cambio_usado = Column(Numeric(12, 6), nullable=True)
    fecha_emision = Column(DateTime(timezone=True), nullable=False)
    valida_hasta = Column(DateTime(timezone=True), nullable=False)
    estado = Column(String(20), nullable=False, default="vigente")
    parent_codigo = Column(String(18), ForeignKey("quotes.codigo"), nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    conversation_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    items = relationship("QuoteItem", back_populates="quote", cascade="all, delete-orphan")


class QuoteItem(Base):
    __tablename__ = "quote_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    quote_id = Column(
        UUID(as_uuid=True), ForeignKey("quotes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    texto_original = Column(Text, nullable=False)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    nombre_snapshot = Column(String(200), nullable=False)
    medida_snapshot = Column(String(100), nullable=True)
    cantidad = Column(Numeric(12, 3), nullable=False)
    unidad = Column(String(40), nullable=True)
    cantidad_asumida = Column(Boolean, nullable=False, default=False)
    precio_unitario_snapshot = Column(Numeric(10, 2), nullable=True)
    subtotal_linea = Column(Numeric(12, 2), nullable=True)
    estado_linea = Column(String(20), nullable=False)
    opciones_json = Column(JSON, nullable=True)
    orden = Column(Integer, nullable=False, default=0)
    equivalencia_nota = Column(String(200), nullable=True)
    espesor_snapshot = Column(String(50), nullable=True)
    acabado_snapshot = Column(String(40), nullable=True)

    quote = relationship("Quote", back_populates="items")
    product = relationship("Product")


class MeasurementEquivalence(Base):
    """Equivalencias comerciales pulgada <-> milímetros (editables desde el admin)."""

    __tablename__ = "measurement_equivalences"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tipo_medida = Column(String(20), nullable=False)
    pulgada = Column(String(20), nullable=False)
    mm_minimo = Column(Numeric(8, 3), nullable=False)
    mm_maximo = Column(Numeric(8, 3), nullable=False)
    categoria = Column(String(50), nullable=True)
    tolerancia_mm = Column(Numeric(5, 2), nullable=False, default=1.5, server_default="1.5")


class Order(Base):
    __tablename__ = "orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    codigo = Column(String(20), unique=True, nullable=False, index=True)
    cliente_nombre = Column(String(150), nullable=False)
    cliente_telefono = Column(String(50), nullable=False)
    cliente_correo = Column(String(150), nullable=True)
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
    costo_flete = Column(Numeric(10, 2), default=0.00, nullable=False)
    estado_flete = Column(String(50), default="sin_cotizar", nullable=False)
    tracking_token = Column(String(64), unique=True, index=True, nullable=True)
    fecha_pago = Column(DateTime(timezone=True), nullable=True)
    voucher_referencia = Column(Text, nullable=True)
    fecha_limite_pago = Column(DateTime(timezone=True), nullable=True)
    recordatorio_enviado = Column(Boolean, default=False, nullable=False)
    stock_reservado = Column(Boolean, default=True, nullable=False)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    items = relationship(
        "OrderItem", back_populates="order", cascade="all, delete-orphan"
    )
    events = relationship(
        "OrderEvent",
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="OrderEvent.created_at.asc()",
    )


class OrderEvent(Base):
    __tablename__ = "order_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    estado_anterior = Column(String(50), nullable=True)
    estado_nuevo = Column(String(50), nullable=False)
    nota = Column(Text, nullable=True)
    autor = Column(String(50), default="sistema", nullable=False)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    order = relationship("Order", back_populates="events")


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
    fuera_de_alcance = Column(Boolean, default=False, nullable=False)


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