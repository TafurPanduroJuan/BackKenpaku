import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import String, cast, func, or_
from sqlalchemy.orm import Session

from app.services.notification_service import notify_order_status_changed
from app.services.telegram_service import send_telegram_alert

from app.db.models import (
    ChatLog,
    ChatRolEnum,
    CategoryMargin,
    Claim,
    ClaimEstadoEnum,
    Order,
    OrderEstadoEnum,
    OrderEvent,
    Product,
    ProductImportHistory,
    User,
)
from app.db.session import SessionLocal, get_db
from app.routers.auth import get_current_admin_user, get_current_staff_user
from app.schemas.admin import (
    ActionOrderItem,
    ActionRequiredResponse,
    ChatLogResponse,
    DashboardMetrics,
)
from app.schemas.claim import ClaimDetailResponse
from app.schemas.order import (
    OrderDetailResponse,
    OrderEventResponse,
    OrderItemResponse,
    OrderPaymentMethodUpdate,
    OrderStatusUpdate,
    VoucherValidationRequest,
)
from app.schemas.product import (
    AdminProductPaginatedResponse,
    AdminProductResponse,
    ProductCreate,
    ProductStockPriceUpdate,
    ProductUpdate,
    compute_stock_estado,
)
from app.schemas.pricing import PricingSettingsResponse, PricingSettingsUpdate
from app.services import fx_service, pricing_service
from app.services.embeddings import generate_product_embedding
from app.services import product_import_service
from app.services.storage_service import upload_product_image
from app.services.order_service import (
    transition_order_status,
    extract_order_payment_method,
    extract_order_document_info,
)
from app.services.cron_service import to_utc

router = APIRouter(prefix="/api/admin", tags=["Admin"])
logger = logging.getLogger(__name__)


# ==================== DASHBOARD ====================
@router.get("/dashboard", response_model=DashboardMetrics)
def get_dashboard_metrics(
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user),
):
    """Obtiene las métricas clave para el panel de administración."""
    # Pedidos pendientes
    pedidos_pendientes = (
        db.query(func.count(Order.id))
        .filter(Order.estado == OrderEstadoEnum.pendiente)
        .scalar()
        or 0
    )

    # Pedidos hoy (UTC / fecha actual)
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    pedidos_hoy = (
        db.query(func.count(Order.id))
        .filter(Order.created_at >= today_start)
        .scalar()
        or 0
    )

    # Consultas de chat hoy (rol == 'user')
    consultas_chat_hoy = (
        db.query(func.count(ChatLog.id))
        .filter(
            ChatLog.timestamp >= today_start, ChatLog.rol == ChatRolEnum.user
        )
        .scalar()
        or 0
    )

    # Porcentaje de consultas derivadas hoy
    # (por ejemplo, respuestas del asistente con palabra clave o etiqueta de derivación)
    porcentaje_derivadas = 0.0
    if consultas_chat_hoy > 0:
        derivadas_count = (
            db.query(func.count(ChatLog.id))
            .filter(
                ChatLog.timestamp >= today_start,
                ChatLog.rol == ChatRolEnum.assistant,
                ChatLog.mensaje_texto.ilike("%https://wa.me/%"),
            )
            .scalar()
            or 0
        )
        porcentaje_derivadas = round((derivadas_count / consultas_chat_hoy) * 100, 2)

    return DashboardMetrics(
        pedidos_pendientes=pedidos_pendientes,
        pedidos_hoy=pedidos_hoy,
        consultas_chat_hoy=consultas_chat_hoy,
        porcentaje_derivadas=porcentaje_derivadas,
    )

# ==================== ACCIONES REQUERIDAS (FASE 6) ====================
def _to_action_item(order: Order, motivo: str) -> ActionOrderItem:
    return ActionOrderItem(
        id=order.id,
        codigo=order.codigo,
        cliente_nombre=order.cliente_nombre,
        estado=order.estado.value,
        total=order.total,
        motivo=motivo,
        created_at=order.created_at,
        fecha_limite_pago=order.fecha_limite_pago,
    )

def _voucher_observado(order: Order) -> bool:
    """True si caja observó el voucher actual y el cliente aún no subió uno nuevo."""
    fecha_pago = to_utc(order.fecha_pago)
    for ev in order.events or []:
        if not ev.nota or not ev.nota.startswith("Comprobante observado por caja"):
            continue
        if fecha_pago is None or to_utc(ev.created_at) >= fecha_pago:
            return True
    return False

