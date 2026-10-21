from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import secrets
from typing import Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Order, OrderEstadoEnum, OrderEvent, OrderItem, Product
from app.schemas.order import OrderCreate
from app.services.whatsapp import build_whatsapp_order_url


def round_money(amount: Decimal) -> Decimal:
    """Redondea un monto a 2 decimales usando ROUND_HALF_UP de Decimal."""
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def generate_order_code(db: Session) -> str:
    """Genera un código único secuencial con formato KPK-000123 usando secuencia atómica en PostgreSQL."""
    bind = db.get_bind()
    if bind.dialect.name == "postgresql":
        db.execute(text("CREATE SEQUENCE IF NOT EXISTS order_code_seq;"))
        seq_val = db.execute(text("SELECT nextval('order_code_seq');")).scalar()
        code = f"KPK-{seq_val:06d}"
        while db.query(Order).filter(Order.codigo == code).first():
            seq_val = db.execute(text("SELECT nextval('order_code_seq');")).scalar()
            code = f"KPK-{seq_val:06d}"
        return code

    count = db.query(func.count(Order.id)).scalar() or 0
    seq = count + 1
    code = f"KPK-{seq:06d}"

    while db.query(Order).filter(Order.codigo == code).first():
        seq += 1
        code = f"KPK-{seq:06d}"

    return code


VALID_TRANSITIONS_DESPACHO = {
    OrderEstadoEnum.pendiente: [OrderEstadoEnum.flete_cotizado, OrderEstadoEnum.confirmado, OrderEstadoEnum.cancelado],
    OrderEstadoEnum.flete_cotizado: [OrderEstadoEnum.confirmado, OrderEstadoEnum.cancelado],
    OrderEstadoEnum.confirmado: [OrderEstadoEnum.despachado, OrderEstadoEnum.cancelado],
    OrderEstadoEnum.despachado: [OrderEstadoEnum.entregado, OrderEstadoEnum.cancelado],
    OrderEstadoEnum.entregado: [],
    OrderEstadoEnum.cancelado: [],
}

VALID_TRANSITIONS_RECOJO = {
    OrderEstadoEnum.pendiente: [OrderEstadoEnum.confirmado, OrderEstadoEnum.cancelado],
    OrderEstadoEnum.confirmado: [OrderEstadoEnum.listo_para_recojo, OrderEstadoEnum.cancelado],
    OrderEstadoEnum.listo_para_recojo: [OrderEstadoEnum.entregado, OrderEstadoEnum.cancelado],
    OrderEstadoEnum.entregado: [],
    OrderEstadoEnum.cancelado: [],
}


