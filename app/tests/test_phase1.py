from decimal import Decimal
import uuid
import pytest
from fastapi import HTTPException

from app.db.models import Order, OrderEstadoEnum, OrderEvent, OrderItem, Product, ProductCategoryEnum, ProductAcabadoEnum
from app.services.order_service import transition_order_status, create_order_service
from app.schemas.order import OrderCreate, ClienteInfo, OrderItemCreate


def seed_product(db_session, stock=20):
    prod = Product(
        id=uuid.uuid4(),
        nombre="Tubo negro 2 pulg",
        categoria=ProductCategoryEnum.tubos,
        acabado=ProductAcabadoEnum.negro,
        precio_unitario=Decimal("100.00"),
        stock_disponible=stock,
        activo=True,
    )
    db_session.add(prod)
    db_session.commit()
    db_session.refresh(prod)
    return prod


def test_create_order_has_tracking_token_and_event(db_session):
    prod = seed_product(db_session)
    order_in = OrderCreate(
        cliente=ClienteInfo(nombre="Juan Perez", telefono="987654321", correo="juan@kenpaku.pe"),
        direccion="Av. Lima 123",
        recojo_en_tienda=False,
        acepto_privacidad=True,
        items=[OrderItemCreate(product_id=prod.id, cantidad=2)],
    )

    order, whatsapp_url = create_order_service(db_session, order_in)
    assert order.tracking_token is not None
    assert order.tracking_token.startswith("kpk_")
    assert order.estado == OrderEstadoEnum.pendiente
    assert order.costo_flete == Decimal("0.00")
    assert order.estado_flete == "sin_cotizar"

    # Verificar que se creó el evento inicial
    events = db_session.query(OrderEvent).filter(OrderEvent.order_id == order.id).all()
    assert len(events) == 1
    assert events[0].estado_nuevo == "pendiente"
    assert events[0].autor == "cliente"


def test_despacho_lifecycle_and_stock_management(db_session):
    prod = seed_product(db_session, stock=10)
    order_in = OrderCreate(
        cliente=ClienteInfo(nombre="Maria Lopez", telefono="912345678", correo="maria@kenpaku.pe"),
        direccion="Calle Los Pinos 456",
        recojo_en_tienda=False,
        acepto_privacidad=True,
        items=[OrderItemCreate(product_id=prod.id, cantidad=3)],
    )
    order, _ = create_order_service(db_session, order_in)

    # 1. Cotizar flete
    order = transition_order_status(db_session, order, "flete_cotizado", autor="admin", costo_flete=Decimal("35.00"))
    assert order.estado == OrderEstadoEnum.flete_cotizado
    assert order.costo_flete == Decimal("35.00")
    assert order.estado_flete == "cotizado"
    # El stock sigue en 10 (no se descuenta en flete cotizado)
    db_session.refresh(prod)
    assert prod.stock_disponible == 10

    # 2. Confirmar pedido (debe descontar stock 10 - 3 = 7)
    order = transition_order_status(db_session, order, "confirmado", autor="admin", nota="Pago Yape validado")
    assert order.estado == OrderEstadoEnum.confirmado
    db_session.refresh(prod)
    assert prod.stock_disponible == 7

    # 3. Despachar a obra
    order = transition_order_status(db_session, order, "despachado", autor="admin", nota="En camión de reparto")
    assert order.estado == OrderEstadoEnum.despachado

    # 4. Entregar en obra
    order = transition_order_status(db_session, order, "entregado", autor="admin", nota="Firmado por maestro de obra")
    assert order.estado == OrderEstadoEnum.entregado

    # 5. Intentar cancelar pedido ya entregado debe fallar con error 422
    with pytest.raises(HTTPException) as exc_info:
        transition_order_status(db_session, order, "cancelado", autor="admin")
    assert exc_info.value.status_code == 422

    # Verificar que se crearon los 4 eventos correspondientes más el inicial
    events = db_session.query(OrderEvent).filter(OrderEvent.order_id == order.id).all()
    assert len(events) == 5


def test_recojo_en_tienda_and_cancellation_restores_stock(db_session):
    prod = seed_product(db_session, stock=10)
    order_in = OrderCreate(
        cliente=ClienteInfo(nombre="Carlos Ramos", telefono="933444555", correo="carlos@kenpaku.pe"),
        recojo_en_tienda=True,
        acepto_privacidad=True,
        items=[OrderItemCreate(product_id=prod.id, cantidad=4)],
    )
    order, _ = create_order_service(db_session, order_in)
    assert order.estado_flete == "sin_flete"

    # Pasar a confirmado: descuenta 4 -> stock queda en 6
    order = transition_order_status(db_session, order, "confirmado", autor="admin")
    db_session.refresh(prod)
    assert prod.stock_disponible == 6

    # Pasar a listo_para_recojo
    order = transition_order_status(db_session, order, "listo_para_recojo", autor="admin")
    assert order.estado == OrderEstadoEnum.listo_para_recojo

    # Cancelar pedido: debe restituir stock a 10
    order = transition_order_status(db_session, order, "cancelado", autor="admin", nota="Cliente desistió de compra")
    assert order.estado == OrderEstadoEnum.cancelado
    db_session.refresh(prod)
    assert prod.stock_disponible == 10
