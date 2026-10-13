from datetime import datetime, timedelta, timezone
from decimal import Decimal
import uuid
import pytest
from app.core.config import settings
from app.db.models import (
    Order,
    OrderEstadoEnum,
    OrderEvent,
    OrderItem,
    Product,
    ProductAcabadoEnum,
    ProductCategoryEnum,
    User,
    UserRolEnum,
)
from app.routers.auth import create_access_token
from app.schemas.order import ClienteInfo, OrderCreate, OrderItemCreate
from app.services.order_service import create_order_service, transition_order_status


def seed_product(db_session, stock: int = 20):
    product = Product(
        id=uuid.uuid4(),
        nombre='Viga H 6" x 12 m',
        categoria=ProductCategoryEnum.perfiles,
        acabado=ProductAcabadoEnum.negro,
        medida='6" x 12 m',
        espesor="6 mm",
        descripcion_corta="Viga de acero estructural pesada",
        precio_unitario=Decimal("350.00"),
        stock_disponible=stock,
        stock_reservado=0,
        activo=True,
    )
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)
    return product


def seed_admin_token():
    return create_access_token(subject="admin@kenpaku.pe")


def test_cron_endpoint_unauthorized_without_secret(client):
    """Rechaza con 401 si la petición no incluye cabecera secreta ni token de admin."""
    resp = client.post("/api/cron/process-scheduled-tasks")
    assert resp.status_code == 401
    data = resp.json()
    assert data["code"] == "UNAUTHORIZED_CRON"


