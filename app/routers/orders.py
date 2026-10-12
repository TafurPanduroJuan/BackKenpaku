import re
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import check_tracking_rate_limit
from app.db.models import Order
from app.db.session import get_db
from app.schemas.order import (
    OrderCreate,
    OrderItemResponse,
    OrderPublicEventResponse,
    OrderPublicTrackingResponse,
    OrderResponse,
)
from app.services.notification_service import notify_order_created
from app.services.order_service import create_order_service

router = APIRouter(prefix="/api/orders", tags=["Orders"])


def normalize_phone_pe(phone: Optional[str]) -> str:
    """Normaliza un número de teléfono a solo dígitos sin código de país (+51 / 51)."""
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 11 and digits.startswith("51"):
        return digits[2:]
    return digits


def mask_client_name(full_name: Optional[str]) -> str:
    """Oculta parcialmente el nombre del cliente para confirmación visual sin violar privacidad."""
    if not full_name:
        return "Cliente"
    parts = full_name.strip().split()
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0]} {parts[1][0]}."


@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
def create_order(
    order_in: OrderCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Registra un nuevo pedido en estado 'pendiente' y genera el enlace de WhatsApp y tracking_token."""
    order, whatsapp_url = create_order_service(db, order_in)
    background_tasks.add_task(notify_order_created, order)

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
        costo_flete=order.costo_flete,
        estado_flete=order.estado_flete,
        tracking_token=order.tracking_token,
        items=items_resp,
        whatsapp_url=whatsapp_url,
    )


@router.get(
    "/tracking",
    response_model=OrderPublicTrackingResponse,
    dependencies=[Depends(check_tracking_rate_limit)],
)
def get_order_public_tracking(
    token: Optional[str] = Query(None, description="Token secreto aleatorio del pedido"),
    codigo: Optional[str] = Query(None, description="Código de pedido (ej. KPK-000001)"),
    telefono: Optional[str] = Query(None, description="Teléfono asociado al pedido"),
    db: Session = Depends(get_db),
):
    """
    Permite el seguimiento público de un pedido sin requerir cuenta o inicio de sesión.
    Consulta mediante token secreto O mediante combinación de código + teléfono.
    Seguridad: No expone datos sensibles (dirección completa, DNI, correo) y devuelve 404 uniforme.
    """
    order = None

    if token and token.strip():
        token_clean = token.strip()
        order = db.query(Order).filter(Order.tracking_token == token_clean).first()
        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No se encontró ningún pedido con los datos proporcionados.",
            )
    elif codigo and telefono:
        codigo_clean = codigo.strip().upper()
        order = db.query(Order).filter(Order.codigo == codigo_clean).first()
        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No se encontró ningún pedido con los datos proporcionados.",
            )

        norm_input = normalize_phone_pe(telefono)
        norm_db = normalize_phone_pe(order.cliente_telefono)
        if not norm_input or norm_input != norm_db:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No se encontró ningún pedido con los datos proporcionados.",
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debe proporcionar el token de seguimiento o el código de pedido junto con su teléfono.",
        )

    items_resp = [
        OrderItemResponse(
            nombre=item.nombre_snapshot,
            cantidad=item.cantidad,
            precio_unitario=item.precio_unitario_snapshot,
        )
        for item in order.items
    ]

    events_resp = [
        OrderPublicEventResponse(
            estado_nuevo=ev.estado_nuevo,
            nota=ev.nota,
            created_at=ev.created_at,
        )
        for ev in (order.events or [])
    ]

    wa_msg = quote(f"¡Hola Comercial Kenpaku! Consulto por el estado de mi pedido *{order.codigo}*.")
    wa_url = f"https://wa.me/{settings.WHATSAPP_NUMBER}?text={wa_msg}"

    return OrderPublicTrackingResponse(
        codigo=order.codigo,
        estado=order.estado.value,
        recojo_en_tienda=order.recojo_en_tienda,
        subtotal=order.subtotal,
        igv=order.igv,
        costo_flete=order.costo_flete,
        estado_flete=order.estado_flete,
        total=order.total,
        tracking_token=order.tracking_token,
        created_at=order.created_at,
        items=items_resp,
        events=events_resp,
        whatsapp_url=wa_url,
        cliente_resumen=mask_client_name(order.cliente_nombre),
    )
