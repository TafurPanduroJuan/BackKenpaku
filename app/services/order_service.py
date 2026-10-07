from decimal import Decimal, ROUND_HALF_UP
from typing import Tuple

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import Order, OrderEstadoEnum, OrderItem, Product
from app.schemas.order import OrderCreate
from app.services.whatsapp import build_whatsapp_order_url


def round_money(amount: Decimal) -> Decimal:
    """Redondea un monto a 2 decimales usando ROUND_HALF_UP de Decimal."""
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def generate_order_code(db: Session) -> str:
    """Genera un código único secuencial con formato KPK-000123."""
    count = db.query(func.count(Order.id)).scalar() or 0
    seq = count + 1
    code = f"KPK-{seq:06d}"

    while db.query(Order).filter(Order.codigo == code).first():
        seq += 1
        code = f"KPK-{seq:06d}"

    return code


def create_order_service(db: Session, order_in: OrderCreate) -> Tuple[Order, str]:
    """Crea un nuevo pedido validando privacidad, stock y recalculando IGV en PEN."""
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

    db.commit()
    db.refresh(order)

    whatsapp_url = build_whatsapp_order_url(
        codigo=order.codigo,
        cliente_nombre=order.cliente_nombre,
        total_str=f"{order.total:.2f}",
    )

    return order, whatsapp_url