def test_cron_endpoint_authorized_with_secret_header(client):
    """Acepta la petición si incluye la cabecera X-Cron-Secret correcta."""
    headers = {"X-Cron-Secret": settings.CRON_SECRET}
    resp = client.post("/api/cron/process-scheduled-tasks", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["keepalive_db"] is True


def test_cron_endpoint_authorized_with_query_param(client):
    """Acepta la petición mediante query parameter ?cron_secret=..."""
    resp = client.post(f"/api/cron/process-scheduled-tasks?cron_secret={settings.CRON_SECRET}")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_cron_endpoint_authorized_with_admin_jwt(client):
    """Permite la ejecución desde el panel de control mediante el token JWT de administrador."""
    token = seed_admin_token()
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.post("/api/cron/process-scheduled-tasks", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_cron_reminder_24h_idempotency(client, db_session):
    """
    Envía recordatorio si transcurrieron 24 horas y el cliente no ha pagado.
    Garantiza IDEMPOTENCIA: No vuelve a enviar recordatorio en ejecuciones posteriores.
    """
    prod = seed_product(db_session, stock=20)
    order_in = OrderCreate(
        cliente=ClienteInfo(
            nombre="Marcos Vega",
            telefono="988776655",
            correo="marcos@gmail.com",
        ),
        direccion="Av. Los Alisos 789, Los Olivos",
        recojo_en_tienda=False,
        acepto_privacidad=True,
        items=[OrderItemCreate(product_id=prod.id, cantidad=2)],
    )
    order, _ = create_order_service(db_session, order_in)

    # Simular que pasaron 26 horas desde la creación
    past_26h = datetime.now(timezone.utc) - timedelta(hours=26)
    order.created_at = past_26h
    db_session.commit()
    db_session.refresh(order)

    assert order.recordatorio_enviado is False

    # 1. Ejecutar cron
    headers = {"X-Cron-Secret": settings.CRON_SECRET}
    resp1 = client.post("/api/cron/process-scheduled-tasks", headers=headers)
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["recordatorios_enviados"] == 1
    assert order.codigo in data1["pedidos_recordatorio"]

    # Verificar que en base de datos quedó marcado como enviado
    db_session.refresh(order)
    assert order.recordatorio_enviado is True

    # Verificar registro en order_events
    reminder_event = (
        db_session.query(OrderEvent)
        .filter(OrderEvent.order_id == order.id, OrderEvent.autor == "sistema")
        .first()
    )
    assert reminder_event is not None
    assert "Recordatorio automático de 24 horas" in reminder_event.nota

    # 2. Ejecutar cron de nuevo (segunda vez): NO debe enviar nuevamente el recordatorio
    resp2 = client.post("/api/cron/process-scheduled-tasks", headers=headers)
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["recordatorios_enviados"] == 0


def test_cron_auto_expiration_48h_and_stock_release(client, db_session):
    """
    Si pasaron más de 48 horas sin confirmación ni comprobante:
    1. Cancela el pedido automáticamente.
    2. Libera el stock reservado de los productos.
    3. Registra el evento en la línea de tiempo con autor='sistema'.
    """
    prod = seed_product(db_session, stock=20)
    order_in = OrderCreate(
        cliente=ClienteInfo(
            nombre="Julio Morales",
            telefono="922334455",
            correo="julio@constructora.pe",
        ),
        direccion="Calle Los Metales 123, Comas",
        recojo_en_tienda=False,
        acepto_privacidad=True,
        items=[OrderItemCreate(product_id=prod.id, cantidad=5)],
    )
    order, _ = create_order_service(db_session, order_in)

    # Verificar que el producto tiene la reserva de 5 unidades
    db_session.refresh(prod)
    assert prod.stock_reservado == 5
    assert prod.stock_disponible == 20  # Stock físico aún no descontado

    # Simular que transcurrieron 50 horas
    past_50h = datetime.now(timezone.utc) - timedelta(hours=50)
    order.created_at = past_50h
    db_session.commit()

    # Ejecutar cron
    headers = {"X-Cron-Secret": settings.CRON_SECRET}
    resp = client.post("/api/cron/process-scheduled-tasks", headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    assert data["pedidos_cancelados_por_vencimiento"] == 1
    assert order.codigo in data["pedidos_cancelados"]
    assert data["stock_liberado_items"] == 5

    # Verificar pedido en BD
    db_session.refresh(order)
    assert order.estado == OrderEstadoEnum.cancelado
    assert order.stock_reservado is False

    # Verificar que la reserva del producto fue liberada
    db_session.refresh(prod)
    assert prod.stock_reservado == 0

    # Verificar evento de sistema en order_events
    cancel_event = (
        db_session.query(OrderEvent)
        .filter(OrderEvent.order_id == order.id, OrderEvent.estado_nuevo == "cancelado")
        .first()
    )
    assert cancel_event is not None
    assert cancel_event.autor == "sistema"
    assert "Cancelación automática" in cancel_event.nota


def test_cron_does_not_cancel_confirmed_orders_or_orders_with_voucher(client, db_session):
    """Los pedidos confirmados o que ya enviaron voucher para validación NO deben ser cancelados."""
    prod = seed_product(db_session, stock=15)
    order_in = OrderCreate(
        cliente=ClienteInfo(
            nombre="Empresa Aceros Norte",
            telefono="911223344",
            correo="logistica@acerosnorte.pe",
        ),
        recojo_en_tienda=True,
        acepto_privacidad=True,
        items=[OrderItemCreate(product_id=prod.id, cantidad=3)],
    )
    order, _ = create_order_service(db_session, order_in)

    # Subió voucher
    order.voucher_referencia = "uploads/vouchers/voucher_123.jpg"
    order.fecha_pago = datetime.now(timezone.utc)
    # Simular que el pedido se creó hace 60 horas
    order.created_at = datetime.now(timezone.utc) - timedelta(hours=60)
    db_session.commit()

    headers = {"X-Cron-Secret": settings.CRON_SECRET}
    resp = client.post("/api/cron/process-scheduled-tasks", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["pedidos_cancelados_por_vencimiento"] == 0

    db_session.refresh(order)
    assert order.estado == OrderEstadoEnum.pendiente


def test_cron_simulation_hours_parameter(client, db_session):
    """Permite el parámetro ?simulate_hours=48 para demostraciones sin alterar fechas de BD."""
    prod = seed_product(db_session, stock=10)
    order_in = OrderCreate(
        cliente=ClienteInfo(
            nombre="Cliente Demo",
            telefono="977889900",
            correo="demo@kenpaku.pe",
        ),
        recojo_en_tienda=True,
        acepto_privacidad=True,
        items=[OrderItemCreate(product_id=prod.id, cantidad=1)],
    )
    order, _ = create_order_service(db_session, order_in)

    headers = {"X-Cron-Secret": settings.CRON_SECRET}
    # Simular avance de 49 horas
    resp = client.post("/api/cron/process-scheduled-tasks?simulate_hours=49", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["pedidos_cancelados_por_vencimiento"] == 1
    assert order.codigo in data["pedidos_cancelados"]


def test_cron_status_public_endpoint(client):
    """El endpoint público /api/cron/status informa los parámetros de configuración."""
    resp = client.get("/api/cron/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "active"
    assert data["reminder_hours"] == 24
    assert data["expiration_hours"] == 48
    assert data["keepalive_support"] is True
