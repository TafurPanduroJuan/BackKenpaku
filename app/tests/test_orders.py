from decimal import Decimal, ROUND_HALF_UP
import uuid
from app.db.models import Product, ProductCategoryEnum, ProductAcabadoEnum, Order, OrderEstadoEnum


def seed_test_order_product(db_session):
    product = Product(
        id=uuid.uuid4(),
        nombre='Tubo negro redondo 2" x 6 m',
        categoria=ProductCategoryEnum.tubos,
        acabado=ProductAcabadoEnum.negro,
        medida='2" x 6 m',
        espesor="2 mm",
        descripcion_corta="Tubo de acero negro",
        precio_unitario=Decimal("128.90"),  # PEN con IGV
        stock_disponible=10,
        activo=True,
    )
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)
    return product


def test_create_order_success_and_igv_calculation(client, db_session):
    product = seed_test_order_product(db_session)
    cantidad = 2
    # Total esperado = 128.90 * 2 = 257.80
    # Subtotal esperado = 257.80 / 1.18 = 218.4745 -> 218.47
    # IGV esperado = 257.80 - 218.47 = 39.33

    payload = {
        "cliente": {
            "nombre": "Carlos Mendoza",
            "telefono": "987654321",
            "correo": "carlos@gmail.com",
        },
        "direccion": "Av. Néstor Gambetta 456, Puente Piedra",
        "recojo_en_tienda": False,
        "observaciones": "Llamar antes de entregar",
        "acepto_privacidad": True,
        "items": [
            {
                "product_id": str(product.id),
                "cantidad": cantidad,
            }
        ],
    }

    response = client.post("/api/orders", json=payload)
    assert response.status_code == 201
    data = response.json()

    assert data["codigo"].startswith("KPK-")
    assert data["estado"] == "pendiente"
    assert Decimal(str(data["total"])) == Decimal("257.80")
    assert Decimal(str(data["subtotal"])) == Decimal("218.47")
    assert Decimal(str(data["igv"])) == Decimal("39.33")
    assert Decimal(str(data["subtotal"])) + Decimal(str(data["igv"])) == Decimal(str(data["total"]))
    assert "https://wa.me/51987654321?text=" in data["whatsapp_url"]


def test_create_order_without_privacy_returns_422(client, db_session):
    product = seed_test_order_product(db_session)
    payload = {
        "cliente": {
            "nombre": "Ana Ramos",
            "telefono": "912345678",
            "correo": "ana@gmail.com",
        },
        "acepto_privacidad": False,  # No aceptó privacidad
        "items": [{"product_id": str(product.id), "cantidad": 1}],
    }

    response = client.post("/api/orders", json=payload)
    assert response.status_code == 422


def test_create_order_insufficient_stock_returns_409(client, db_session):
    product = seed_test_order_product(db_session)  # stock = 10
    payload = {
        "cliente": {
            "nombre": "Pedro Castillo",
            "telefono": "999888777",
            "correo": "pedro@gmail.com",
        },
        "acepto_privacidad": True,
        "items": [{"product_id": str(product.id), "cantidad": 50}],  # Excede stock
    }

    response = client.post("/api/orders", json=payload)
    assert response.status_code == 409
    data = response.json()
    assert data["code"] == "STOCK_INSUFFICIENT"


def test_order_does_not_deduct_stock_on_creation(client, db_session):
    product = seed_test_order_product(db_session)
    initial_stock = product.stock_disponible  # 10

    payload = {
        "cliente": {
            "nombre": "Luis Paredes",
            "telefono": "955443322",
            "correo": "luis@gmail.com",
        },
        "acepto_privacidad": True,
        "items": [{"product_id": str(product.id), "cantidad": 3}],
    }

    response = client.post("/api/orders", json=payload)
    assert response.status_code == 201

    # Verificar que el stock en la BD NO haya cambiado al crear el pedido
    db_session.refresh(product)
    assert product.stock_disponible == initial_stock
