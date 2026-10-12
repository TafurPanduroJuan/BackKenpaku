import io
from decimal import Decimal
from fastapi.testclient import TestClient

from app.db.models import Order, OrderEstadoEnum, OrderItem, Product, ProductCategoryEnum, User, UserRolEnum
from app.core.security import get_password_hash, create_access_token
from app.services.order_service import transition_order_status


def seed_test_data(db_session):
    product = Product(
        nombre="Plancha LAC 2.0 mm Test",
        categoria=ProductCategoryEnum.planchas,
        precio_unitario=Decimal("150.00"),
        stock_disponible=20,
        activo=True,
    )
    admin = User(
        email="admin_phase4@kenpaku.pe",
        password_hash=get_password_hash("AdminKenpaku2026!"),
        rol=UserRolEnum.admin,
        activo=True,
    )
    db_session.add_all([product, admin])
    db_session.commit()
    db_session.refresh(product)
    db_session.refresh(admin)

    order = Order(
        codigo="KPK-PHASE4-01",
        cliente_nombre="Carlos Maza",
        cliente_telefono="987654321",
        cliente_correo="carlos@example.com",
        direccion="Av. Túpac Amaru 1234, Carabayllo",
        recojo_en_tienda=False,
        subtotal=Decimal("300.00"),
        igv=Decimal("54.00"),
        total=Decimal("354.00"),
        acepto_privacidad=True,
        tracking_token="phase4_test_token_12345",
        estado=OrderEstadoEnum.pendiente,
        costo_flete=Decimal("0.00"),
        estado_flete="sin_cotizar",
    )
    db_session.add(order)
    db_session.commit()
    db_session.refresh(order)

    item = OrderItem(
        order_id=order.id,
        product_id=product.id,
        cantidad=2,
        precio_unitario_snapshot=Decimal("150.00"),
        nombre_snapshot=product.nombre,
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(order)

    token = create_access_token(subject=admin.email)
    admin_headers = {"Authorization": f"Bearer {token}"}

    return admin, product, order, admin_headers


def test_flete_decision_accept(client: TestClient, db_session):
    _, _, order, _ = seed_test_data(db_session)
    # Admin cotiza flete de 45.00
    order = transition_order_status(db_session, order, "flete_cotizado", autor="admin", costo_flete=Decimal("45.00"))
    assert order.estado == OrderEstadoEnum.flete_cotizado
    assert order.costo_flete == Decimal("45.00")

    # Cliente acepta flete usando su token público
    resp = client.post(
        f"/api/orders/tracking/flete-decision?token={order.tracking_token}",
        json={"decision": "aceptar"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["estado_flete"] == "aceptado"

    db_session.refresh(order)
    assert order.estado_flete == "aceptado"
    # Verificar que el evento quedó registrado
    events = order.events
    assert any("aceptó el costo de flete" in ev.nota for ev in events)


def test_flete_decision_reject(client: TestClient, db_session):
    _, _, order, _ = seed_test_data(db_session)
    order = transition_order_status(db_session, order, "flete_cotizado", autor="admin", costo_flete=Decimal("60.00"))

    # Cliente rechaza flete con motivo
    resp = client.post(
        f"/api/orders/tracking/flete-decision?token={order.tracking_token}",
        json={"decision": "rechazar", "nota": "Costo de flete supera mi presupuesto, prefiero coordinar recojo."},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["estado_flete"] == "rechazado"

    db_session.refresh(order)
    assert order.estado_flete == "rechazado"


def test_flete_decision_invalid_state(client: TestClient, db_session):
    _, _, order, _ = seed_test_data(db_session)
    # Orden está en 'pendiente', no en 'flete_cotizado'
    resp = client.post(
        f"/api/orders/tracking/flete-decision?token={order.tracking_token}",
        json={"decision": "aceptar"},
    )
    assert resp.status_code == 422
    assert "no se encuentra en estado de cotización" in resp.json()["detail"]


def test_upload_voucher_valid_image(client: TestClient, db_session):
    _, _, order, _ = seed_test_data(db_session)
    file_content = b"fake-jpeg-image-binary-content-for-testing"
    files = {"file": ("voucher_yape.jpg", io.BytesIO(file_content), "image/jpeg")}

    resp = client.post(
        f"/api/orders/tracking/voucher?token={order.tracking_token}",
        files=files,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "voucher_url" in data
    assert data["fecha_pago"] is not None

    db_session.refresh(order)
    assert order.voucher_referencia is not None
    assert order.fecha_pago is not None


def test_upload_voucher_invalid_mime_type(client: TestClient, db_session):
    _, _, order, _ = seed_test_data(db_session)
    files = {"file": ("malicious_script.sh", io.BytesIO(b"echo hack"), "application/x-sh")}

    resp = client.post(
        f"/api/orders/tracking/voucher?token={order.tracking_token}",
        files=files,
    )
    assert resp.status_code == 400
    assert "no permitido" in resp.json()["detail"].lower()


def test_upload_voucher_empty_file(client: TestClient, db_session):
    _, _, order, _ = seed_test_data(db_session)
    files = {"file": ("empty.png", io.BytesIO(b""), "image/png")}

    resp = client.post(
        f"/api/orders/tracking/voucher?token={order.tracking_token}",
        files=files,
    )
    assert resp.status_code == 400
    assert "vacío" in resp.json()["detail"].lower()


def test_admin_validate_voucher_approve(client: TestClient, db_session):
    _, product, order, admin_headers = seed_test_data(db_session)
    initial_stock = product.stock_disponible

    # Subir voucher primero
    files = {"file": ("voucher_bcp.png", io.BytesIO(b"image_content"), "image/png")}
    client.post(f"/api/orders/tracking/voucher?token={order.tracking_token}", files=files)

    # Admin valida voucher y aprueba
    resp = client.put(
        f"/api/admin/orders/{order.id}/validate-voucher",
        json={"aprobado": True, "nota": "Depósito en BCP verificado en banca móvil."},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["estado"] == "confirmado"

    # Verificar que el stock fue descontado automáticamente (2 unidades)
    db_session.refresh(product)
    assert product.stock_disponible == initial_stock - 2


def test_admin_validate_voucher_reject(client: TestClient, db_session):
    _, product, order, admin_headers = seed_test_data(db_session)
    initial_stock = product.stock_disponible

    # Subir voucher
    files = {"file": ("voucher_borroso.jpg", io.BytesIO(b"image_content"), "image/jpeg")}
    client.post(f"/api/orders/tracking/voucher?token={order.tracking_token}", files=files)

    # Admin observa el voucher
    resp = client.put(
        f"/api/admin/orders/{order.id}/validate-voucher",
        json={"aprobado": False, "nota": "Foto borrosa, no se lee el número de operación."},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    # El estado no pasa a confirmado
    assert data["estado"] == "pendiente"

    # El stock NO se descuenta
    db_session.refresh(product)
    assert product.stock_disponible == initial_stock


def test_serve_voucher_file_and_traversal_protection(client: TestClient, db_session):
    _, _, order, _ = seed_test_data(db_session)
    files = {"file": ("recibo.pdf", io.BytesIO(b"%PDF-1.4 test pdf content"), "application/pdf")}
    resp_upload = client.post(f"/api/orders/tracking/voucher?token={order.tracking_token}", files=files)
    voucher_url = resp_upload.json()["voucher_url"]

    # Si es URL local (/api/orders/voucher/...), podemos consultar el endpoint
    if "/api/orders/voucher/" in voucher_url:
        filename = voucher_url.split("/")[-1]
        resp_get = client.get(f"/api/orders/voucher/{filename}")
        assert resp_get.status_code == 200
        assert resp_get.content == b"%PDF-1.4 test pdf content"

    # Intento de Path Traversal
    resp_traversal = client.get("/api/orders/voucher/..%2F..%2Fsecret.txt")
    assert resp_traversal.status_code in (400, 404)
