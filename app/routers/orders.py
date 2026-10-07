from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.order import OrderCreate, OrderItemResponse, OrderResponse
from app.services.order_service import create_order_service

router = APIRouter(prefix="/api/orders", tags=["Orders"])


@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
def create_order(order_in: OrderCreate, db: Session = Depends(get_db)):
    """Registra un nuevo pedido en estado 'pendiente' y genera el enlace de WhatsApp."""
    order, whatsapp_url = create_order_service(db, order_in)

    items_resp = [
        OrderItemResponse(
            nombre=item.nombre_snapshot,
            cantidad=item.cantidad,
            precio_unitario=item.precio_unitario_snapshot,
        )
        for item in order.items
    ]

    return OrderResponse(
        id=order.id,
        codigo=order.codigo,
        estado=order.estado.value,
        subtotal=order.subtotal,
        igv=order.igv,
        total=order.total,
        items=items_resp,
        whatsapp_url=whatsapp_url,
    )