@router.get("/action-required", response_model=ActionRequiredResponse)
def get_action_required(
    horas_aviso: int = Query(12, ge=1, le=48),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_staff_user),
):
    """Pedidos y reclamos que requieren acción del administrador hoy."""
    abiertos = [OrderEstadoEnum.pendiente, OrderEstadoEnum.flete_cotizado]
    pedidos_abiertos = (
        db.query(Order)
        .filter(Order.estado.in_(abiertos))
        .order_by(Order.created_at.asc())
        .all()
    )

    limite = datetime.now(timezone.utc) + timedelta(hours=horas_aviso)
    flete_por_cotizar: List[ActionOrderItem] = []
    voucher_por_validar: List[ActionOrderItem] = []
    pedidos_por_vencer: List[ActionOrderItem] = []

    for o in pedidos_abiertos:
        if o.voucher_referencia:
            if not _voucher_observado(o):
                voucher_por_validar.append(
                    _to_action_item(o, "Voucher subido: validar el pago")
                )
            continue
        if (
            o.estado == OrderEstadoEnum.pendiente
            and not o.recojo_en_tienda
            and o.estado_flete == "sin_cotizar"
        ):
            flete_por_cotizar.append(_to_action_item(o, "Falta cotizar el flete"))
        venc = to_utc(o.fecha_limite_pago)
        if venc is not None and venc <= limite:
            pedidos_por_vencer.append(
                _to_action_item(o, f"Vence en menos de {horas_aviso} horas")
            )

    reclamos_pendientes = (
        db.query(func.count(Claim.id))
        .filter(Claim.estado == ClaimEstadoEnum.pendiente)
        .scalar()
        or 0
    )

    return ActionRequiredResponse(
        flete_por_cotizar=flete_por_cotizar,
        voucher_por_validar=voucher_por_validar,
        pedidos_por_vencer=pedidos_por_vencer,
        reclamos_pendientes=reclamos_pendientes,
        total_acciones=(
            len(flete_por_cotizar)
            + len(voucher_por_validar)
            + len(pedidos_por_vencer)
            + reclamos_pendientes
        ),
    )

def build_order_detail_response(order: Order) -> OrderDetailResponse:
    items_resp = [
        OrderItemResponse(
            nombre=item.nombre_snapshot,
            cantidad=item.cantidad,
            precio_unitario=item.precio_unitario_snapshot,
        )
        for item in order.items
    ]
    events_resp = [
        OrderEventResponse(
            id=ev.id,
            estado_anterior=ev.estado_anterior,
            estado_nuevo=ev.estado_nuevo,
            nota=ev.nota,
            autor=ev.autor,
            created_at=ev.created_at,
        )
        for ev in (order.events or [])
    ]
    metodo_clean = extract_order_payment_method(order)
    comprobante_tipo, doc_num = extract_order_document_info(order)

    return OrderDetailResponse(
        id=order.id,
        codigo=order.codigo,
        cliente_nombre=order.cliente_nombre,
        cliente_telefono=order.cliente_telefono,
        cliente_correo=order.cliente_correo,
        direccion=order.direccion,
        recojo_en_tienda=order.recojo_en_tienda,
        observaciones=order.observaciones,
        estado=order.estado.value,
        subtotal=order.subtotal,
        igv=order.igv,
        total=order.total,
        costo_flete=order.costo_flete,
        estado_flete=order.estado_flete,
        tracking_token=order.tracking_token,
        fecha_pago=order.fecha_pago,
        voucher_referencia=order.voucher_referencia,
        acepto_privacidad=order.acepto_privacidad,
        created_at=order.created_at,
        items=items_resp,
        events=events_resp,
        metodo_pago=metodo_clean,
        comprobante_tipo=comprobante_tipo,
        doc_numero=doc_num,
    )


