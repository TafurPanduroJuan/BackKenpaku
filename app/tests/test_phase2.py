import uuid
from decimal import Decimal
import pytest
from app.db.models import Product, ProductCategoryEnum, ProductAcabadoEnum


@pytest.fixture
def sample_product(db_session):
    prod = Product(
        id=uuid.uuid4(),
        nombre="Tubo Redondo LAC 2 pulg",
        categoria=ProductCategoryEnum.tubos,
        acabado=ProductAcabadoEnum.negro,
        precio_unitario=Decimal("85.50"),
        stock_disponible=50,
        activo=True,
    )
    db_session.add(prod)
    db_session.commit()
    db_session.refresh(prod)
    return prod


def test_create_order_returns_tracking_token(client, sample_product):
    payload = {
        "cliente": {
            "nombre": "Carlos Mendoza",
            "telefono": "987654321",
            "correo": "carlos@mendoza.pe",
        },
        "direccion": "Av. Los Sauces 123, Comas",
        "recojo_en_tienda": False,
        "observaciones": "Entrega por la mañana",
        "acepto_privacidad": True,
        "items": [
            {
                "product_id": str(sample_product.id),
                "cantidad": 2,
            }
        ],
    }

    res = client.post("/api/orders", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert "tracking_token" in data
    assert data["tracking_token"] is not None
    assert len(data["tracking_token"]) >= 20
    assert data["tracking_token"].startswith("kpk_")
    assert data["costo_flete"] == "0.00"
    assert data["estado_flete"] == "sin_cotizar"


def test_tracking_by_token_success(client, sample_product):
    # 1. Crear pedido
    payload = {
        "cliente": {
            "nombre": "Juan Pérez",
            "telefono": "912345678",
            "correo": "juan@perez.pe",
        },
        "recojo_en_tienda": True,
        "acepto_privacidad": True,
        "items": [{"product_id": str(sample_product.id), "cantidad": 1}],
    }
    create_res = client.post("/api/orders", json=payload)
    order_data = create_res.json()
    token = order_data["tracking_token"]
    codigo = order_data["codigo"]

    # 2. Consultar por token
    track_res = client.get(f"/api/orders/tracking?token={token}")
    assert track_res.status_code == 200
    track_data = track_res.json()
    assert track_data["codigo"] == codigo
    assert track_data["estado"] == "pendiente"
    assert track_data["recojo_en_tienda"] is True
    assert track_data["cliente_resumen"] == "Juan P."
    assert len(track_data["items"]) == 1
    assert len(track_data["events"]) >= 1
    assert "whatsapp_url" in track_data


def test_tracking_by_token_invalid_returns_uniform_404(client):
    res = client.get("/api/orders/tracking?token=kpk_invalido_token_12345")
    assert res.status_code == 404
    assert res.json()["detail"] == "No se encontró ningún pedido con los datos proporcionados."


def test_tracking_by_code_and_phone_success(client, sample_product):
    # 1. Crear pedido con teléfono estándar
    payload = {
        "cliente": {
            "nombre": "Mariana Gómez",
            "telefono": "998877665",
            "correo": "mariana@gomez.pe",
        },
        "direccion": "Puente Piedra Km 28",
        "recojo_en_tienda": False,
        "acepto_privacidad": True,
        "items": [{"product_id": str(sample_product.id), "cantidad": 3}],
    }
    create_res = client.post("/api/orders", json=payload)
    codigo = create_res.json()["codigo"]

    # 2. Consultar con formato de teléfono con espacios y prefijo +51
    track_res = client.get(f"/api/orders/tracking?codigo={codigo}&telefono=%2B51%20998%20877%20665")
    assert track_res.status_code == 200
    data = track_res.json()
    assert data["codigo"] == codigo
    assert data["cliente_resumen"] == "Mariana G."


def test_tracking_by_code_and_wrong_phone_returns_uniform_404(client, sample_product):
    payload = {
        "cliente": {
            "nombre": "Roberto Silva",
            "telefono": "944556677",
            "correo": "roberto@silva.pe",
        },
        "recojo_en_tienda": True,
        "acepto_privacidad": True,
        "items": [{"product_id": str(sample_product.id), "cantidad": 1}],
    }
    create_res = client.post("/api/orders", json=payload)
    codigo = create_res.json()["codigo"]

    # Teléfono equivocado: debe retornar 404 genérico para evitar enumeración de códigos KPK
    track_res = client.get(f"/api/orders/tracking?codigo={codigo}&telefono=999999999")
    assert track_res.status_code == 404
    assert track_res.json()["detail"] == "No se encontró ningún pedido con los datos proporcionados."


def test_tracking_missing_params_returns_400(client):
    res = client.get("/api/orders/tracking")
    assert res.status_code == 400
    assert "Debe proporcionar el token" in res.json()["detail"]


def test_tracking_does_not_expose_sensitive_pii(client, sample_product):
    payload = {
        "cliente": {
            "nombre": "Esteban Luis",
            "telefono": "997410117",
            "correo": "esteban_privado@empresa.com",
        },
        "direccion": "Calle Secreta 456, Dpto 302, Lima",
        "recojo_en_tienda": False,
        "observaciones": "Dejar en conserjería",
        "acepto_privacidad": True,
        "items": [{"product_id": str(sample_product.id), "cantidad": 1}],
    }
    create_res = client.post("/api/orders", json=payload)
    token = create_res.json()["tracking_token"]

    track_res = client.get(f"/api/orders/tracking?token={token}")
    assert track_res.status_code == 200
    data = track_res.json()

    # Verificar que NO se expongan campos privados
    assert "cliente_correo" not in data
    assert "cliente_telefono" not in data
    assert "direccion" not in data
    assert "observaciones" not in data
    # Solo resumen no invasivo
    assert data["cliente_resumen"] == "Esteban L."
