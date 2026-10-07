from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import (
    ChatLog,
    ChatRolEnum,
    Claim,
    Order,
    OrderEstadoEnum,
    OrderItem,
    Product,
    User,
)
from app.db.session import get_db
from app.routers.auth import get_current_admin_user
from app.schemas.admin import ChatLogResponse, DashboardMetrics
from app.schemas.claim import ClaimDetailResponse
from app.schemas.order import OrderDetailResponse, OrderItemResponse, OrderStatusUpdate
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


# ==================== GESTIÓN DE PEDIDOS (ADMIN) ====================
@router.get("/orders")
def get_admin_orders(
    estado: Optional[OrderEstadoEnum] = Query(None, description="Filtrar por estado"),
    page: int = Query(1, ge=1),
    page_size: int = Query(12, ge=1, le=100),
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user),
):
    """Lista todos los pedidos recibidos con soporte de paginación y filtro por estado."""
    query = db.query(Order)
    if estado:
        query = query.filter(Order.estado == estado)

    total = query.count()
    items_db = (
        query.order_by(Order.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    result = []
    for order in items_db:
        items_resp = [
            OrderItemResponse(
                nombre=item.nombre_snapshot,
                cantidad=item.cantidad,
                precio_unitario=item.precio_unitario_snapshot,
            )
            for item in order.items
        ]
        result.append(
            OrderDetailResponse(
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
                acepto_privacidad=order.acepto_privacidad,
                created_at=order.created_at,
                items=items_resp,
            )
        )

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

    items_resp = [
        OrderItemResponse(
            nombre=item.nombre_snapshot,
            cantidad=item.cantidad,
            precio_unitario=item.precio_unitario_snapshot,
        )
        for item in order.items
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
        acepto_privacidad=order.acepto_privacidad,
        created_at=order.created_at,
        items=items_resp,
    )


@router.patch("/orders/{order_id}/estado", response_model=OrderDetailResponse)
def update_order_status(
    order_id: UUID,
    status_in: OrderStatusUpdate,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user),
):
    """
    Actualiza el estado de un pedido.
    REGLA CRÍTICA: Al pasar a 'confirmado', valida y descuenta el stock disponible.
    Si se cancela un pedido previamente confirmado, restituye el stock.
    """
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": "Pedido no encontrado.", "code": "NOT_FOUND"},
        )

    nuevo_estado_str = status_in.estado.lower()
    try:
        nuevo_estado = OrderEstadoEnum(nuevo_estado_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "detail": f"Estado '{status_in.estado}' no es válido. Opciones: pendiente, confirmado, entregado, cancelado.",
                "code": "VALIDATION_ERROR",
            },
        )

    estado_anterior = order.estado

    # Transición a 'confirmado': Descontar stock
    if nuevo_estado == OrderEstadoEnum.confirmado and estado_anterior not in (
        OrderEstadoEnum.confirmado,
        OrderEstadoEnum.entregado,
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

        # Aplicar descuento de stock
        for item in order.items:
            product = db.query(Product).filter(Product.id == item.product_id).first()
            if product:
                product.stock_disponible -= item.cantidad

    # Transición a 'cancelado' viniendo de 'confirmado' o 'entregado': Restituir stock
    elif nuevo_estado == OrderEstadoEnum.cancelado and estado_anterior in (
        OrderEstadoEnum.confirmado,
        OrderEstadoEnum.entregado,
    ):
        for item in order.items:
            product = db.query(Product).filter(Product.id == item.product_id).first()
            if product:
                product.stock_disponible += item.cantidad

    order.estado = nuevo_estado
    db.commit()
    db.refresh(order)

    items_resp = [
        OrderItemResponse(
            nombre=item.nombre_snapshot,
            cantidad=item.cantidad,
            precio_unitario=item.precio_unitario_snapshot,
        )
        for item in order.items
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
        acepto_privacidad=order.acepto_privacidad,
        created_at=order.created_at,
        items=items_resp,
    )


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
    """Consulta los registros del chat de asistencia para auditoría."""
    query = db.query(ChatLog)
    total = query.count()
    items = (
        query.order_by(ChatLog.timestamp.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
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