# ==================== GESTIÓN DE PEDIDOS (ADMIN) ====================
@router.get("/orders")
def get_admin_orders(
    estado: Optional[OrderEstadoEnum] = Query(None, description="Filtrar por estado"),
    q: Optional[str] = Query(
        None, min_length=2, max_length=50, description="Buscar por código o teléfono"
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(12, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_staff_user),
):
    """Lista pedidos con paginación, filtro por estado y búsqueda por código o teléfono."""
    query = db.query(Order)
    if estado:
        query = query.filter(Order.estado == estado)

    if q:
        termino = q.strip()
        solo_digitos = "".join(ch for ch in termino if ch.isdigit())
        condiciones = [Order.codigo.ilike(f"%{termino}%")]
        if solo_digitos:
            condiciones.append(Order.cliente_telefono.ilike(f"%{solo_digitos}%"))
        query = query.filter(or_(*condiciones))

    total = query.count()
    items_db = (
        query.order_by(Order.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    result = [build_order_detail_response(o) for o in items_db]
    return {"items": result, "total": total, "page": page, "page_size": page_size}

@router.get("/orders/{order_id}", response_model=OrderDetailResponse)
def get_admin_order_by_id(
    order_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_staff_user),
):
    """Obtiene el detalle completo de un pedido específico."""
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": "Pedido no encontrado.", "code": "NOT_FOUND"},
        )

    return build_order_detail_response(order)


@router.patch("/orders/{order_id}/estado", response_model=OrderDetailResponse)
def update_order_status(
    order_id: UUID,
    status_in: OrderStatusUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_staff_user),
):
    """
    Actualiza el estado de un pedido usando la máquina de estados centralizada.
    Valida transiciones legales (Despacho vs Recojo), gestiona stock y registra en order_events.
    Dispara notificaciones por correo y Telegram en segundo plano.
    """
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": "Pedido no encontrado.", "code": "NOT_FOUND"},
        )

    updated_order = transition_order_status(
        db=db,
        order=order,
        nuevo_estado_input=status_in.estado,
        autor=current_user.rol.value if current_user and current_user.rol else "admin",
        nota=status_in.nota,
        costo_flete=status_in.costo_flete,
    )

    background_tasks.add_task(
        notify_order_status_changed,
        updated_order,
        status_in.estado,
        status_in.nota,
    )

    return build_order_detail_response(updated_order)


@router.put("/orders/{order_id}/validate-voucher", response_model=OrderDetailResponse)
def validate_order_voucher(
    order_id: UUID,
    validation_in: VoucherValidationRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_staff_user),
):
    """
    Permite al administrador o cajero aprobar o rechazar el comprobante de pago subido.
    - Si se aprueba: El pedido pasa a 'confirmado' y se descuenta el stock de almacén.
    - Puede confirmar o corregir el medio de pago real verificado (Yape, BCP, Interbank, Efectivo).
    - Si se rechaza: Se registra la observación en el historial para subsanación del cliente.
    """
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": "Pedido no encontrado.", "code": "NOT_FOUND"},
        )

    metodo_clean = None
    if validation_in.metodo_pago:
        metodo_map = {
            "yape": "Yape",
            "bcp": "Transferencia BCP",
            "interbank": "Transferencia Interbank",
            "efectivo": "Efectivo",
        }
        metodo_clean = metodo_map.get(validation_in.metodo_pago.lower(), validation_in.metodo_pago.strip())
        obs_actual = order.observaciones or ""
        obs_limpia = re.sub(r"\[PAGO[^\]]*\]", "", obs_actual).strip()
        order.observaciones = f"{obs_limpia} [PAGO: {metodo_clean}]".strip()

    autor_str = current_user.rol.value if current_user and current_user.rol else "cajero"

    if validation_in.aprobado:
        nota_default = (
            f"Pago validado por caja tras revisión de voucher vía {metodo_clean}."
            if metodo_clean
            else "Pago validado por caja tras revisión de voucher."
        )
        nota_final = validation_in.nota or nota_default
        updated_order = transition_order_status(
            db=db,
            order=order,
            nuevo_estado_input="confirmado",
            autor=autor_str,
            nota=nota_final,
        )
        background_tasks.add_task(
            notify_order_status_changed,
            updated_order,
            "confirmado",
            nota_final,
        )
        return build_order_detail_response(updated_order)
    else:
        motivo = validation_in.nota.strip() if validation_in.nota else "Comprobante observado o ilegible"
        event = OrderEvent(
            order_id=order.id,
            estado_anterior=order.estado.value,
            estado_nuevo=order.estado.value,
            autor=autor_str,
            nota=f"Comprobante observado por caja: {motivo}. Favor cargar nuevo voucher.",
        )
        db.add(event)
        db.commit()
        db.refresh(order)
        background_tasks.add_task(
            notify_order_status_changed,
            order,
            order.estado.value,
            f"Comprobante observado por caja: {motivo}. Favor acceder a su enlace de seguimiento y cargar un nuevo comprobante.",
        )
        return build_order_detail_response(order)