def transition_order_status(
    db: Session,
    order: Order,
    nuevo_estado_input: str,
    autor: str = "admin",
    nota: Optional[str] = None,
    costo_flete: Optional[Decimal] = None,
) -> Order:
    """
    Máquina de estados centralizada para Comercial Kenpaku S.A.C.
    Valida transiciones legales (Despacho vs Recojo), gestiona el stock e historiza en order_events.
    """
    try:
        nuevo_estado = OrderEstadoEnum(nuevo_estado_input.lower())
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "detail": f"Estado '{nuevo_estado_input}' no es válido. Opciones: {[e.value for e in OrderEstadoEnum]}.",
                "code": "VALIDATION_ERROR",
            },
        )

    estado_anterior = order.estado

    # Si ya se encuentra en ese estado, no hacer nada (idempotente)
    if estado_anterior == nuevo_estado:
        return order

    # Estados terminales no admiten retroceso ni cambios
    if estado_anterior in (OrderEstadoEnum.entregado, OrderEstadoEnum.cancelado):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "detail": f"El pedido {order.codigo} se encuentra en estado terminal '{estado_anterior.value}' y no puede modificarse.",
                "code": "TERMINAL_STATE_ERROR",
            },
        )

    # Validar transición según modalidad
    transitions_map = VALID_TRANSITIONS_RECOJO if order.recojo_en_tienda else VALID_TRANSITIONS_DESPACHO
    allowed_next = transitions_map.get(estado_anterior, [])

    if nuevo_estado not in allowed_next:
        modalidad_str = "Recojo en almacén" if order.recojo_en_tienda else "Despacho a obra"
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "detail": f"Transición no permitida: de '{estado_anterior.value}' a '{nuevo_estado.value}' para '{modalidad_str}'.",
                "code": "INVALID_STATE_TRANSITION",
            },
        )

    # Lógica de Flete (si pasa a flete_cotizado)
    if nuevo_estado == OrderEstadoEnum.flete_cotizado:
        if costo_flete is not None and costo_flete >= Decimal("0.00"):
            order.costo_flete = round_money(costo_flete)
            order.estado_flete = "cotizado"
            if order.items:
                total_productos = sum(
                    round_money(Decimal(str(it.precio_unitario_snapshot)) * Decimal(str(it.cantidad)))
                    for it in order.items
                )
            else:
                total_productos = round_money(order.total)
            order.total = round_money(total_productos + order.costo_flete)
            # SUNAT Opción 1: El flete cotizado incluye IGV (Op. Gravada e IGV recalculados sobre el total final)
            order.subtotal = round_money(order.total / Decimal("1.18"))
            order.igv = round_money(order.total - order.subtotal)
            if not nota:
                nota = f"Flete cotizado por S/ {order.costo_flete:.2f}"

    # Lógica de Stock al confirmar: Descontar inventario disponible
    if nuevo_estado == OrderEstadoEnum.confirmado and estado_anterior not in (
        OrderEstadoEnum.confirmado,
        OrderEstadoEnum.entregado,
        OrderEstadoEnum.despachado,
        OrderEstadoEnum.listo_para_recojo,
    ):
        stock_errors = []
        for item in order.items:
            product = db.query(Product).filter(Product.id == item.product_id).first()
            if not product or product.stock_disponible < item.cantidad:
                stock_errors.append(
                    {
                        "product_id": str(item.product_id),
                        "nombre": item.nombre_snapshot,
                        "stock_disponible": product.stock_disponible if product else 0,
                        "solicitado": item.cantidad,
                    }
                )

        if stock_errors:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "detail": "No se puede confirmar el pedido. Stock insuficiente en el inventario actual.",
                    "code": "STOCK_INSUFFICIENT",
                    "productos_afectados": stock_errors,
                },
            )

        for item in order.items:
            product = db.query(Product).filter(Product.id == item.product_id).first()
            if product:
                product.stock_disponible -= item.cantidad
                if getattr(order, "stock_reservado", False) and getattr(product, "stock_reservado", 0) > 0:
                    product.stock_reservado = max(0, product.stock_reservado - item.cantidad)
        order.stock_reservado = False

    # Lógica de Stock al cancelar: Restituir stock si ya había sido descontado, o liberar reserva
    elif nuevo_estado == OrderEstadoEnum.cancelado:
        if estado_anterior in (
            OrderEstadoEnum.confirmado,
            OrderEstadoEnum.despachado,
            OrderEstadoEnum.listo_para_recojo,
        ):
            for item in order.items:
                product = db.query(Product).filter(Product.id == item.product_id).first()
                if product:
                    product.stock_disponible += item.cantidad
            order.stock_reservado = False
        elif estado_anterior in (OrderEstadoEnum.pendiente, OrderEstadoEnum.flete_cotizado):
            if getattr(order, "stock_reservado", False):
                for item in order.items:
                    product = db.query(Product).filter(Product.id == item.product_id).first()
                    if product and getattr(product, "stock_reservado", 0) > 0:
                        product.stock_reservado = max(0, product.stock_reservado - item.cantidad)
                order.stock_reservado = False

    order.estado = nuevo_estado

    # Registrar evento en la línea de tiempo
    event = OrderEvent(
        order_id=order.id,
        estado_anterior=estado_anterior.value,
        estado_nuevo=nuevo_estado.value,
        nota=nota or f"Estado cambiado a {nuevo_estado.value}",
        autor=autor,
    )
    db.add(event)

    db.commit()
    db.refresh(order)
    return order


