from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.services.notification_service import notify_order_status_changed

from app.db.models import (
    ChatLog,
    ChatRolEnum,
    Claim,
    ClaimEstadoEnum,
    Order,
    OrderEstadoEnum,
    OrderEvent,
    OrderItem,
    Product,
    User,
)
from app.db.session import get_db
from app.routers.auth import get_current_admin_user
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
    OrderStatusUpdate,
    VoucherValidationRequest,
)
from app.schemas.product import (
    ProductCreate,
    ProductPaginatedResponse,
    ProductResponse,
    ProductStockPriceUpdate,
    ProductUpdate,
    compute_stock_estado,
)
from app.services.embeddings import (
    generate_product_embedding_text,
    get_embedding,
)
from app.services.order_service import transition_order_status
from app.services.cron_service import to_utc

router = APIRouter(prefix="/api/admin", tags=["Admin"])


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
    admin_user: User = Depends(get_current_admin_user),
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
    )


# ==================== GESTIÓN DE PEDIDOS (ADMIN) ====================
@router.get("/orders")
def get_admin_orders(
    estado: Optional[OrderEstadoEnum] = Query(None, description="Filtrar por estado"),
    q: Optional[str] = Query(
        None, min_length=2, max_length=50, description="Buscar por código o teléfono"
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(12, ge=1, le=100),
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user),
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
    admin_user: User = Depends(get_current_admin_user),
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
    admin_user: User = Depends(get_current_admin_user),
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
        autor="admin",
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
    admin_user: User = Depends(get_current_admin_user),
):
    """
    Permite al administrador aprobar o rechazar el comprobante de pago subido.
    - Si se aprueba: El pedido pasa a 'confirmado' y se descuenta el stock de almacén.
    - Si se rechaza: Se registra la observación en el historial para subsanación del cliente.
    """
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": "Pedido no encontrado.", "code": "NOT_FOUND"},
        )

    if validation_in.aprobado:
        updated_order = transition_order_status(
            db=db,
            order=order,
            nuevo_estado_input="confirmado",
            autor="admin",
            nota=validation_in.nota or "Pago validado por caja tras revisión de voucher.",
        )
        background_tasks.add_task(
            notify_order_status_changed,
            updated_order,
            "confirmado",
            validation_in.nota or "Pago validado por caja tras revisión de voucher.",
        )
        return build_order_detail_response(updated_order)
    else:
        motivo = validation_in.nota.strip() if validation_in.nota else "Comprobante observado o ilegible"
        event = OrderEvent(
            order_id=order.id,
            estado_anterior=order.estado.value,
            estado_nuevo=order.estado.value,
            autor="admin",
            nota=f"Comprobante observado por caja: {motivo}. Favor cargar nuevo voucher.",
        )
        db.add(event)
        db.commit()
        db.refresh(order)
        return build_order_detail_response(order)


# ==================== GESTIÓN DE PRODUCTOS (ADMIN) ====================
@router.get("/products", response_model=ProductPaginatedResponse)
def get_admin_products(
    page: int = Query(1, ge=1),
    page_size: int = Query(12, ge=1, le=100),
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user),
):
    """Lista todos los productos (activos e inactivos) para la administración."""
    query = db.query(Product)
    total = query.count()
    items_db = (
        query.order_by(Product.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items_resp = [
        ProductResponse(
            id=item.id,
            nombre=item.nombre,
            categoria=item.categoria,
            acabado=item.acabado,
            medida=item.medida,
            espesor=item.espesor,
            descripcion_corta=item.descripcion_corta,
            ficha_tecnica=item.ficha_tecnica,
            precio_unitario=item.precio_unitario,
            stock_disponible=item.stock_disponible,
            stock_estado=compute_stock_estado(item.stock_disponible),
            imagen_url=item.imagen_url,
        )
        for item in items_db
    ]

    return ProductPaginatedResponse(
        items=items_resp, total=total, page=page, page_size=page_size
    )


@router.post(
    "/products", response_model=ProductResponse, status_code=status.HTTP_201_CREATED
)
def create_admin_product(
    product_in: ProductCreate,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user),
):
    """Crea un nuevo producto en el catálogo."""
    prod = Product(**product_in.model_dump())
    db.add(prod)
    db.commit()
    db.refresh(prod)

    return ProductResponse(
        id=prod.id,
        nombre=prod.nombre,
        categoria=prod.categoria,
        acabado=prod.acabado,
        medida=prod.medida,
        espesor=prod.espesor,
        descripcion_corta=prod.descripcion_corta,
        ficha_tecnica=prod.ficha_tecnica,
        precio_unitario=prod.precio_unitario,
        stock_disponible=prod.stock_disponible,
        stock_estado=compute_stock_estado(prod.stock_disponible),
        imagen_url=prod.imagen_url,
    )


@router.put("/products/{product_id}", response_model=ProductResponse)
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

    db.commit()
    db.refresh(prod)

    return ProductResponse(
        id=prod.id,
        nombre=prod.nombre,
        categoria=prod.categoria,
        acabado=prod.acabado,
        medida=prod.medida,
        espesor=prod.espesor,
        descripcion_corta=prod.descripcion_corta,
        ficha_tecnica=prod.ficha_tecnica,
        precio_unitario=prod.precio_unitario,
        stock_disponible=prod.stock_disponible,
        stock_estado=compute_stock_estado(prod.stock_disponible),
        imagen_url=prod.imagen_url,
    )


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


@router.patch("/products/{product_id}/stock-precio", response_model=ProductResponse)
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
        prod.precio_unitario = update_in.precio_unitario

    db.commit()
    db.refresh(prod)

    return ProductResponse(
        id=prod.id,
        nombre=prod.nombre,
        categoria=prod.categoria,
        acabado=prod.acabado,
        medida=prod.medida,
        espesor=prod.espesor,
        descripcion_corta=prod.descripcion_corta,
        ficha_tecnica=prod.ficha_tecnica,
        precio_unitario=prod.precio_unitario,
        stock_disponible=prod.stock_disponible,
        stock_estado=compute_stock_estado(prod.stock_disponible),
        imagen_url=prod.imagen_url,
    )


# ==================== LOGS DE CHAT Y RECLAMOS (ADMIN) ====================
@router.get("/chat-logs")
def get_admin_chat_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user),
):
    """Consulta los registros del chat de asistencia para auditoría.

    La paginación es por CONVERSACIÓN (no por mensaje): cada página trae todos los mensajes
    de las `page_size` conversaciones más recientes, para que ninguna quede cortada.
    """
    last_activity = func.max(ChatLog.timestamp)
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


@router.post("/knowledge/reindex")
def reindex_knowledge_base(
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user),
):
    """Regenera los embeddings vectoriales para todos los productos activos."""
    active_products = db.query(Product).filter(Product.activo == True).all()
    count = 0
    for prod in active_products:
        text = generate_product_embedding_text(
            nombre=prod.nombre,
            categoria=prod.categoria.value,
            acabado=prod.acabado.value if prod.acabado else "",
            medida=prod.medida or "",
            espesor=prod.espesor or "",
            ficha_tecnica=prod.ficha_tecnica or "",
        )
        prod.embedding = get_embedding(text)
        count += 1

    db.commit()
    return {
        "detail": f"Se reindexaron {count} productos activos con éxito.",
        "code": "SUCCESS",
        "total_reindexed": count,
    }