@router.put("/orders/{order_id}/metodo-pago", response_model=OrderDetailResponse)
def update_order_payment_method(
    order_id: UUID,
    payment_in: OrderPaymentMethodUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_staff_user),
):
    """
    Permite al cajero o administrador confirmar o corregir el medio de pago de una venta.
    """
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": "Pedido no encontrado.", "code": "NOT_FOUND"},
        )

    metodo_map = {
        "yape": "Yape",
        "bcp": "Transferencia BCP",
        "interbank": "Transferencia Interbank",
        "efectivo": "Efectivo",
    }
    metodo_clean = metodo_map.get(payment_in.metodo_pago.lower(), payment_in.metodo_pago.strip())
    obs_actual = order.observaciones or ""
    obs_limpia = re.sub(r"\[PAGO[^\]]*\]", "", obs_actual).strip()
    order.observaciones = f"{obs_limpia} [PAGO: {metodo_clean}]".strip()

    autor_str = current_user.rol.value if current_user and current_user.rol else "cajero"
    event_nota = payment_in.nota or f"Medio de pago verificado/ajustado por {autor_str} a: {metodo_clean}."
    event = OrderEvent(
        order_id=order.id,
        estado_anterior=order.estado.value,
        estado_nuevo=order.estado.value,
        autor=autor_str,
        nota=event_nota,
    )
    db.add(event)
    db.commit()
    db.refresh(order)
    return build_order_detail_response(order)


# ==================== GESTIÓN DE PRODUCTOS (ADMIN) ====================
@router.get("/products", response_model=AdminProductPaginatedResponse)
def get_admin_products(
    q: Optional[str] = Query(None, max_length=100),
    sin_imagen: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(12, ge=1, le=100),
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user),
):
    """Lista todos los productos (activos e inactivos) para la administración."""
    query = db.query(Product)
    if q and q.strip():
        term = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Product.nombre.ilike(term),
                cast(Product.categoria, String).ilike(term),
                Product.medida.ilike(term),
                Product.sku.ilike(term),
            )
        )
    if sin_imagen is True:
        query = query.filter(or_(Product.imagen_url.is_(None), Product.imagen_url == ""))
    elif sin_imagen is False:
        query = query.filter(Product.imagen_url.is_not(None), Product.imagen_url != "")
    total = query.count()
    items_db = (
        query.order_by(Product.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items_resp = [_admin_product_response(db, item) for item in items_db]

    return AdminProductPaginatedResponse(
        items=items_resp, total=total, page=page, page_size=page_size
    )


def _admin_product_response(db: Session, product: Product) -> AdminProductResponse:
    rate, margin, rate_date, rate_source = pricing_service.get_product_pricing_details(db, product)
    return AdminProductResponse(
        id=product.id,
        nombre=product.nombre,
        categoria=product.categoria,
        acabado=product.acabado,
        medida=product.medida,
        espesor=product.espesor,
        descripcion_corta=product.descripcion_corta,
        ficha_tecnica=product.ficha_tecnica,
        precio_unitario=product.precio_unitario,
        stock_disponible=product.stock_disponible,
        stock_estado=compute_stock_estado(product.stock_disponible),
        imagen_url=product.imagen_url,
        sku=product.sku,
        precio_base_usd=product.precio_base_usd,
        margen_pct=product.margen_pct,
        tipo_cambio_usado=rate,
        margen_aplicado_pct=margin,
        fecha_tipo_cambio=rate_date,
        fuente_tipo_cambio=rate_source,
    )


@router.post(
    "/products", response_model=AdminProductResponse, status_code=status.HTTP_201_CREATED
)
def create_admin_product(
    product_in: ProductCreate,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user),
):
    """Crea un nuevo producto en el catálogo."""
    prod = Product(**product_in.model_dump())
    try:
        pricing_service.recalculate_product(db, prod)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.add(prod)
    db.commit()
    db.refresh(prod)

    return _admin_product_response(db, prod)


@router.put("/products/{product_id}", response_model=AdminProductResponse)
def update_admin_product(
    product_id: UUID,
    product_in: ProductUpdate,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user),
):
    """Actualiza la información técnica y comercial de un producto."""
    prod = db.query(Product).filter(Product.id == product_id).first()
    if not prod:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": "Producto no encontrado.", "code": "NOT_FOUND"},
        )

    update_data = product_in.model_dump(exclude_unset=True)
    for field, val in update_data.items():
        setattr(prod, field, val)

    try:
        pricing_service.recalculate_product(db, prod)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    db.commit()
    db.refresh(prod)

    return _admin_product_response(db, prod)