def create_order_service(db: Session, order_in: OrderCreate) -> Tuple[Order, str]:
    """Crea un nuevo pedido validando privacidad, stock, asignando tracking_token y registrando evento inicial."""
    if not order_in.acepto_privacidad:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "detail": "Debe aceptar la política de privacidad para procesar el pedido.",
                "code": "VALIDATION_ERROR",
            },
        )

    if not order_in.items:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "detail": "El pedido debe incluir al menos un producto.",
                "code": "VALIDATION_ERROR",
            },
        )

    stock_errors = []
    items_to_create = []
    total_acumulado = Decimal("0.00")

    for item_in in order_in.items:
        product = (
            db.query(Product)
            .filter(Product.id == item_in.product_id, Product.activo == True)
            .first()
        )
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "detail": f"Producto con ID '{item_in.product_id}' no encontrado o inactivo.",
                    "code": "NOT_FOUND",
                },
            )

        if product.stock_disponible < item_in.cantidad:
            stock_errors.append(
                {
                    "product_id": str(product.id),
                    "nombre": product.nombre,
                    "stock_disponible": product.stock_disponible,
                    "solicitado": item_in.cantidad,
                }
            )
        else:
            subtotal_item = product.precio_unitario * item_in.cantidad
            total_acumulado += subtotal_item
            items_to_create.append(
                (product, item_in.cantidad, product.precio_unitario)
            )

    if stock_errors:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "detail": "Stock insuficiente para uno o más productos del pedido.",
                "code": "STOCK_INSUFFICIENT",
                "productos_afectados": stock_errors,
            },
        )

    # Recalcular montos en el servidor (precios en BD incluyen 18% IGV)
    total = round_money(total_acumulado)
    subtotal = round_money(total / Decimal("1.18"))
    igv = round_money(total - subtotal)

    codigo = generate_order_code(db)
    tracking_token = f"kpk_{secrets.token_urlsafe(16)}"
    estado_flete = "sin_flete" if order_in.recojo_en_tienda else "sin_cotizar"
    fecha_limite = datetime.now(timezone.utc) + timedelta(hours=settings.CRON_EXPIRATION_HOURS)

    order = Order(
        codigo=codigo,
        cliente_nombre=order_in.cliente.nombre,
        cliente_telefono=order_in.cliente.telefono,
        cliente_correo=order_in.cliente.correo,
        direccion=order_in.direccion,
        recojo_en_tienda=order_in.recojo_en_tienda,
        observaciones=order_in.observaciones,
        estado=OrderEstadoEnum.pendiente,
        subtotal=subtotal,
        igv=igv,
        total=total,
        costo_flete=Decimal("0.00"),
        estado_flete=estado_flete,
        tracking_token=tracking_token,
        fecha_limite_pago=fecha_limite,
        recordatorio_enviado=False,
        stock_reservado=True,
        acepto_privacidad=order_in.acepto_privacidad,
    )
    db.add(order)
    db.flush()

    for product, cantidad, precio_unitario in items_to_create:
        order_item = OrderItem(
            order_id=order.id,
            product_id=product.id,
            nombre_snapshot=product.nombre,
            cantidad=cantidad,
            precio_unitario_snapshot=precio_unitario,
        )
        db.add(order_item)
        # Reservar stock en el producto (evita sobreventa)
        product.stock_reservado = (getattr(product, "stock_reservado", 0) or 0) + cantidad

    # Evento inicial en order_events
    initial_event = OrderEvent(
        order_id=order.id,
        estado_anterior=None,
        estado_nuevo=OrderEstadoEnum.pendiente.value,
        nota="Pedido registrado por el cliente en la plataforma web",
        autor="cliente",
    )
    db.add(initial_event)

    db.commit()
    db.refresh(order)

    whatsapp_url = build_whatsapp_order_url(
        codigo=order.codigo,
        cliente_nombre=order.cliente_nombre,
        total_str=f"{order.total:.2f}",
    )

    return order, whatsapp_url
