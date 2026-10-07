from decimal import Decimal
import uuid
from app.core.security import create_access_token, get_password_hash
from app.db.models import (
    Order,
    OrderEstadoEnum,
    OrderItem,
    Product,
    ProductAcabadoEnum,
    ProductCategoryEnum,
    User,
    UserRolEnum,
)


def seed_admin_and_product(db_session):
    admin = User(
        email="admin@kenpaku.pe",
        password_hash=get_password_hash("AdminKenpaku2026!"),
        rol=UserRolEnum.admin,
        activo=True,
    )
    product = Product(
        id=uuid.uuid4(),
        nombre='Tubo negro redondo 2" x 6 m',
        categoria=ProductCategoryEnum.tubos,
        acabado=ProductAcabadoEnum.negro,
        medida='2" x 6 m',
        espesor="2 mm",
        precio_unitario=Decimal("128.90"),
        stock_disponible=10,
        activo=True,
    )
    db_session.add_all([admin, product])
    db_session.commit()
    token = create_access_token(subject=admin.email)
    headers = {"Authorization": f"Bearer {token}"}
    return admin, product, headers


def test_get_dashboard(client, db_session):
    _, _, headers = seed_admin_and_product(db_session)
    response = client.get("/api/admin/dashboard", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "pedidos_pendientes" in data
    assert "pedidos_hoy" in data
    assert "consultas_chat_hoy" in data


def test_admin_confirm_order_deducts_stock(client, db_session):
    _, product, headers = seed_admin_and_product(db_session)
    initial_stock = product.stock_disponible  # 10

    # Crear pedido en estado pendiente
    order = Order(
        codigo="KPK-000001",
        cliente_nombre="Mario Vargas",
        cliente_telefono="987654321",
        cliente_correo="mario@gmail.com",
        estado=OrderEstadoEnum.pendiente,
        subtotal=Decimal("218.47"),
        igv=Decimal("39.33"),
        total=Decimal("257.80"),
        acepto_privacidad=True,
    )
    db_session.add(order)
    db_session.flush()

    item = OrderItem(
        order_id=order.id,
        product_id=product.id,
        nombre_snapshot=product.nombre,
        cantidad=4,
        precio_unitario_snapshot=product.precio_unitario,
    )
    db_session.add(item)
    db_session.commit()

    # Cambiar estado del pedido a 'confirmado' como administrador
    response = client.patch(
        f"/api/admin/orders/{order.id}/estado",
        json={"estado": "confirmado"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["estado"] == "confirmado"

    # Verificar que se haya descontado el stock (10 - 4 = 6)
    db_session.refresh(product)
    assert product.stock_disponible == initial_stock - 4


def test_admin_cancel_confirmed_order_restores_stock(client, db_session):
    _, product, headers = seed_admin_and_product(db_session)
    product.stock_disponible = 6
    db_session.commit()

    order = Order(
        codigo="KPK-000002",
        cliente_nombre="Roberto Gomez",
        cliente_telefono="911223344",
        cliente_correo="roberto@gmail.com",
        estado=OrderEstadoEnum.confirmado,  # Ya estaba confirmado
        subtotal=Decimal("218.47"),
        igv=Decimal("39.33"),
        total=Decimal("257.80"),
        acepto_privacidad=True,
    )
    db_session.add(order)
    db_session.flush()

    item = OrderItem(
        order_id=order.id,
        product_id=product.id,
        nombre_snapshot=product.nombre,
        cantidad=4,
        precio_unitario_snapshot=product.precio_unitario,
    )
    db_session.add(item)
    db_session.commit()

    # Cambiar estado a 'cancelado'
    response = client.patch(
        f"/api/admin/orders/{order.id}/estado",
        json={"estado": "cancelado"},
        headers=headers,
    )
    assert response.status_code == 200

    # Verificar restitución de stock (6 + 4 = 10)
    db_session.refresh(product)
    assert product.stock_disponible == 10


def test_admin_product_crud(client, db_session):
    _, _, headers = seed_admin_and_product(db_session)

    # 1. Crear producto
    create_payload = {
        "nombre": "Plancha LAF 2mm",
        "categoria": "planchas",
        "acabado": "negro",
        "medida": "1.20 x 2.40 m",
        "espesor": "2 mm",
        "descripcion_corta": "Plancha laminada en frio de 2mm",
        "precio_unitario": 210.00,
        "stock_disponible": 15,
        "activo": True,
    }
    resp_create = client.post(
        "/api/admin/products", json=create_payload, headers=headers
    )
    assert resp_create.status_code == 201
    prod_data = resp_create.json()
    prod_id = prod_data["id"]
    assert prod_data["nombre"] == "Plancha LAF 2mm"

    # 2. Actualización rápida de stock y precio
    patch_payload = {"stock_disponible": 20, "precio_unitario": 205.50}
    resp_patch = client.patch(
        f"/api/admin/products/{prod_id}/stock-precio",
        json=patch_payload,
        headers=headers,
    )
    assert resp_patch.status_code == 200
    assert resp_patch.json()["stock_disponible"] == 20
    assert Decimal(str(resp_patch.json()["precio_unitario"])) == Decimal("205.50")

    # 3. Baja lógica
    resp_delete = client.delete(
        f"/api/admin/products/{prod_id}", headers=headers
    )
    assert resp_delete.status_code == 200
    assert resp_delete.json()["code"] == "SUCCESS"

    # Verificar que el producto está inactivo en BD
    db_prod = db_session.query(Product).filter(Product.id == uuid.UUID(prod_id)).first()
    assert db_prod.activo is False