@router.delete("/products/{product_id}")
def delete_admin_product(
    product_id: UUID,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user),
):
    """Realiza la baja lógica de un producto (`activo = False`)."""
    prod = db.query(Product).filter(Product.id == product_id).first()
    if not prod:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": "Producto no encontrado.", "code": "NOT_FOUND"},
        )

    prod.activo = False
    db.commit()
    return {"detail": "Producto desactivado correctamente", "code": "SUCCESS"}

@router.post("/products/{product_id}/image")
async def upload_admin_product_image(
    product_id: UUID,
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user),
):
    product = db.query(Product).filter(Product.id == product_id).first()
    if product is None:
        raise HTTPException(status_code=404, detail="Producto no encontrado.")
    image_bytes = await image.read(5 * 1024 * 1024 + 1)
    if len(image_bytes) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="La imagen supera el limite de 5 MB.")
    try:
        image_url = upload_product_image(image_bytes, image.content_type or "")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Error subiendo imagen de producto %s", product_id)
        raise HTTPException(status_code=502, detail="No se pudo subir la imagen.") from exc

    product.imagen_url = image_url
    db.commit()
    return {"id": product.id, "imagen_url": image_url}


@router.patch("/products/{product_id}/stock-precio", response_model=AdminProductResponse)
def update_product_stock_price(
    product_id: UUID,
    update_in: ProductStockPriceUpdate,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user),
):
    """Actualización rápida de stock y/o precio unitario."""
    prod = db.query(Product).filter(Product.id == product_id).first()
    if not prod:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": "Producto no encontrado.", "code": "NOT_FOUND"},
        )

    if update_in.stock_disponible is not None:
        prod.stock_disponible = update_in.stock_disponible

    if update_in.precio_unitario is not None:
        if prod.precio_base_usd is not None:
            raise HTTPException(
                status_code=409,
                detail="El precio de este producto se calcula desde su costo USD; edita el costo o el margen.",
            )
        prod.precio_unitario = update_in.precio_unitario

    db.commit()
    db.refresh(prod)

    return _admin_product_response(db, prod)


def _pricing_settings_response(db: Session) -> PricingSettingsResponse:
    settings_row = pricing_service.get_pricing_settings(db)
    latest = pricing_service.get_latest_exchange_rate(db)
    margins = [
        {"categoria": row.categoria, "margen_pct": row.margen_pct}
        for row in db.query(CategoryMargin).order_by(CategoryMargin.categoria.asc()).all()
    ]
    db.commit()
    return PricingSettingsResponse(
        margen_global_pct=settings_row.margen_global_pct,
        costo_incluye_igv=settings_row.costo_incluye_igv,
        redondeo=settings_row.redondeo,
        margenes_por_categoria=margins,
        tipo_cambio_actual=latest.valor_venta if latest else None,
        fecha_tipo_cambio=latest.fecha if latest else None,
        fuente_tipo_cambio=latest.fuente if latest else None,
    )


@router.get("/pricing/settings", response_model=PricingSettingsResponse)
def get_admin_pricing_settings(
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user),
):
    return _pricing_settings_response(db)


@router.put("/pricing/settings", response_model=PricingSettingsResponse)
def update_admin_pricing_settings(
    settings_in: PricingSettingsUpdate,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user),
):
    category_names = [margin.categoria.value for margin in settings_in.margenes_por_categoria]
    if len(category_names) != len(set(category_names)):
        raise HTTPException(status_code=422, detail="No repitas una categoría en los márgenes.")

    settings_row = pricing_service.get_pricing_settings(db)
    settings_row.margen_global_pct = settings_in.margen_global_pct
    settings_row.costo_incluye_igv = settings_in.costo_incluye_igv
    settings_row.redondeo = settings_in.redondeo

    db.query(CategoryMargin).delete(synchronize_session=False)
    for margin in settings_in.margenes_por_categoria:
        db.add(
            CategoryMargin(
                categoria=margin.categoria.value,
                margen_pct=margin.margen_pct,
            )
        )

    try:
        if settings_in.tipo_cambio_manual is not None:
            fx_service.set_manual_exchange_rate(db, settings_in.tipo_cambio_manual)
        else:
            pricing_service.recalculate_usd_products(db)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return _pricing_settings_response(db)


