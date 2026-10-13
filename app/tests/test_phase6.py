import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.db.models import Order, OrderEstadoEnum
from app.tests.test_admin import seed_admin_and_product


def make_order(db_session, codigo, **kwargs):
    data = dict(
        id=uuid.uuid4(),
        codigo=codigo,
        cliente_nombre="Cliente Prueba",
        cliente_telefono="987654321",
        cliente_correo="cliente@prueba.com",
        direccion="Av. Test 123",
        recojo_en_tienda=False,
        estado=OrderEstadoEnum.pendiente,
        subtotal=Decimal("84.75"),
        igv=Decimal("15.25"),
        total=Decimal("100.00"),
        acepto_privacidad=True,
        estado_flete="sin_cotizar",
    )
    data.update(kwargs)
    order = Order(**data)
    db_session.add(order)
    db_session.commit()
    return order


def test_action_required_requires_auth(client):
    response = client.get("/api/admin/action-required")
    assert response.status_code == 401


def test_action_required_classifies_orders(client, db_session):
    _, _, headers = seed_admin_and_product(db_session)
    ahora = datetime.now(timezone.utc)

    make_order(db_session, "KPK-900001")
    make_order(
        db_session,
        "KPK-900002",
        estado=OrderEstadoEnum.flete_cotizado,
        estado_flete="cotizado",
        voucher_referencia="vouchers/test.png",
        fecha_pago=ahora,
    )
    make_order(
        db_session,
        "KPK-900003",
        recojo_en_tienda=True,
        fecha_limite_pago=ahora + timedelta(hours=5),
    )
    make_order(db_session, "KPK-900004", estado=OrderEstadoEnum.entregado)

    response = client.get("/api/admin/action-required", headers=headers)
    assert response.status_code == 200
    data = response.json()

    assert [o["codigo"] for o in data["flete_por_cotizar"]] == ["KPK-900001"]
    assert [o["codigo"] for o in data["voucher_por_validar"]] == ["KPK-900002"]
    assert [o["codigo"] for o in data["pedidos_por_vencer"]] == ["KPK-900003"]
    assert data["reclamos_pendientes"] == 0
    assert data["total_acciones"] == 3

def test_admin_orders_search_by_code_and_phone(client, db_session):
    _, _, headers = seed_admin_and_product(db_session)
    make_order(db_session, "KPK-910001", cliente_telefono="987111222")
    make_order(db_session, "KPK-910002", cliente_telefono="955333444")

    por_codigo = client.get("/api/admin/orders?q=910001", headers=headers).json()
    assert [o["codigo"] for o in por_codigo["items"]] == ["KPK-910001"]

    por_telefono = client.get("/api/admin/orders?q=955333", headers=headers).json()
    assert [o["codigo"] for o in por_telefono["items"]] == ["KPK-910002"]

    sin_resultados = client.get("/api/admin/orders?q=000000", headers=headers).json()
    assert sin_resultados["total"] == 0


def test_admin_orders_search_combined_with_estado(client, db_session):
    _, _, headers = seed_admin_and_product(db_session)
    make_order(db_session, "KPK-920001")
    make_order(db_session, "KPK-920002", estado=OrderEstadoEnum.entregado)

    data = client.get(
        "/api/admin/orders?q=KPK-9200&estado=entregado", headers=headers
    ).json()
    assert [o["codigo"] for o in data["items"]] == ["KPK-920002"]