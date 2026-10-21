import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import check_tracking_rate_limit
from app.db.models import Order, OrderEvent
from app.db.session import get_db
from app.schemas.order import (
    FleteDecisionRequest,
    OrderCreate,
    OrderItemResponse,
    OrderPublicEventResponse,
    OrderPublicTrackingResponse,
    OrderResponse,
)
from app.services.notification_service import (
    notify_flete_decision,
    notify_order_created,
    notify_voucher_uploaded,
)
from app.services.order_service import create_order_service
from app.services.storage_service import ALLOWED_MIME_TYPES, upload_voucher_file

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


def resolve_tracking_order(
    db: Session,
    token: Optional[str] = None,
    codigo: Optional[str] = None,
    telefono: Optional[str] = None,
) -> Order:
    """
    Resuelve de forma segura un pedido para operaciones públicas.
    Admite token secreto o combinación código + teléfono.
    """
    if token and token.strip():
        token_clean = token.strip()
        order = db.query(Order).filter(Order.tracking_token == token_clean).first()
        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No se encontró ningún pedido con los datos proporcionados.",
            )
        return order
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
        return order
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debe proporcionar el token de seguimiento o el código de pedido junto con su teléfono.",
        )


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
        recojo_en_tienda=order.recojo_en_tienda,
        direccion=order.direccion,
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
    order = resolve_tracking_order(db, token=token, codigo=codigo, telefono=telefono)

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
        voucher_referencia=order.voucher_referencia,
        fecha_pago=order.fecha_pago,
    )


@router.post("/tracking/flete-decision")
def submit_flete_decision(
    decision_in: FleteDecisionRequest,
    background_tasks: BackgroundTasks,
    token: Optional[str] = Query(None),
    codigo: Optional[str] = Query(None),
    telefono: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Permite al cliente aceptar o rechazar el flete cotizado para su despacho a obra.
    Actualiza el estado del flete e historiza el evento en el pedido.
    """
    order = resolve_tracking_order(db, token=token, codigo=codigo, telefono=telefono)

    decision = decision_in.decision.lower().strip()
    if decision not in ("aceptar", "rechazar"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La decisión debe ser 'aceptar' o 'rechazar'.",
        )

    if order.estado.value != "flete_cotizado":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"El pedido no se encuentra en estado de cotización de flete (estado actual: {order.estado.value}).",
        )

    if decision == "aceptar":
        order.estado_flete = "aceptado"
        evento_nota = (
            f"Cliente aceptó el costo de flete de S/ {order.costo_flete:.2f}. "
            f"Total final a pagar: S/ {order.total:.2f}."
        )
    else:
        order.estado_flete = "rechazado"
        motivo = f": {decision_in.nota.strip()}" if decision_in.nota else ""
        evento_nota = f"Cliente rechazó la cotización de flete{motivo}."

    event = OrderEvent(
        order_id=order.id,
        estado_anterior=order.estado.value,
        estado_nuevo=order.estado.value,
        autor="cliente",
        nota=evento_nota,
    )
    db.add(event)
    db.commit()
    db.refresh(order)

    background_tasks.add_task(notify_flete_decision, order, decision, decision_in.nota)

    return {
        "ok": True,
        "codigo": order.codigo,
        "estado_flete": order.estado_flete,
        "total": float(order.total),
        "mensaje": "Decisión de flete registrada con éxito.",
    }


@router.post("/tracking/voucher")
async def upload_order_voucher(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    metodo_pago: Optional[str] = Form(None),
    token: Optional[str] = Query(None),
    codigo: Optional[str] = Query(None),
    telefono: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Permite al cliente subir el comprobante de pago (voucher Yape/Plin/transferencia).
    Valida tipo de archivo (JPG, PNG, WEBP, PDF) y tamaño máximo (5MB).
    Almacena en Supabase Storage (o fallback seguro) y notifica al administrador.
    """
    order = resolve_tracking_order(db, token=token, codigo=codigo, telefono=telefono)

    content_type = (file.content_type or "").lower().split(";")[0].strip()
    if content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tipo de archivo no permitido. Solo se aceptan imágenes (JPG, PNG, WEBP) o documentos PDF.",
        )

    file_bytes = await file.read()
    if len(file_bytes) > settings.MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo excede el tamaño máximo permitido de 5 MB.",
        )

    if len(file_bytes) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo proporcionado está vacío.",
        )

    file_url, saved_filename = upload_voucher_file(file_bytes, file.filename or "voucher.png", content_type)

    existing_vouchers = [v.strip() for v in (order.voucher_referencia or "").split(",") if v.strip()]
    if file_url not in existing_vouchers:
        existing_vouchers.append(file_url)
    order.voucher_referencia = ",".join(existing_vouchers)
    order.fecha_pago = datetime.now(timezone.utc)
    if order.estado_flete == "cotizado":
        order.estado_flete = "aceptado"

    metodo_label = ""
    if metodo_pago:
        metodo_map = {
            "yape": "Yape",
            "bcp": "Transferencia BCP",
            "interbank": "Transferencia Interbank",
            "efectivo": "Efectivo",
        }
        metodo_clean = metodo_map.get(metodo_pago.lower(), metodo_pago.strip())
        metodo_label = f" declarado vía {metodo_clean}"
        obs_actual = order.observaciones or ""
        obs_limpia = re.sub(r"\[PAGO DECLARADO:[^\]]*\]", "", obs_actual).strip()
        order.observaciones = f"{obs_limpia} [PAGO DECLARADO: {metodo_clean}]".strip()

    event = OrderEvent(
        order_id=order.id,
        estado_anterior=order.estado.value,
        estado_nuevo=order.estado.value,
        autor="cliente",
        nota=f"Comprobante de pago{metodo_label} cargado ({saved_filename}). En proceso de verificación por caja.",
    )
    db.add(event)
    db.commit()
    db.refresh(order)

    background_tasks.add_task(notify_voucher_uploaded, order, saved_filename)

    return {
        "ok": True,
        "codigo": order.codigo,
        "voucher_url": file_url,
        "fecha_pago": order.fecha_pago.isoformat() if order.fecha_pago else None,
        "mensaje": "Comprobante de pago recibido con éxito. Será validado a la brevedad por el equipo de caja.",
    }


@router.get("/voucher/{filename}")
def serve_voucher_file(filename: str):
    """
    Sirve localmente un archivo de voucher en caso de uso de almacenamiento en disco.
    Protegido contra Directory Traversal.
    """
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nombre de archivo inválido.")

    upload_dir = Path(settings.UPLOAD_DIR)
    file_path = upload_dir / filename
    if not file_path.exists() or not file_path.is_file():
        # Fallback de resolución relativa a la raíz del proyecto backend
        backend_root = Path(__file__).resolve().parent.parent.parent
        alt_path = backend_root / settings.UPLOAD_DIR / filename
        if alt_path.exists() and alt_path.is_file():
            file_path = alt_path
        else:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Archivo de voucher no encontrado.")

    ext = file_path.suffix.lower()
    media_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".pdf": "application/pdf",
    }
    media_type = media_types.get(ext, "application/octet-stream")
    return FileResponse(file_path, media_type=media_type, content_disposition_type="inline")