# ==================== LOGS DE CHAT Y RECLAMOS (ADMIN) ====================
@router.get("/chat-logs")
def get_admin_chat_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    fuera_de_alcance: Optional[bool] = Query(None, description="Filtrar por mensajes fuera de alcance"),
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user),
):
    """Consulta los registros del chat de asistencia para auditoría.

    La paginación es por CONVERSACIÓN (no por mensaje): cada página trae todos los mensajes
    de las `page_size` conversaciones más recientes, para que ninguna quede cortada.
    Opcionalmente filtra conversaciones que contengan mensajes fuera de alcance.
    """
    last_activity = func.max(ChatLog.timestamp)

    # Si se filtra por fuera_de_alcance, primero encontrar las conversaciones que lo contienen
    if fuera_de_alcance is not None:
        # Subquery: conversaciones que tienen al menos un mensaje fuera_de_alcance
        from sqlalchemy import distinct
        conv_with_offtopic = (
            db.query(distinct(ChatLog.id_conversacion))
            .filter(ChatLog.fuera_de_alcance == True)
            .subquery()
        )

        if fuera_de_alcance:
            # Solo conversaciones CON mensajes fuera de alcance
            base_query = db.query(ChatLog.id_conversacion).filter(
                ChatLog.id_conversacion.in_(conv_with_offtopic)
            )
        else:
            # Solo conversaciones SIN mensajes fuera de alcance
            base_query = db.query(ChatLog.id_conversacion).filter(
                ~ChatLog.id_conversacion.in_(conv_with_offtopic)
            )

        total = base_query.group_by(ChatLog.id_conversacion).count()
        conv_rows = (
            base_query
            .group_by(ChatLog.id_conversacion)
            .order_by(last_activity.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
    else:
        total = db.query(func.count(func.distinct(ChatLog.id_conversacion))).scalar() or 0
        conv_rows = (
            db.query(ChatLog.id_conversacion)
            .group_by(ChatLog.id_conversacion)
            .order_by(last_activity.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

    conv_ids = [row[0] for row in conv_rows]

    items = []
    if conv_ids:
        items = (
            db.query(ChatLog)
            .filter(ChatLog.id_conversacion.in_(conv_ids))
            .order_by(ChatLog.timestamp.desc())
            .all()
        )
    items_resp = [ChatLogResponse.model_validate(item) for item in items]
    return {"items": items_resp, "total": total, "page": page, "page_size": page_size}


@router.get("/claims")
def get_admin_claims(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user),
):
    """Consulta las reclamaciones del Libro de Reclamaciones."""
    query = db.query(Claim)
    total = query.count()
    items = (
        query.order_by(Claim.fecha.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items_resp = [ClaimDetailResponse.model_validate(item) for item in items]
    return {"items": items_resp, "total": total, "page": page, "page_size": page_size}


def _parse_import_form_json(value: Optional[str], expect_dict: bool = True):
    if not value:
        return {} if expect_dict else []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="JSON de importacion invalido.") from exc
    if expect_dict and not isinstance(parsed, dict):
        raise HTTPException(status_code=422, detail="El valor debe ser un objeto JSON.")
    if not expect_dict and not isinstance(parsed, list):
        raise HTTPException(status_code=422, detail="El valor debe ser una lista JSON.")
    return parsed


async def _read_import_source(file: Optional[UploadFile], pasted_text: Optional[str]):
    if file is not None:
        data = await file.read(product_import_service.MAX_IMPORT_BYTES + 1)
        filename = file.filename or "proveedor.csv"
        pasted = None
    elif pasted_text and pasted_text.strip():
        data = b""
        filename = "Tabla pegada"
        pasted = pasted_text
    else:
        raise HTTPException(status_code=422, detail="Sube un archivo o pega la tabla del proveedor.")
    if len(data) > product_import_service.MAX_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail="El archivo supera el limite de 5 MB.")
    return data, filename, pasted


@router.post("/products/import/preview")
async def preview_product_import(
    file: Optional[UploadFile] = File(None),
    pasted_text: Optional[str] = Form(None),
    mapping: Optional[str] = Form(None),
    category_overrides: Optional[str] = Form(None),
    update_mode: str = Form("todo"),
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user),
):
    data, filename, pasted = await _read_import_source(file, pasted_text)
    selected_mapping = _parse_import_form_json(mapping) if mapping else None
    overrides = _parse_import_form_json(category_overrides)
    try:
        return product_import_service.build_preview(
            db,
            data=data,
            filename=filename,
            pasted_text=pasted,
            mapping=selected_mapping,
            category_overrides=overrides,
            update_mode=update_mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Error al analizar archivo de importacion")
        raise HTTPException(
            status_code=422,
            detail="No se pudo leer la lista. Verifica el archivo y sus encabezados.",
        ) from exc


@router.post("/products/import/commit")
async def commit_product_import(
    background_tasks: BackgroundTasks,
    file: Optional[UploadFile] = File(None),
    pasted_text: Optional[str] = Form(None),
    mapping: Optional[str] = Form(None),
    category_overrides: Optional[str] = Form(None),
    excluded_rows: Optional[str] = Form("[]"),
    update_mode: str = Form("todo"),
    new_products_active: bool = Form(False),
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user),
):
    data, filename, pasted = await _read_import_source(file, pasted_text)
    selected_mapping = _parse_import_form_json(mapping) if mapping else None
    overrides = _parse_import_form_json(category_overrides)
    excluded = _parse_import_form_json(excluded_rows, expect_dict=False)
    try:
        history, product_ids = product_import_service.commit_import(
            db,
            data=data,
            filename=filename,
            pasted_text=pasted,
            mapping=selected_mapping,
            category_overrides=overrides,
            excluded_rows=excluded,
            update_mode=update_mode,
            new_products_active=new_products_active,
            user_email=admin_user.email,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        logger.exception("Error al confirmar importacion de productos")
        raise HTTPException(
            status_code=409,
            detail="No se pudo guardar la importacion; ningun cambio fue confirmado.",
        ) from exc

    if product_ids:
        background_tasks.add_task(
            product_import_service.index_import_embeddings,
            history.id,
            product_ids,
            SessionLocal,
        )
    return {
        "import_id": history.id,
        "nuevos": history.nuevos,
        "actualizados": history.actualizados,
        "errores": history.errores,
        "indexing_status": history.indexing_status,
        "indexing_total": history.indexing_total,
    }


@router.get("/products/import/history")
def get_product_import_history(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user),
):
    rows = (
        db.query(ProductImportHistory)
        .order_by(ProductImportHistory.created_at.desc(), ProductImportHistory.id.desc())
        .limit(limit)
        .all()
    )
    return {
        "items": [
            {
                "id": row.id,
                "created_at": row.created_at,
                "usuario_email": row.usuario_email,
                "source_name": row.source_name,
                "nuevos": row.nuevos,
                "actualizados": row.actualizados,
                "errores": row.errores,
                "indexing_status": row.indexing_status,
                "indexing_total": row.indexing_total,
                "indexing_completed": row.indexing_completed,
                "indexing_error": row.indexing_error,
            }
            for row in rows
        ]
    }


@router.post("/knowledge/reindex")
def reindex_knowledge_base(
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user),
):
    """Regenera los embeddings vectoriales para todos los productos activos."""
    active_products = db.query(Product).filter(Product.activo == True).all()
    count = 0
    for prod in active_products:
        prod.embedding = generate_product_embedding(prod)
        count += 1

    db.commit()
    return {
        "detail": f"Se reindexaron {count} productos activos con éxito.",
        "code": "SUCCESS",
        "total_reindexed": count,
    }


@router.post("/test-telegram")
def test_telegram_connection(
    admin_user: User = Depends(get_current_staff_user),
):
    """
    Envía un mensaje de prueba al bot de Telegram configurado en .env.
    Permite validar de forma instantánea si el Bot Token y Chat ID están operativos.
    """
    test_msg = (
        "🤖 <b>Comercial Kenpaku S.A.C. — Notificaciones</b>\n\n"
        "✅ <b>Conexión con el Bot de Telegram exitosa.</b>\n"
        "A partir de este momento, recibirás aquí todas las alertas instantáneas "
        "de nuevas ventas virtuales, cotizaciones de flete y comprobantes de pago."
    )
    result = send_telegram_alert(test_msg)
    return {
        "detail": "Prueba de Telegram ejecutada.",
        "telegram_result": result,
    }